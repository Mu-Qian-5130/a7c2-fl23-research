"""Run continuous lifecycle code against an explicit virtual pixel device.

This exercises the NEW controller, including real test-buffer/file contents.
It never mocks an original firmware service, loads a camera image, talks to
USB or produces an installable candidate. Native adapters remain unbound.
"""
import argparse
import hashlib
import json
from pathlib import Path
import random

from support.build import compile_shared
from support.memory import MEM
from support.workflow_model import WorkflowVM, STATE, ACTION, COMPLETION, OFFER, NATIVE


def exercise(elf,arch,folder):
    reports=[];serial=0
    def new(name,**options):
        nonlocal serial
        serial+=1
        return WorkflowVM(elf,arch,folder/f'{serial:03d}-{name}',**options)
    def record(name,v,expected=None,leases=None):
        outcome=v.assert_closed(expected,leases) if expected is not None else dict(
            phase=v.state()['phase'],retained_leases=v.state()['count'],
            no_automatic_retry_or_restore=True)
        report=dict(case=name,**outcome,events=v.journal,offers=v.offers)
        reports.append(report)
    def armed(name,**options):
        v=new(name,**options);assert v.drive()==0 and v.state()['phase']==4
        return v
    def stop_at(name,kind):
        v=armed(name);assert v.offer(1,9_900_000)==1
        assert v.trigger(10_000_000)==1
        for _ in range(30):
            a=v.next();assert isinstance(a,dict)
            if a['kind']==kind:return v,a
            assert v.finish(a)==1
        raise AssertionError('Requested boundary was never reached')
    def uncertain(name,v,a,**wrong):
        c=v.apply(a);c.pop('_released_handle',None);c.update(wrong)
        assert v.deliver(c)==-5 and v.state()['phase']==11
        frozen=bytes(v.cpu.mem_read(STATE,920))
        assert v.next()==-5 and v.cancel()==-5
        assert v.call('rearm',STATE,v.generation+1)==-16
        assert bytes(v.cpu.mem_read(STATE,920))==frozen
        record(name,v)

    # Full transaction with actual virtual pixels and queued post-edge frames.
    v=armed('continuous-save')
    for lease,tick in enumerate((8_800_000,9_001_000,9_500_000,9_999_999),1):
        assert v.offer(lease,tick)==1;assert v.drive()==0
    assert v.trigger(10_000_000)==1
    assert v.offer(5,10_000_000)==1  # Finishes at S2; not a pre-trigger exposure.
    v.pending_frames.append((6,10_100_000))
    assert v.cancel()==0  # S1 released AFTER full press must preserve saves.
    assert v.drive()==0
    record('continuous-save',v,1,[2,3,4])
    assert [e['kind'] for e in v.journal if e['event']=='request'][:3]==[1,2,3]

    for mode in (True,'mixed'):
        v=armed('save-consumes-reference-'+str(mode),save_consumes=mode)
        for lease in (1,2,3):assert v.offer(lease,9_500_000+lease*100_000)==1
        assert v.trigger(10_000_000)==1 and v.drive()==0
        record('save-consumes-reference-'+str(mode),v,1,[1,2,3])
        release_leases=[e['lease'] for e in v.journal if e['event']=='request' and e['kind']==7]
        assert release_leases==([] if mode is True else [1,3]),'No second release after consuming SAVE'

    v=armed('half-release');assert v.offer(1,9_900_000)==1
    assert v.cancel()==1;assert v.drive()==0;record('half-release',v,2,[])
    v=armed('no-pretrigger');assert v.trigger(10_000_000)==1
    assert v.drive()==0;record('no-pretrigger',v,3,[])
    v=armed('capacity-pressure',capacity=2)
    assert v.offer(1,9_800_000)==v.offer(2,9_900_000)==1
    assert v.offer(3,9_950_000)==-28 and v.state()['rejected']==1
    assert v.trigger(10_000_000)==1;assert v.drive()==0
    record('capacity-pressure',v,1,[1,2])

    # 32nd saved-bit, 64-bit exposure ticks and baseline flag1 are intentional.
    v=armed('full-capacity-wide-clock',capacity=32,original_flag=1)
    edge=(1<<40)+10_000_000
    for lease in range(1,33):assert v.offer(lease,edge-(33-lease)*1000)==1
    assert v.offer(33,edge-1)==-28
    assert v.trigger(edge)==1;assert v.drive()==0
    record('full-capacity-wide-clock',v,1,list(range(1,33)))

    for kind in (1,2,3):
        v=new(f'cancel-in-flight-{kind}')
        for _ in range(kind):
            a=v.next();assert isinstance(a,dict)
            if a['kind']==kind:break
            assert v.finish(a)==1
        c=v.apply(a)
        if kind==3:assert v.offer(1,9_900_000)==1
        assert v.cancel()==1 and v.deliver(c)==1
        assert v.drive()==0;record(f'cancel-in-flight-{kind}',v,2,[])
        requested=[e['kind'] for e in v.journal if e['event']=='request']
        if kind<3:assert 3 not in requested
    v=new('cancel-before-first-request');assert v.cancel()==1
    assert v.drive()==0;record('cancel-before-first-request',v,2,[])
    for full in (False,True):
        v=new('edge-before-start-request-'+str(full))
        for _ in range(2):assert v.finish(v.next())==1
        assert (v.trigger(10_000_000) if full else v.cancel())==1
        assert v.drive()==0
        assert 3 not in [e['kind'] for e in v.journal if e['event']=='request']
        record('edge-before-start-request-'+str(full),v,3 if full else 2,[])

    v=new('full-press-before-start-completion')
    for _ in range(2):assert v.finish(v.next())==1
    a=v.next();assert a['kind']==3;c=v.apply(a)
    assert v.offer(1,9_900_000)==1 and v.trigger(10_000_000)==1
    assert v.deliver(c)==1 and v.drive()==0
    record('full-press-before-start-completion',v,1,[1])

    for full in (False,True):
        v=armed('edge-during-expired-release-'+str(full))
        assert v.offer(1,8_000_000)==v.offer(2,9_900_000)==1
        a=v.next();assert a['kind']==7
        assert (v.trigger(10_000_000) if full else v.cancel())==1
        assert v.finish(a)==1 and v.drive()==0
        record('edge-during-expired-release-'+str(full),v,1 if full else 2,[2] if full else [])

    # Old/wrong/duplicate service events cannot advance the current action.
    for field,value in (('ticket',999),('generation',6),('kind',9)):
        v=new('foreign-ack-'+field);a=v.next();before=bytes(v.cpu.mem_read(STATE,920))
        assert v.deliver(v.completion(a,**{field:value}))==-116
        assert bytes(v.cpu.mem_read(STATE,920))==before
        assert v.finish(a)==1;assert v.cancel()==1 and v.drive()==0
        before=bytes(v.cpu.mem_read(STATE,920))
        assert v.deliver(v.completion(a))==-116
        assert bytes(v.cpu.mem_read(STATE,920))==before
        record('foreign-and-duplicate-ack-'+field,v,2,[])

    # Unknown, stale or contradictory *matched* outcomes must hold ownership.
    v=new('unknown-configure');a=v.next();uncertain('unknown-configure',v,a,outcome=2)
    for field,value in (('value',20),('auxiliary',0)):
        v=new('stale-refresh-'+field);assert v.finish(v.next())==1;a=v.next()
        uncertain('stale-refresh-'+field,v,a,**{field:value})
    v=new('stale-start');assert v.finish(v.next())==v.finish(v.next())==1
    a=v.next();uncertain('stale-start',v,a,value=20)
    for kind,field,value in ((4,'outcome',2),(5,'value',6),(5,'serial',0),
                             (6,'outcome',2),(7,'outcome',2),
                             (8,'value',0),(9,'value',20),(9,'auxiliary',1)):
        name=f'held-{kind}-{field}';v,a=stop_at(name,kind)
        uncertain(name,v,a,**{field:value})
        if kind==6:
            assert v.saved and v.state()['count']==1
            assert v.state()['saved']==0  # File exists; its completion is unknown.

    v,a=stop_at('bad-save-lease',6)
    uncertain('bad-save-lease',v,a,lease=2)
    v,a=stop_at('unknown-save-reference-disposition',6)
    uncertain('unknown-save-reference-disposition',v,a,value=2)
    v,a=stop_at('late-ingress-after-fence',5);assert v.finish(a)==1
    assert v.offer(2,10_100_000)==-5 and v.state()['phase']==11
    assert v.next()==-5;record('late-ingress-after-fence',v)
    v=armed('reordered-exposure-clock');assert v.offer(1,9_900_000)==1
    assert v.offer(2,9_800_000)==-5 and v.next()==-5
    record('reordered-exposure-clock',v)
    v=armed('late-S2-edge');assert v.offer(1,10_100_000)==1
    assert v.trigger(10_000_000)==-5 and v.next()==-5
    record('late-S2-edge',v)

    # A marker without the native class/kind/error contract does not transfer RAW.
    for options in (dict(marker=1),dict(cls=0),dict(kind=8),dict(error=1)):
        name='bad-profile-'+next(iter(options));v=armed(name)
        assert v.offer(1,9_900_000,**options)==-84 and not v.ledger
        assert v.trigger(10_000_000)==1 and v.drive()==0
        record(name,v,3,[])

    v=armed('input-aliases');frozen=bytes(v.cpu.mem_read(STATE,920))
    assert v.call('next',STATE,STATE)==-22
    assert v.call('complete',STATE,STATE)==-22
    assert v.call('frame',STATE,7,1,STATE,NATIVE)==-22
    assert v.call('frame',STATE,7,1,OFFER,STATE)==-22
    assert bytes(v.cpu.mem_read(STATE,920))==frozen
    assert v.call('begin',STATE,7,500,8,1,9,20,0)==-16
    assert v.cancel()==1 and v.drive()==0;record('input-aliases-and-reentry',v,2,[])

    v=armed('repeat-transactions')
    assert v.call('rearm',STATE,8)==-16
    for generation in (7,8,9):
        if generation!=7:
            v.rearm(generation);assert v.drive()==0
            frozen=bytes(v.cpu.mem_read(STATE,920))
            assert v.offer(99,9_900_000,generation=generation-1)==-116
            assert bytes(v.cpu.mem_read(STATE,920))==frozen
        assert v.offer(1,9_900_000)==1
        assert (v.trigger(10_000_000) if generation!=8 else v.cancel())==1
        assert v.drive()==0
        v.assert_closed(2 if generation==8 else 1,[] if generation==8 else [1])
        frozen=bytes(v.cpu.mem_read(STATE,920))
        assert v.call('rearm',STATE,generation)==-22
        assert bytes(v.cpu.mem_read(STATE,920))==frozen
    record('repeated-save-cancel-save-same-state',v,1,[1])

    v=armed('rearm-exhausted-epoch',epoch=0xfffffffd)
    assert v.cancel()==1 and v.drive()==0
    frozen=bytes(v.cpu.mem_read(STATE,920))
    assert v.call('rearm',STATE,8)==-75
    assert bytes(v.cpu.mem_read(STATE,920))==frozen
    record('rearm-exhausted-epoch',v,2,[])

    # Invalid admission must not turn zero storage into an initialized session.
    for index,value in ((1,0),(1,0xffffffff),(2,4),(2,1001),(3,0),(3,33),
                        (4,2),(6,0),(6,0xfffffffe),(7,2)):
        v=new(f'invalid-begin-{index}-{value}')
        v.cpu.mem_write(STATE,bytes(920))
        args=[STATE,7,500,8,1,9,20,0];args[index]=value
        assert v.call('begin',*args)==-22
        assert bytes(v.cpu.mem_read(STATE,920))==bytes(920)
        reports.append(dict(case=f'invalid-begin-{index}-{value}',state_untouched=True))

    # Independent reference selection from ALL generated physical test frames.
    # Capacity here exceeds the maximum in-window frame count, so checking
    # against every generated frame does not mirror the controller's slots.
    rng=random.Random(0xA7C2)
    for run in range(20):
        duration=rng.choice((5,100,500,1000))
        v=armed(f'random-{run}',duration=duration,capacity=32,
                original_policy=run%2,original_limit=run+3,original_flag=run%2)
        tick=(1<<35)+3_000_000;generated=[]
        for lease in range(1,rng.randrange(3,32)):
            tick+=rng.randrange(100_000,300_000)
            assert v.offer(lease,tick)==1;generated.append((lease,tick))
            assert v.drive()==0
        edge=tick+rng.randrange(1,400_000)
        if run%4:
            assert v.trigger(edge)==1;assert v.trigger(edge)==0
            assert v.cancel()==0
            expected=[lease for lease,end in generated if edge-duration*2000<=end<edge]
            assert v.drive()==0
            record(f'random-save-{run}',v,1 if expected else 3,expected)
        else:
            assert v.cancel()==1 and v.drive()==0
            record(f'random-cancel-{run}',v,2,[])
    return reports


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--zig',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args();args.output.mkdir(parents=True,exist_ok=False)
    result={}
    for arch in ('thumb','aarch64'):
        elf=args.output/(arch+'-workflow.elf')
        compile_shared(args.zig,arch,elf,[Path(__file__).with_name('capture_workflow.c'),
                                        Path(__file__).with_name('frame_route.c')])
        result[arch]=dict(cases=exercise(elf,arch,args.output/arch),
                          ELF_sha256=hashlib.sha256(elf.read_bytes()).hexdigest())
    # Full byte comparison of the virtual saved images across target ISAs.
    thumb_files={p.relative_to(args.output/'thumb') for p in (args.output/'thumb').rglob('*.pgm')}
    arm64_files={p.relative_to(args.output/'aarch64') for p in (args.output/'aarch64').rglob('*.pgm')}
    assert thumb_files==arm64_files
    for thumb in (args.output/'thumb').rglob('*.pgm'):
        peer=args.output/'aarch64'/thumb.relative_to(args.output/'thumb')
        assert thumb.read_bytes()==peer.read_bytes()
    assert result['thumb']['cases']==result['aarch64']['cases'],'Cross-ISA lifecycle trace mismatch'
    sources=[Path(__file__),Path(__file__).with_name('capture_workflow.c'),
             Path(__file__).with_name('capture_workflow.h'),Path(__file__).with_name('frame_route.c'),
             Path(__file__).with_name('support')/'workflow_model.py']
    report=dict(schema='OFFLINE_CONTINUOUS_CAPTURE_LIFECYCLE/1',camera_io=False,
        native_firmware_loaded=False,native_services_mocked=False,
        device_model='explicit virtual pixel allocations, event queue and fsynced PGM writer',
        implementation=result,physical_precapture_complete=False,
        cross_ISA_action_traces_identical=True,cross_ISA_virtual_pixel_files_identical=True,
        sources={str(p.relative_to(Path(__file__).parent)):hashlib.sha256(p.read_bytes()).hexdigest() for p in sources},
        limits=['Native source/task/clock/RAW-reference/terminal bindings are not supplied',
                'Simulated exposures and image files are synthetic test fixtures, not Sony photos',
                'Original firmware services are not executed or replaced with success',
                'No boot, hardware safety, actual pixel capacity or physical restoration is established'])
    (args.output/'workflow.private.json').write_text(json.dumps(report,indent=2)+'\n',encoding='utf-8')
    for arch,d in result.items():print(f'{arch}: {len(d["cases"])} continuous/failure scenarios; virtual pixel files verified.')


if __name__=='__main__':main()
