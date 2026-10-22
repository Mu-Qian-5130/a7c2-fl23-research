"""Explain recorded job failures using only local files and the standard library.

Never imports USB, authenticates service, changes state or deletes temporary
files. Historical evidence is not proof of the camera's current contents.
"""
import argparse,gzip,json,struct
from pathlib import Path

NAME_REPORT=struct.Struct('<8sIIII7q6I32s')
LINUX_ERRNO={2:'ENOENT',5:'EIO',13:'EACCES',16:'EBUSY',17:'EEXIST',22:'EINVAL',27:'EFBIG',28:'ENOSPC',30:'EROFS',75:'EOVERFLOW',84:'EILSEQ',116:'ESTALE'}

def name_report(raw,expected_mode=None,build=None):
    if len(raw)!=NAME_REPORT.size:raise ValueError('Expected exactly 136 bytes for the native name report')
    v=NAME_REPORT.unpack(raw)
    if v[:2]!=(b'A7NMR001',1):raise ValueError('Unsupported native name report ABI')
    status=v[5];phase=v[3]
    detail={'mode':v[2],'phase':phase,'files':v[4],'status':status,
        'status_name':LINUX_ERRNO.get(-status,'LINUX_ERRNO_'+str(-status)) if status else 'OK',
        'rollback':v[6],'remount':v[7],'readonly':v[8],'cleanup':v[9],
        'running_as_root':v[10]==0,'pid_present':v[11]>0,
        'staged':v[12],'linked':v[13],'committed':v[14],'restored':v[15],'removed_backups':v[16],
        'requested_mode_matches':None if expected_mode is None else v[2]==expected_mode,
        'ap_matches_job':None,'historical_evidence_only':True}
    if build:
        expected=build.get('target_AP',build.get('AP')) if v[2]==3 else build.get('AP')
        if isinstance(expected,str) and len(expected)==64:
            detail['ap_matches_job']=v[18].hex()==expected.lower()
    detail['stage']={0:'request or permissions',1:'preflight',2:'preflight passed',
        3:'recreate missing originals' if v[2]==2 else 'stage renamed resources',
        4:'link originals',5:'commit names',6:'restore name resources',7:'remove old links',9:'worker finished'}.get(phase,'unknown')
    return detail

def name_failure_text(raw,mode,build):
    d=name_report(raw,mode,build)
    return ('Native name transaction incomplete: requested_mode=%s, mode=%s, phase=%s, status=%s (%s), '
            'rollback=%s, remount=%s, readonly=%s, cleanup=%s, AP_match=%s; '
            'staged=%s, linked=%s, committed=%s, restored=%s; '
            'preserve this job and inspect/recover its existing result, do not repeat restore.' %
            (mode,d['mode'],d['phase'],d['status'],d['status_name'],d['rollback'],d['remount'],d['readonly'],d['cleanup'],d['ap_matches_job'],
             d['staged'],d['linked'],d['committed'],d['restored']))

def read_limited(path,limit):
    with (gzip.open(path,'rb') if path.suffix=='.gz' else path.open('rb')) as stream:raw=stream.read(limit+1)
    if len(raw)>limit:raise ValueError('Diagnostic input exceeds its size limit')
    return raw

def explain(folder,report_path=None):
    root=Path(folder);state=json.loads(read_limited(root/'job.private.json',8*1024*1024))
    if state.get('schema')!='a7c2-lut-device-job/1':raise ValueError('Unsupported job schema')
    phase=state.get('phase');failed=state.get('failed_during');error=state.get('error','')
    result={'camera_io':False,'state_modified':False,'phase':phase,'failed_during':failed,
        'active_operation':state.get('active_operation'),'historical_evidence_only':True}
    if not isinstance(error,str):error=''
    if 'Existing temporary state' in error:
        result.update(problem='pending_shared_temporary_state',next_step='Recover the FIRST failing job that owns the pending files; do not delete them or switch jobs.')
    elif 'Complete host readback differs' in error:
        result.update(problem='current_program_differs_from_job',next_step='Check later jobs/changes. Full rollback uses recovery.py; selected-slot restoration uses restore-slot. Preserve unknown outcomes instead of replaying this job.')
    elif failed=='NAME_RESTORE_INTENT':
        result.update(problem='name_restoration_needs_inspection',next_step='Run recover on THIS job; resume only after it establishes PROGRAMS_RESTORED or PARTIAL_NAMES_RESTORE_VERIFIED.')
    else:
        result.update(problem='recorded_job_state',next_step='Inspect the recorded phase before any new write. This command does not determine current camera state.')
    intents=[e for e in state.get('journal',[]) if e.get('event')=='native_intent']
    if intents:
        intent=intents[-1];result['last_native_intent']={'result':intent.get('result'),'mode':intent.get('mode')}
    if report_path is None:
        matches=[p for p in (root/'evidence').glob('*names-2.bin*') if p.is_file() and p.name.endswith(('.bin','.bin.gz'))]
        if matches:report_path=max(matches,key=lambda p:p.stat().st_mtime_ns)
    if report_path is not None:
        result['native_name_report']=name_report(read_limited(Path(report_path),NAME_REPORT.size),2,state.get('name_build'))
    else:result['native_name_report']=None
    return result

def main(argv):
    p=argparse.ArgumentParser(prog='lut.py diagnose-job',description=__doc__)
    p.add_argument('job',type=Path);p.add_argument('--names-report',type=Path)
    args=p.parse_args(argv[1:]);print(json.dumps(explain(args.job,args.names_report),ensure_ascii=False,indent=2));return 0
