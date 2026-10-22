"""Immutable host-side DCP versions for automatic Lightroom matching.

The descriptor travels inside .a7look on the COMPUTER. It is not a RAW tag,
not a firmware payload, and does not change the camera's six ISP markers.
"""
import base64
from datetime import datetime
import json
import os
from pathlib import Path
import struct
import uuid
from . import rawprofiles

SCHEMA='a7c2-source-DCP-version/1'


def descriptor(dcp,title=None):
    path=Path(dcp);info=rawprofiles.dcp_info(path);identifier=uuid.uuid4().hex
    title=title or info['profile']
    return dict(schema=SCHEMA,id=identifier,source_profile=info['profile'],source_filename=path.name,
        adobe_profile=f'{title[:40]} [A7L-{identifier[:12]}]',
        dcp_base64=base64.b64encode(path.read_bytes()).decode('ascii'),copyright=info['copyright'])


def source_bytes(value):
    if value.get('schema')!=SCHEMA:raise ValueError('Unknown source-DCP descriptor')
    identifier=value.get('id','')
    if len(identifier)!=32 or any(c not in '0123456789abcdef' for c in identifier):raise ValueError('Invalid source-DCP version identifier')
    raw=base64.b64decode(value['dcp_base64'],validate=True)
    info=rawprofiles.dcp_info(raw)
    if info['profile']!=value.get('source_profile'):raise ValueError('Source DCP name differs from its version record')
    return raw


def renamed_dcp(source,name):
    """Replace ProfileName only, retaining every other TIFF field payload."""
    raw=bytes(source);order='<' if raw[:2]==b'II' else '>' if raw[:2]==b'MM' else None
    if order is None or len(raw)<8:raise ValueError('Not a classic TIFF DCP')
    magic,start=struct.unpack_from(order+'HI',raw,2)
    if magic not in (42,0x4352) or start+2>len(raw):raise ValueError('Invalid DCP directory')
    count=struct.unpack_from(order+'H',raw,start)[0]
    end=start+2+12*count
    if end+4>len(raw) or struct.unpack_from(order+'I',raw,end)[0]!=0:raise ValueError('A single DCP profile directory is required')
    sizes={1:1,2:1,3:2,4:4,5:8,7:1,9:4,10:8,11:4,12:8};records=[];found=False
    for i in range(count):
        at=start+2+12*i;tag,kind,n,offset=struct.unpack_from(order+'HHII',raw,at)
        if kind not in sizes:raise ValueError('Unsupported DCP field type')
        length=n*sizes[kind];pointer=at+8 if length<=4 else offset
        if pointer+length>len(raw):raise ValueError('DCP field outside file')
        data=raw[pointer:pointer+length]
        if tag==50936:kind=2;data=name.encode('utf-8')+b'\0';n=len(data);found=True
        records.append((tag,kind,n,data))
    if not found:raise ValueError('DCP has no ProfileName')
    header=bytearray(raw[:2]+struct.pack(order+'HIH',magic,8,count))
    data_start=8+2+12*count+4;payload=bytearray()
    for tag,kind,n,data in records:
        header.extend(struct.pack(order+'HHI',tag,kind,n))
        if len(data)<=4:header.extend(data.ljust(4,b'\0'))
        else:
            if len(payload)%2:payload.append(0)
            header.extend(struct.pack(order+'I',data_start+len(payload)));payload.extend(data)
    return bytes(header+bytes(4)+payload)


def materialize(value,root):
    source=source_bytes(value);folder=Path(root)/'looks'/value['id'];folder.mkdir(parents=True,exist_ok=True)
    original=folder/'source.dcp';alias=folder/'adobe.dcp'
    if original.exists() and original.read_bytes()!=source:raise ValueError('A stored DCP version cannot be replaced')
    if not original.exists():original.write_bytes(source)
    if not alias.exists():alias.write_bytes(renamed_dcp(source,value['adobe_profile']))
    info=rawprofiles.dcp_info(alias)
    if info['profile']!=value['adobe_profile']:raise ValueError('Stored Adobe profile name differs')
    rawprofiles.write_json(folder/'version.json',{key:item for key,item in value.items() if key!='dcp_base64'})
    return alias


def default_settings():
    configured=os.environ.get('A7LOOK_AUTO_SETTINGS')
    return Path(configured) if configured else Path.home()/'.a7look/auto-profile/settings.json'


def previous(slot,camera_signature,settings_path=None):
    """Recover attribution only when the observed selected-slot bytes agree."""
    path=Path(settings_path) if settings_path else default_settings()
    if not path.exists():return None
    settings=json.loads(path.read_text(encoding='utf-8'))
    row=rawprofiles.Registry(settings['registry']).match(slot,datetime.now())
    if not row or not row.get('look_id'):return None
    folder=Path(settings['library'])/'looks'/row['look_id']
    signatures=folder/'camera-signatures.json'
    if not signatures.exists() or camera_signature not in json.loads(signatures.read_text(encoding='utf-8')):return None
    value=json.loads((folder/'version.json').read_text(encoding='utf-8'))
    value['dcp_base64']=base64.b64encode((folder/'source.dcp').read_bytes()).decode('ascii')
    source_bytes(value)
    return value


def document_signature(document):
    if 'table_base64' not in document:return None
    raw=base64.b64decode(document['table_base64'],validate=True)
    native_raw=None
    if document.get('native_photo') is not None:
        from .photoformat import expand_matrix
        basis=document['native_photo']['runtime_basis']
        values=list(basis['tone_q10'])
        for plane in basis['matrix_planes']:values.extend(expand_matrix(plane,(0,0,0)))
        for plane in basis['chroma_planes']:values.extend(plane)
        native_raw=struct.pack('<54h',*values).hex()
    return dict(table_hex=raw.hex(),native_hex=native_raw)


def activated(documents,slots,event_id,since,settings_path=None):
    """Publish only a confirmed writer outcome. No camera or RAW I/O occurs."""
    path=Path(settings_path) if settings_path else default_settings()
    if not path.exists():return dict(status='not_configured')
    settings=json.loads(path.read_text(encoding='utf-8'));root=Path(settings['library'])
    root.mkdir(parents=True,exist_ok=True);receipt=root/'activations'/(str(event_id)+'.json')
    if receipt.exists():return json.loads(receipt.read_text(encoding='utf-8'))
    registry=rawprofiles.Registry(settings['registry']);published=[]
    if len(documents)!=len(slots):raise ValueError('Each changed slot needs its own source-DCP record')
    for slot,document in zip(slots,documents):
        value=document.get('raw_profile') if document else None
        if value:
            alias=materialize(value,root)
            observed=document.get('camera_signature') or document_signature(document)
            if observed is not None:
                record=alias.parent/'camera-signatures.json'
                signatures=json.loads(record.read_text(encoding='utf-8')) if record.exists() else []
                if observed not in signatures:
                    signatures.append(observed);rawprofiles.write_json(record,signatures)
            # Immutable version names also protect old captures when a user
            # later replaces a same-named canonical Adobe profile externally.
            selected=alias
            selected_name=rawprofiles.dcp_info(selected)['profile']
            entry=registry.bind(slot,selected,since,look=document.get('name'))
            data=registry.read()
            for row in data['entries']:
                if row['id']==entry['id']:row['look_id']=value['id']
            rawprofiles.write_json(registry.path,data)
            plan=dict(action='profile',profile=selected_name,dcp=str(selected))
            installed=rawprofiles.install_profiles([plan],settings.get('adobe_profiles'))
            published.append(dict(slot=slot,look_id=value['id'],profile=selected_name,installed=installed))
        else:
            # A diagnostic, native restored slot, or old file without its source
            # must not inherit a later DCP just because its slot marker matches.
            existing=registry.read()['entries']
            stamp=rawprofiles.camera_time(since)
            if not any(row['slot']==slot and rawprofiles.camera_time(row['since'])==stamp for row in existing):
                registry.suspend(slot,since)
            published.append(dict(slot=slot,status='no_source_DCP'))
    result=dict(status='published',event_id=str(event_id),effective_camera_local_time=since,slots=published,
        clock_basis='Computer local clock; camera clock must agree',RAW_embedded_version_id=False)
    rawprofiles.write_json(receipt,result)
    return result


def after_verified(state,save,event_id,documents,slots):
    """A host-profile error never turns a verified firmware write into a retry."""
    if state.get('phase') not in ('VERIFIED','COMPLETE','RESTORED'):
        return dict(status='awaiting_verified_activation')
    since=state.get('raw_profile_effective_since') or datetime.now().isoformat(timespec='microseconds')
    try:result=activated(documents,slots,event_id,since)
    except (OSError,ValueError,KeyError) as error:result=dict(status='profile_sync_failed',error=str(error))
    state['raw_profile_sync']=result
    save(state['phase'],raw_profile_sync=result)
    return result
