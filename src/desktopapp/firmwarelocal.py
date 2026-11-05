"""Build a C2 firmware candidate locally, optionally signed by its owner.

No USB, SSH, block device or device updater operation occurs here.
The FDAT model/header, auxiliary environment and unchanged TAR members retain
their original identities. Signing and stock-device trust are separate stages.
"""
import copy
import io
import json
from pathlib import Path
import shutil
import stat
import struct
import sys
import tarfile
import zlib

from .paths import ROOT, write_json

MODEL = 0x20030014
IMAGE_NAMES = {'rootfs':'0700_part_image/dev/nflasha7',
               'cp':'0700_part_image/dev/nflasha8', 'usr':'0700_part_image/dev/nflasha15'}


def stream_bytes(stream):
    return b''.join(iter(lambda:stream.read(65536),b''))


def tools():
    sys.path.insert(0,str(ROOT/'src/desktopapp/vendor'))
    from fwtool.sony import fdat,dat
    from fwtool.archive import ext2,fat
    return fdat,dat,ext2,fat


def version_bytes(value):
    import re
    if not re.fullmatch(r'[0-9]\.[0-9]{2}',value):
        raise ValueError('固件头版本使用 Sony 格式，例如 3.01，而不是 3.0.1')
    major,minor=value.split('.')
    return int(major,16),int(minor,16)


def decode(source,destination):
    fdat,dat,_,_=tools()
    with Path(source).open('rb') as original,Path(destination).open('xb') as target:
        if original.read(8)==fdat.fdatHeaderMagic:
            original.seek(0);plain=original;cipher='plaintext-FDAT'
        else:
            original.seek(0);outer=dat.readDat(original)
            cipher,plain=fdat.decryptFdat(outer.firmwareData)
        plain.seek(0)
        # fwtool's chunk reader concatenates bytes; small reads avoid quadratic
        # copies without changing its original decrypt/checksum behavior.
        while block:=plain.read(65536):target.write(block)
    with Path(destination).open('rb') as stream:
        contents=fdat.readFdat(stream)
        if (contents.model,contents.version)!=(MODEL,'2.01'):
            raise ValueError('请选择官方 ILCE-7CM2 2.01 固件')
    return cipher


def patch_defaults(raw,wanted,source_records,*,scalar_fields=()):
    """Edit only declared fields of official defaults, not body backups."""
    from pmca.backup import BackupFile
    matches=[];start=0
    while (at:=raw.find(b'BK4\0',start))>=0:
        start=at+4
        if at<12:continue
        try:
            stream=io.BytesIO(raw[at-12:]);backup=BackupFile(stream)
        except Exception:continue
        matches.append((at-12,stream,backup))
    result=bytearray(raw)
    for at,stream,backup in matches:
        properties=dict(backup.listProperties())
        for chip in (0,1):
            for key,value in wanted[chip].items():
                if key not in properties:continue
                original=source_records[chip][key].data;current=properties[key].data
                if len(current)!=len(original) or len(value)!=len(original):raise ValueError('Regional default property size differs')
                if key in scalar_fields:
                    if current not in (b'\0',b'\1') or value not in (b'\0',b'\1'):raise ValueError('Feature switch is not a native boolean')
                    backup.setProperty(key,value);continue
                patched=bytearray(current)
                for index,(before,after) in enumerate(zip(original,value)):
                    if before!=after:
                        if current[index] not in (before,after):raise ValueError('Regional default edited-byte conflict')
                        patched[index]=after
                backup.setProperty(key,bytes(patched))
        backup.updateChecksum();changed=stream.getvalue()[:backup.size]
        result[at:at+len(changed)]=changed
    return bytes(result)


def rewrite_sum(raw,replacements):
    lines=[];changed=[]
    for line in raw.decode('ascii').splitlines(keepends=True):
        tail='\r\n' if line.endswith('\r\n') else '\n' if line.endswith('\n') else ''
        parts=line.rstrip('\r\n').split(',')
        if len(parts)>10 and parts[0]=='0':
            relative=parts[10]
            matches=[(name,path) for name,path in replacements.items() if name.endswith('/'+relative)]
            if len(matches)>1:raise ValueError('Ambiguous checksum target: '+relative)
            if matches:
                name,path=matches[0];crc=0
                with Path(path).open('rb') as source:
                    while block:=source.read(4<<20):crc=zlib.crc32(block,crc)
                parts[1]=f'{crc&0xffffffff:08x}';parts[2]=f'{Path(path).stat().st_size:08x}'
                line=','.join(parts)+tail;changed.append(name)
        lines.append(line)
    return ''.join(lines).encode('ascii'),changed


def build(args,job):
    """Produce components, edited images, TAR and plaintext FDAT for VM review."""
    from .worker import setup_runtime
    setup_runtime()
    sys.path.insert(0,str(ROOT/'src/shutter_sound'))
    from looktool.devicesession import modules
    from .imageedit import edit_images
    from . import firmwarefeatures
    features=firmwarefeatures.options(args)
    if args.get('looks'):
        from looktool import bundle
        bundle.documents(dict(looks=args['looks']),allow_menu_icons=True)
    if args.get('automatic_identity'):
        container=args.get('signing_container') or args['sony_firmware']
        with Path(container).open('rb') as source:
            if source.read(8)==tools()[0].fdatHeaderMagic:
                raise ValueError('请选择原始官方 BODYDATA.DAT；应用会自动签名，不需要手动选择密钥')
    signing_private=args.get('signing_private_key')
    signing_public=args.get('signing_public_key')
    if bool(signing_private)!=bool(signing_public):
        raise ValueError('签名时请同时选择配对的 RSA 私钥和公钥')
    out=Path(args['workspace']).resolve()
    out.mkdir(parents=True,exist_ok=False)
    report=dict(schema='a7c2-local-firmware/1',phase='PREPARING',camera_io=False,
                signed=False,card_flash_ready=False,physical_tested=False,
                model='ILCE-7CM2',base_version='2.01',update_header_version=args.get('update_version','3.01'),
                version_rollback_implemented=True,source=str(Path(args['sony_firmware']).resolve()))
    major,minor=version_bytes(report['update_header_version'])
    status=out/'build.private.json';write_json(status,report)
    try:
        decoded=out/'original.FDAT.private.bin'
        report['decoder']=decode(args['sony_firmware'],decoded)
        fdat,_,ext2,fat=tools()
        originals=out/'original-images';originals.mkdir()
        overlays=out/'overlays';overlays.mkdir()
        replacements={};current={};default_members={};voice_sources={}
        with decoded.open('rb') as stream:
            header=fdat.FdatHeader.unpack(stream);contents=fdat.readFdat(stream)
            with tarfile.open(fileobj=contents.firmware,mode='r:') as archive:
                members=archive.getmembers()
                for role,name in IMAGE_NAMES.items():
                    member=archive.getmember(name);path=originals/(role+'.img')
                    with path.open('xb') as target:shutil.copyfileobj(archive.extractfile(member),target)
                for member in members:
                    if member.isfile() and member.name.startswith('0110_backup/'):
                        raw=archive.extractfile(member).read();default_members[member.name]=raw
                        if member.name.endswith('/CX89700_ALLLANG.bin'):
                            current['settings-ram.bin']=current['settings-saved.bin']=raw
        for role,reader in (('usr',ext2.readExt2),('cp',fat.readFat)):
            with (originals/(role+'.img')).open('rb') as image:
                for entry in reader(image):
                    if not stat.S_ISREG(entry.mode):continue
                    name=entry.path.lstrip('/')
                    if name=='lib/appFw.so':current['appFw.so']=stream_bytes(entry.contents)
                    elif name=='cpapp-b.bin':current['cpapp-b.bin']=stream_bytes(entry.contents)
                    elif name.startswith('share/app/'):
                        from looktool.nameworker import filenames
                        base=name.rsplit('/',1)[-1]
                        if base in filenames():current['resources/'+base]=entry.contents.read()
                        if (features['vertical'] or args.get('looks')) and base in {f'image_{i:02d}_32_IPSX.uxc' for i in range(3)}:
                            current['images/'+base]=stream_bytes(entry.contents)
                    elif name.startswith('share/screenreader/'):
                        from .screenreader import NAMES
                        base=name.rsplit('/',1)[-1]
                        if base in NAMES:voice_sources[base]=entry.size
        from .screenreader import NAMES,LANGUAGES
        if set(voice_sources)!=set(NAMES):raise ValueError('官方无障碍语音资源不完整，未删除任何来源文件')
        source_records=modules()[1].backup_records(current['settings-ram.bin'])
        target,wanted,selected,resource_files,composition=firmwarefeatures.compose(current,source_records,args)
        write_json(out/'composition.private.json',composition)
        files={'usr':{},'cp':{},'rootfs':{}}
        for language in LANGUAGES:files['usr']['/share/screenreader/'+language+'.bin']=dict(delete=True)
        for path,raw in resource_files.items():
            dest=overlays/Path(path).name;dest.write_bytes(raw)
            files['usr'][path]=dict(source=str(dest),mode=0o644)
        for name,role,path in (('appFw.so','usr','/lib/appFw.so'),('cpapp-b.bin','cp','/cpapp-b.bin')):
            dest=overlays/name;dest.write_bytes(target[name]);files[role][path]=dict(source=str(dest),mode=0o755 if role=='usr' else 0o644)
        for name,value in target.items():
            if name.startswith('resources/') and value!=current[name]:
                dest=overlays/name.split('/',1)[1];dest.write_bytes(value)
                files['usr']['/share/app/'+dest.name]=dict(source=str(dest),mode=0o644)
        # Subsequent SSH edits are compiled from this exact local baseline.
        # Keep the reference and resources local, never in a diagnostic ZIP.
        baseline=out/'baseline';baseline.mkdir()
        for name,value in target.items():
            if name.startswith('resources/') or name in ('appFw.so','cpapp-b.bin','settings-ram.bin','settings-saved.bin'):
                path=baseline/name;path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(value)
        write_json(baseline/'baseline.private.json',dict(schema='a7c2-ssh-update-baseline/1',model='ILCE-7CM2',version='2.01',
            files=sorted(target),wanted=[{str(k):v.hex() for k,v in fields.items()} for fields in wanted]))
        for name,raw in default_members.items():
            from looktool import voicelock,verticalpersist
            changed=patch_defaults(raw,wanted,source_records,scalar_fields=(voicelock.SETTING,voicelock.TRIGGER,verticalpersist.SETTING))
            if changed!=raw:
                dest=overlays/(name.replace('/','_'));dest.write_bytes(changed);replacements[name]=dest
        if args.get('ssh'):
            from .sshboot import prepare_boot
            additions=prepare_boot(args,out/'ssh',originals/'rootfs.img',target)
            for role,rows in additions.items():files[role].update(rows)
            report['camera_command']='/usr/bin/a7c2-api'
            report['camera_command_bytes']=(out/'ssh/api/a7c2-api').stat().st_size
        edited=edit_images(originals,files,out/'edited-images')
        from .firmwarespace import report as capacity_report
        capacity=capacity_report(originals,edited,files)
        write_json(out/'capacity.private.json',capacity)
        for role,name in IMAGE_NAMES.items():
            if files[role]:replacements[name]=edited[role]
        sums=[]
        with decoded.open('rb') as stream:
            contents=fdat.readFdat(stream)
            with tarfile.open(fileobj=contents.firmware,mode='r:') as archive:
                for member in archive:
                    if member.isfile() and member.name.endswith('.sum'):
                        raw=archive.extractfile(member).read();changed,ledger=rewrite_sum(raw,replacements)
                        if ledger:
                            dest=overlays/(member.name.replace('/','_'));dest.write_bytes(changed)
                            replacements[member.name]=dest;sums+=ledger
        archive_path=out/'candidate-firmware.private.tar'
        with decoded.open('rb') as stream,tarfile.open(archive_path,'w',format=tarfile.USTAR_FORMAT) as output:
            contents=fdat.readFdat(stream)
            with tarfile.open(fileobj=contents.firmware,mode='r:') as archive:
                for member in archive:
                    item=copy.copy(member)
                    if member.name in replacements:
                        path=replacements[member.name];item.size=path.stat().st_size
                        with path.open('rb') as data:output.addfile(item,data)
                    else:output.addfile(item,archive.extractfile(member) if member.isfile() else None)
        candidate=out/'candidate.FDAT.UNSIGNED.bin'
        with decoded.open('rb') as source:prefix=bytearray(source.read(header.firmwareOffset))
        prefix[0x20],prefix[0x21]=minor,major
        struct.pack_into('<I',prefix,0x34,archive_path.stat().st_size)
        struct.pack_into('<I',prefix,8,zlib.crc32(prefix[12:fdat.FdatHeader.size])&0xffffffff)
        with candidate.open('xb') as result,archive_path.open('rb') as archive:
            result.write(prefix);shutil.copyfileobj(archive,result)
        with candidate.open('rb') as stream:
            check=fdat.readFdat(stream)
            if (check.model,check.version)!=(MODEL,report['update_header_version']):raise ValueError('Candidate FDAT header readback differs')
            with tarfile.open(fileobj=check.firmware,mode='r:') as archive:
                for name,path in replacements.items():
                    with archive.extractfile(name) as actual,Path(path).open('rb') as expected:
                        while block:=expected.read(4<<20):
                            if actual.read(len(block))!=block:raise ValueError('Candidate member readback differs: '+name)
                        if actual.read(1):raise ValueError('Candidate member has trailing bytes: '+name)
        report.update(phase='OFFLINE_CANDIDATE',candidate=str(candidate),workspace=str(out),
                      changed_members=sorted(replacements),checksum_targets=sorted(set(sums)),
                      whitebalance=bool(args.get('whitebalance')),ssh=bool(args.get('ssh')),
                      filter_slots=[row['slot'] for row in selected],
                      menu_icon_slots=composition.get('menu_icon_slots',[]),
                      features=features,voice_audio_removed=len(LANGUAGES),
                      voice_bytes_removed=sum(voice_sources[name+'.bin'] for name in LANGUAGES),
                      portrait_resources=len(resource_files),
                      capacity=capacity,
                      note='Plaintext FDAT for offline/VM validation. No trusted signature, no stock-device card-flash acceptance.')
        finish_signing(args,candidate,out,report)
        write_json(status,report);write_json(Path(job)/'backend-workspace.private.json',dict(workspace=str(out)))
        return report
    except BaseException as exc:
        report.update(phase='FAILED',error=type(exc).__name__+': '+str(exc));write_json(status,report);raise


def finish_signing(args,candidate,out,report):
    """Use the same offline signer from the CLI and desktop build path."""
    if not args.get('signing_private_key') and not args.get('signing_public_key'):
        if not args.get('automatic_identity'):return
        from .identity import signing_paths
        private,public=signing_paths()
        args=dict(args,signing_private_key=str(private),signing_public_key=str(public))
    from .firmwaresign import sign_candidate
    container=args.get('signing_container') or args['sony_firmware']
    with Path(container).open('rb') as source:decoded_source=source.read(8)==tools()[0].fdatHeaderMagic
    if decoded_source:
        raise ValueError('自动签名需要官方 BODYDATA.DAT 容器，请选择原始 DAT，不要选择已解码 FDAT')
    signed=sign_candidate(candidate,container,
                          args['signing_private_key'],args['signing_public_key'],
                          Path(out)/'candidate.RESEARCH.DAT')
    shutil.copyfile(args['signing_public_key'],Path(out)/'firmware-public.pem')
    write_json(Path(out)/'signature.private.json',signed)
    report.update(phase=signed['phase'],signed=True,plaintext_candidate=str(candidate),
                  candidate=signed['candidate'],signature_validation=signed,
                  note='Owner-signed offline DAT candidate. First trust installation, boot and physical card update remain unverified.')
