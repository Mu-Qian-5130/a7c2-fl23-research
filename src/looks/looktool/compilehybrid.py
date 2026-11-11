"""Offline CUBE/DCP conversion through the current complete C2 native fitter."""
import argparse
import base64
import copy
import json
from pathlib import Path
import shutil
import uuid

def main(argv=None):
    from . import r5fit,lookfile,looklabels,editrecipe,rawidentity,dcpexport
    from . import compilelook
    from .compilelook import cube_targets,dcp_targets
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('source',type=Path)
    p.add_argument('--name',required=True)
    p.add_argument('--output',type=Path,required=True)
    p.add_argument('--dcp-output',type=Path,help='Companion DCP; default is the A7Look filename with .dcp')
    p.add_argument('--work',type=Path)
    p.add_argument('--calibration',type=Path,default=r5fit.ROOT/'data/response.json')
    p.add_argument('--config',type=Path,help=argparse.SUPPRESS)
    p.add_argument('--passes',type=int,default=12,help='Native starts, 2..12; formal default 12')
    p.add_argument('--evaluations',type=int,default=2000)
    p.add_argument('--extra-colors',type=int,default=0,help=argparse.SUPPRESS)
    p.add_argument('--menu-icon-text')
    p.add_argument('--without-menu-icon',action='store_true')
    p.add_argument('--dcp-bridge',type=Path)
    p.add_argument('--input-space')
    p.add_argument('--bridge',type=Path)
    p.add_argument('--raw-dcp',type=Path)
    a=p.parse_args(argv)
    if a.extra_colors!=0:p.error('Hybrid uses the frozen C2 cohort; the legacy extra-colors option no longer applies')
    if a.config and a.config.is_file()and json.loads(a.config.read_text(encoding='utf-8')):
        p.error('Legacy virtual-model configuration no longer applies; select a C2 Hybrid response JSON and explicit bridge options')
    if a.source.suffix.lower()not in ('.dcp','.cube')or not a.source.is_file():p.error('Select an existing DCP or CUBE')
    if a.output.suffix.lower()!='.a7look'or a.output.exists():p.error('Choose a new .a7look output filename')
    companion=a.dcp_output or a.output.with_suffix('.dcp')
    if companion.suffix.lower()!='.dcp':p.error('Companion output must be a .dcp file')
    if not 2<=a.passes<=12 or a.evaluations<1:p.error('Use 2..12 native starts and positive evaluations')
    if a.calibration.suffix.lower()!='.json'or not a.calibration.is_file():p.error('Select the new C2 Hybrid response JSON')
    cube=a.source.suffix.lower()=='.cube'
    if cube:
        if not a.input_space or (a.input_space=='sony-st-srgb')==bool(a.bridge):p.error('CUBE requires Sony ST sRGB, or a named space with an explicit bridge')
    elif a.input_space or a.bridge or a.raw_dcp:p.error('Input space, bridge and raw-dcp apply only to CUBE')
    try:name,icon=looklabels.metadata(a.name,source=a.source,icon_text=a.menu_icon_text,include_icon=not a.without_menu_icon)
    except ValueError as error:p.error(str(error))
    work=a.work or a.output.with_suffix('.work');work.mkdir(parents=True,exist_ok=True)
    def freeze(path,name):
        content=Path(path).read_bytes();dest=work/name
        if dest.exists()and dest.read_bytes()!=content:p.error('Compilation inputs changed; use a new work directory')
        if not dest.exists():dest.write_bytes(content)
        return dest
    copied=freeze(a.source,'input'+a.source.suffix.lower())
    response=freeze(a.calibration,'response.json')
    bridge=freeze(a.bridge,'bridge.cube')if a.bridge else None
    dcp_bridge=None
    if not cube:dcp_bridge=freeze(a.dcp_bridge or Path(compilelook.__file__).resolve().parents[3]/'src/looks/assets/rendering-model-v1.json','dcp-bridge.json')
    paired=freeze(a.raw_dcp,'raw-source.dcp')if a.raw_dcp else None
    import numpy as np
    r5fit.initialize(calibration=response)
    from compute_backend import render_native
    from patch_sampling import center_mean
    with np.load(r5fit.ROOT/'data/inputs.npz')as z:inputs=z['input'].copy()
    source=center_mean(render_native(r5fit.context(),inputs))/16383
    raw_profile=None;source_reference=None
    if cube:
        target,contract=cube_targets(source,copied,a.input_space,bridge)
        source_reference=dict(schema='a7c2-source-cube/1',filename=a.source.name,input_space=a.input_space,cube_base64=base64.b64encode(copied.read_bytes()).decode('ascii'))
        if bridge:source_reference['bridge_base64']=base64.b64encode(bridge.read_bytes()).decode('ascii')
    else:
        target,contract,info=dcp_targets(source,copied,dcp_bridge)
    # Frozen byte copies provide the resume contract. Existing diagnostic
    # fingerprints from the DCP inventory are not used as new validation gates.
    request_contract={k:v for k,v in contract.items()if 'sha256'not in k and 'digest'not in k}
    request=dict(algorithm=r5fit.COMMIT,calibration=json.loads(response.read_text(encoding='utf-8')),evaluations=a.evaluations,starts=a.passes,contract=request_contract)
    # Inventory tuples become arrays on disk; compare the same JSON value on
    # both sides so an unchanged interrupted DCP fit can resume.
    request=json.loads(json.dumps(request,allow_nan=False))
    saved=work/'request.json'
    if saved.exists()and json.loads(saved.read_text(encoding='utf-8'))!=request:p.error('Compilation options changed; choose a new work directory')
    if not saved.exists():r5fit.save(saved,request)
    generated_report=None
    if cube and paired is None:
        base=freeze(dcpexport.BASE,'camera-st-base.dcp')
        profile_source=work/'generated-reference.dcp';record=work/'dcp-generation.json'
        if profile_source.exists()and not record.exists():
            profile_source.rename(work/('interrupted-reference-'+uuid.uuid4().hex+'.dcp'))
        if not profile_source.exists():
            temporary=work/('reference-'+uuid.uuid4().hex+'.dcp')
            print('Creating the matching Sony Camera ST / CUBE DCP reference.',flush=True)
            generated_report=dcpexport.cube_profile(copied,name,temporary,bridge=bridge,base=base)
            temporary.rename(profile_source);r5fit.save(record,generated_report)
        else:generated_report=json.loads(record.read_text(encoding='utf-8'))
        source_filename=companion.name
    else:
        profile_source=paired if cube else copied
        source_filename=a.raw_dcp.name if cube else a.source.name
    profile_bytes=profile_source.read_bytes()
    if companion.exists()and companion.read_bytes()!=profile_bytes:
        p.error('Companion DCP already contains different data; choose another output path')
    raw_profile=rawidentity.descriptor(profile_source,name)
    raw_profile['source_filename']=source_filename
    print('C2 Hybrid: native %d starts → up to five target-grid rounds → three stacked rounds. Offline CPU fitting.'%a.passes,flush=True)
    params,table,report=r5fit.fit(target,work/'fit-hybrid',evaluations=a.evaluations,starts=a.passes,calibration=response)
    edit=copy.deepcopy(json.loads((r5fit.ROOT/'data/template.json').read_text(encoding='utf-8')))
    edit['fitted']=params;editrecipe.validate(edit)
    report.update(Lightroom_reference_used=False,reference_pipeline='explicit-CUBE-input'if cube else'builtin-DCP-look-tone-v1',reference_contract=contract,
        response_model_scope='C2 historical physical grid probes; chart-domain approximation',model_error_included_in_metrics=False)
    report['paired_DCP']=dict(created_from_CUBE=generated_report is not None,
        original_input_DCP_preserved=not cube or paired is not None,
        representation=generated_report,actual_Adobe_verified=False)
    if cube:report['reference_contract']=dict(contract,automatic_Adobe_profile_generated=generated_report is not None)
    a.output.parent.mkdir(parents=True,exist_ok=True)
    dcpexport.publish(profile_source,companion)
    lookfile.write(a.output,name,table,method='R5-C2-Hybrid-native12-grid5-stack3-20261110',
        attribution='Owner-provided reference; Hearts-Ace numerical optimizer adapted to C2',metrics=report,
        edit_native=edit,raw_profile=raw_profile,source_reference=source_reference,menu_icon=icon)
    print('Created '+str(a.output.resolve()),flush=True)
    print('Companion DCP '+str(companion.resolve()),flush=True)
    print('Offline model prediction; actual camera color accuracy has not been established.',flush=True)
    return 0
