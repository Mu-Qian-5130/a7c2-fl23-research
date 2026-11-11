"""Focused frozen numerical and color-resource check; no camera or UI access."""
from pathlib import Path
import sys

def run(resources_only=False):
    root=Path(__file__).resolve().parents[2]
    sys.path[:0]=[str(root/'src'),str(root/'src/looks')]
    from desktopapp import VERSION,presets
    from looktool import r5fit,lookfile,editrecipe
    report=None;native_count=None;projection=None
    if not resources_only:
        report=r5fit.preflight()
        import numpy as np
        from edit_parameter_context import ParameterContext
        model=ParameterContext(r5fit.context())
        with np.load(r5fit.ROOT/'data/inputs.npz')as samples:native=model.base.color_only(samples['input'][:512])
        assert native.shape==(512,9,3)and np.isfinite(native).all();native_count=len(native)
        from concave_gamma import ConcaveGamma
        from gamma_global_correction import _c2_windows_global_quantizer
        shape=ConcaveGamma(model.axis,control_count=128,global_correction=True)
        _c2_windows_global_quantizer(shape)
        desired=shape.curve(shape.encode(model.gamma_y/16))*16
        desired[1:]+=np.sin(np.arange(1,128))*.75
        raw,projection=shape.quantize_global_raw(desired,return_audit=True)
        assert shape.audit_even(raw)['passed']
        model.build(matrix_payload=model.payload,cc1=model.cc1,gamma_y=raw)
    builtin=[];builtin_documents=[]
    for row in presets.catalog():
        doc=lookfile.read(row['path'])
        assert doc['name']==row['name']
        assert editrecipe.unpack(editrecipe.pack(doc['edit_native']))==doc['edit_native']
        builtin.append(doc['name'])
        builtin_documents.append(doc)
    from desktopapp.profilelibrary import location
    import json
    paired=location();paired_catalog=paired/'catalog.json'
    collection=json.loads(paired_catalog.read_text(encoding='utf-8'))if paired_catalog.is_file()else{}
    library=root/'desktop-assets/creative-look-library-v2'
    count=0;dcp_count=0
    if collection.get('schema')=='a7c2-profile-library/2':
        from looktool import rawidentity,rawprofiles
        for row in collection['profiles']:
            doc=lookfile.read(paired/row['a7look']);other=lookfile.read(paired/row['menu_a7look'])
            assert {k:v for k,v in doc.items()if k!='menu_icon'}=={k:v for k,v in other.items()if k!='menu_icon'}
            assert doc['method']=='R5-C2-Hybrid-native12-grid5-stack3-20261110'
            assert rawidentity.source_bytes(doc['raw_profile'])==(paired/row['dcp']).read_bytes()
            assert rawprofiles.dcp_info(paired/row['dcp'])['profile']==doc['name']==row['name']
            count+=1;dcp_count+=1
        assert count==dcp_count==collection['count']
        if collection.get('distribution')=='windows-default-six':
            assert [r['name']for r in collection['profiles']]==builtin and count==6
    elif library.exists():
        plain=list((library/'Looks').rglob('*.a7look'));icons=list((library/'MenuIcons').rglob('*.a7look'))
        assert len(plain)==len(icons)==41
        for file in plain:
            doc=lookfile.read(file);other=lookfile.read(library/'MenuIcons'/file.relative_to(library/'Looks'))
            assert {k:v for k,v in doc.items()if k!='menu_icon'}=={k:v for k,v in other.items()if k!='menu_icon'}
            assert doc['method']=='R5-C2-Hybrid-native12-grid5-stack3-20261110'
            count+=1
    rebuilt=0
    if count and not resources_only:
        with np.load(r5fit.ROOT/'data/inputs.npz')as archive:input_rows=archive['input'][:64]
        for document in builtin_documents:
            assert document['method']=='R5-C2-Hybrid-native12-grid5-stack3-20261110'
            p=document['edit_native']['fitted']
            native=model.build(matrix_payload=bytes.fromhex(p['matrix_780f_hex']),cc1=np.asarray(p['cc1_direct_raw']),gamma_y=np.asarray(p['gamma_7806_y']))
            assert np.isfinite(native.color_only(input_rows)).all()
            rebuilt+=1
    dcp_export=None
    if dcp_count and not resources_only:
        import os,uuid
        from looktool import dcpexport,rawprofiles
        folder=Path(os.environ['TEMP'])/('a7c2-paired-frozen-'+uuid.uuid4().hex)
        folder.mkdir(parents=True)
        source=folder/'identity.cube'
        source.write_text('LUT_3D_SIZE 2\n0 0 0\n1 0 0\n0 1 0\n1 1 0\n0 0 1\n1 0 1\n0 1 1\n1 1 1\n',encoding='utf-8')
        output=folder/'Packaged DCP Probe.dcp'
        dcp_export=dcpexport.cube_profile(source,'Packaged DCP Probe',output,dimensions=(12,16,16))
        assert rawprofiles.dcp_info(output)['profile']=='Packaged DCP Probe'
        dcp_export['file']=str(output)
    return dict(version=VERSION,numerical=report,native_renderer_samples=native_count,global_gamma_projection=projection,
        resources_only=resources_only,builtins=builtin,builtin_native_rebuilt=rebuilt,updated_library_styles=count,
        paired_DCP_profiles=dcp_count,packaged_DCP_export=dcp_export,optimizer_full_budget_executed_here=False,camera_io=False)
