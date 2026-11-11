"""Offline C2 DCP/CUBE target evaluation and current Hybrid fitter entry."""

import json
from pathlib import Path

def save(path, value):
    path.write_text(json.dumps(value,ensure_ascii=False,indent=2,allow_nan=False)+'\n',encoding='utf-8')

def cube_targets(source,path,input_space,bridge=None):
    import numpy as np
    from .references import Cube
    if not input_space or (input_space=='sony-st-srgb')==bool(bridge):
        raise ValueError('Specify Sony ST sRGB directly, or a named input space and an explicit bridge')
    source=np.asarray(source)
    entering=Cube(bridge).sample(source) if bridge else source
    value=Cube(path).sample(entering)
    return np.clip(value,0,1),dict(input_space=input_space,output_space='srgb',
        bridge_used=bool(bridge),clipped_output_components=int(((value<0)|(value>1)).sum()),
        Lightroom_reference_used=False,automatic_Adobe_profile_generated=False)

def dcp_targets(source,path,bridge=None):
    """Evaluate supported DCP look/tone stages locally against the ST bridge."""
    import numpy as np
    from .references import DcpLook
    from .calibration import inverse_st,validate
    from .rawprofiles import dcp_info
    root=Path(__file__).resolve().parents[3]
    bridge_path=Path(bridge) if bridge else root/'src/looks/assets/rendering-model-v1.json'
    mapping=validate(json.loads(bridge_path.read_text(encoding='utf-8')),True)
    info=dcp_info(path)
    if info['model']!='Sony ILCE-7CM2':raise ValueError('Select a Sony ILCE-7CM2 DCP; foreign sensor calibration is not copied')
    look=DcpLook(path)
    target=look.render(inverse_st(source,mapping),float(mapping.get('reference_exposure_stops',0)))
    report=look.inventory()
    report.update(renderer='builtin-DCP-look-tone',Lightroom_reference_used=False,
        bridge_evidence=mapping['evidence'],bridge_is_shared_approximation=bridge is None,
        calibration_scope='LookTable and ProfileToneCurve only; camera matrices and HueSat maps are not copied',
        camera_io=False)
    return np.clip(target,0,1),report,info

def main(argv=None):
    from .compilehybrid import main as compile_current
    return compile_current(argv)

if __name__=='__main__':raise SystemExit(main())
