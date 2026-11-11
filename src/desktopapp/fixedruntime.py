"""Prepare fixed CP look storage for the normal firmware composition chain."""
from pathlib import Path
import json,struct


def prepare_source(current,out,records,selected):
    """Migrate compiled records and preserve an exact inverse of CP edits.

    It retains the static API's restart workflow. Live reload is outside this
    address migration; there is no App adapter or runtime code upload.
    """
    from looktool import fixedbank,fixedbankcode,fixedregion,device_layout,photofull,photoformat
    out=Path(out);out.mkdir(parents=True,exist_ok=False)
    source=current['cpapp-b.bin'];mask=device_layout.structural_ap(current['appFw.so'])['mask']
    prefix=source[0xa000:0x20000]
    if photofull.present(source):
        image=fixedbank.from_cp(source,mask=mask)
        if struct.unpack_from('<2I',prefix)!=(photofull.MAGIC,1):
            raise ValueError('Compiled full-record source ownership differs')
    else:
        if any(prefix):raise ValueError('Another feature occupies the fixed code source')
        basis=photoformat.extract_bank(source,records[1][0x02a40001].data,records[1][0x02a4000d].data,
            gamma_table_va=0x1209480,regular_row=0,still_row=10,color_parameter=0)[0]
        image=fixedbank.from_documents(source,basis,{r['slot']:r['document']for r in selected},mask=mask)
    staged,code,consumers=fixedbankcode.prepare(source)
    # Source ownership comes from the known predecessor, never from an arbitrary
    # search for unused bytes. Keep the old image solely as local inverse proof.
    retired=bytearray(staged);retired[0xa000:0x20000]=bytes(0x16000)
    target,layout=fixedregion.prepare(bytes(retired),code,image)
    restored=bytearray(target)
    for edit in reversed(layout['windows']):
        raw=bytes.fromhex(edit['before_hex']);restored[edit['offset']:edit['offset']+len(raw)]=raw
    restored[0xa000:0x20000]=prefix
    for edit in reversed(consumers['windows']):
        raw=bytes.fromhex(edit['before_hex']);restored[edit['offset']:edit['offset']+len(raw)]=raw
    if bytes(restored)!=source:raise ValueError('Fixed generator migration inverse differs')
    parsed=fixedbank.parse(image)
    metadata=dict(schema='a7c2-fixed-look-source/1',mask=mask,slots=parsed['count'],image_bytes=len(image),
                  code_bytes=len(code),root_fields=['base','size'],generation_field=False,ready_field=False,
                  fixed_CP=layout,consumers=consumers,exact_inverse=True,
                  activation_policy='battery removal after completed writes',live_reload_added=False,
                  ordinary_generator_default_changed=True,camera_io=False)
    (out/'cpapp-b.fixed.bin').write_bytes(target);(out/'fixed-data.bin').write_bytes(image)
    (out/'fixed-look.code.bin').write_bytes(code);(out/'retired-prefix.bin').write_bytes(prefix)
    layout.update(feature_consumers_connected=True,inputs=dict(code=str(out/'fixed-look.code.bin'),data=str(out/'fixed-data.bin')))
    (out/'layout.json').write_text(json.dumps(layout,indent=2)+'\n',encoding='utf-8')
    (out/'consumers.json').write_text(json.dumps(consumers,indent=2)+'\n',encoding='utf-8')
    (out/'source.private.json').write_text(json.dumps(metadata,indent=2)+'\n',encoding='utf-8')
    fixedbankcode.inspect(target)
    return target,image,metadata
