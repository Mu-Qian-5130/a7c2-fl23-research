"""Launch the real app with existing task records, without camera access."""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile

ROOT=Path(__file__).resolve().parents[2]


def run(command,*,cases=None):
    cases=cases or ('factory_connection_failed','factory_interrupted','factory_awaiting_reload','factory_loaded','factory_temp_conflict','setup_waiting')
    results={}
    with tempfile.TemporaryDirectory(prefix='a7c2-existing-state-') as temporary:
        for name in cases:
            root=(Path(temporary)/name).resolve();root.mkdir()
            work=root/'work/previous';work.mkdir(parents=True)
            if name=='setup_waiting':
                record=work/'setup.private.json'
                state=dict(schema='a7c2-one-click/1',phase='WAIT_RELOAD',options=dict(looks=[],fl23=True,sound=False,vertical=False,plugin=False))
                settings=dict(setup_work=str(work))
            else:
                record=work/'direct.private.json'
                state=dict(schema='a7c2-direct-job/1',mode='factory_reset',phase='NEEDS_REVIEW',failed_during='READING',
                           journal=[],error='[Errno None] Other error')
                if name=='factory_interrupted':state.update(failed_during='WRITING',identity=dict(model='ILCE-7CM2'),
                    journal=[dict(event='native_intent',mode=2)])
                if name=='factory_awaiting_reload':state.update(phase='AWAITING_RELOAD')
                if name=='factory_loaded':state.update(phase='LOADED',readonly_after_reload_verified=True)
                if name=='factory_temp_conflict':state.update(failed_during='PLANNED',
                    error='Existing temporary state needs recovery: lut-names-staged.so')
                settings=dict(factory_direct_work=str(work),factory_failed_work=str(work))
            record.write_text(json.dumps(state),encoding='utf-8')
            config=root/'desktop.json';config.write_text(json.dumps(settings),encoding='utf-8')
            originals={path:path.read_bytes() for path in (record,config)}
            env=dict(os.environ,A7C2_DESKTOP_DATA=str(root),QT_QPA_PLATFORM='offscreen',PYTHONUTF8='1')
            # Do not inherit pytest's module paths: this omission masked the bug.
            env.pop('PYTHONPATH',None)
            done=subprocess.run([*command,'--smoke-test'],env=env,cwd=temporary,capture_output=True,
                                text=True,encoding='utf-8',errors='replace',timeout=45)
            if done.returncode:
                raise RuntimeError('Existing-state startup failed: '+name+'; exit '+str(done.returncode)+'\n'+done.stdout+'\n'+done.stderr)
            pages=list(root.glob('desktop-page-*.png'))
            if len(pages)!=7:raise RuntimeError('Incomplete GUI startup pages for '+name)
            for path,raw in originals.items():
                if path.read_bytes()!=raw:raise RuntimeError('Startup altered previous task evidence: '+str(path))
            results[name]=dict(exit_code=0,pages=7,old_records_preserved=True,camera_io=False)
    return dict(camera_io=False,cases=results)


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--app',type=Path)
    parser.add_argument('--report',type=Path,default=ROOT/'dist/startup-state-self-test.json')
    args=parser.parse_args()
    command=[str(args.app.resolve())] if args.app else [sys.executable,str(ROOT/'desktop.py')]
    result=run(command);args.report.parent.mkdir(parents=True,exist_ok=True)
    args.report.write_text(json.dumps(result,indent=2),encoding='utf-8');print(json.dumps(result))
