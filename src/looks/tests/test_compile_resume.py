"""Plain frozen input comparisons protect interrupted Hybrid compilation."""
import json
from pathlib import Path
from unittest.mock import patch
import pytest
from looktool import compilelook,r5fit
from test_compile_dcp_offline import dcp

@pytest.mark.parametrize('source_type,changed',[
    ('dcp','calibration'),('cube','calibration'),
    ('dcp','custom_bridge'),('dcp','bundled_bridge'),
    ('dcp','legacy_manifest'),('cube','legacy_manifest')])
def test_resume_rejects_changed_input_contents(tmp_path,monkeypatch,capsys,source_type,changed):
    bundled=Path(compilelook.__file__).resolve().parents[3]/'src/looks/assets/rendering-model-v1.json'
    bridge=tmp_path/'src/looks/assets/rendering-model-v1.json';bridge.parent.mkdir(parents=True)
    bridge.write_bytes(bundled.read_bytes())
    monkeypatch.setattr(compilelook,'__file__',str(tmp_path/'src/looks/looktool/compilelook.py'))
    calibration=tmp_path/'response.json';calibration.write_bytes((r5fit.ROOT/'data/response.json').read_bytes())
    source=tmp_path/('source.'+source_type);work=tmp_path/'work';output=tmp_path/'result.a7look'
    argv=[str(source),'--name','Resume fixture','--output',str(output),'--calibration',str(calibration),'--work',str(work)]
    if source_type=='cube':
        source.write_text('LUT_3D_SIZE 2\n0 0 0\n1 0 0\n0 1 0\n1 1 0\n0 0 1\n1 0 1\n0 1 1\n1 1 1\n')
        argv+=['--input-space','sony-st-srgb']
    else:
        dcp(source)
        if changed=='custom_bridge':
            custom=tmp_path/'custom.json';custom.write_bytes(bridge.read_bytes());bridge=custom
            argv+=['--dcp-bridge',str(bridge)]
    with patch.object(r5fit,'fit',side_effect=RuntimeError('interrupted fit'))as fit:
        for _ in range(2):
            with pytest.raises(RuntimeError,match='interrupted fit'):compilelook.main(argv)
        cache=work/'preserved-progress.json';cache.write_text('{"stage":"already-completed"}')
        before=cache.read_bytes()
        if changed=='calibration':
            value=json.loads(calibration.read_text(encoding='utf-8'));value['name']='changed calibration';calibration.write_text(json.dumps(value),encoding='utf-8')
        elif changed.endswith('bridge'):
            value=json.loads(bridge.read_text(encoding='utf-8'));value['reference_exposure_stops']+=1;bridge.write_text(json.dumps(value),encoding='utf-8')
        else:
            manifest=work/'request.json';value=json.loads(manifest.read_text(encoding='utf-8'));value.pop('algorithm');manifest.write_text(json.dumps(value),encoding='utf-8')
        with pytest.raises(SystemExit)as error:compilelook.main(argv)
        assert error.value.code==2 and 'new work directory'in capsys.readouterr().err
        assert fit.call_count==2 and cache.read_bytes()==before and not output.exists()
