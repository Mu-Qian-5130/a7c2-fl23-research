"""Generate a complete original-body recovery candidate on the computer."""
from pathlib import Path
import shutil,struct,zlib
from .paths import write_json
from .firmwarelocal import decode,tools,version_bytes,finish_signing


def build(args,job):
    out=Path(args['workspace']).resolve();out.mkdir(parents=True,exist_ok=False)
    report=dict(schema='a7c2-original-body-recovery/1',phase='PREPARING',camera_io=False,signed=False,
        card_flash_ready=False,physical_tested=False,updater_trust_restored=False,
        source=str(Path(args['sony_firmware']).resolve()),update_header_version='3.02')
    status=out/'build.private.json';write_json(status,report)
    try:
        original=out/'original.FDAT.private.bin';decode(args['sony_firmware'],original)
        candidate=out/'candidate.FDAT.UNSIGNED.bin';shutil.copyfile(original,candidate)
        fdat=tools()[0]
        with candidate.open('r+b') as stream:
            header=bytearray(stream.read(fdat.FdatHeader.size));major,minor=version_bytes('3.02')
            header[0x20],header[0x21]=minor,major
            struct.pack_into('<I',header,8,zlib.crc32(header[12:])&0xffffffff)
            stream.seek(0);stream.write(header)
        with original.open('rb') as a,candidate.open('rb') as b:
            a.seek(fdat.FdatHeader.size);b.seek(fdat.FdatHeader.size)
            while data:=a.read(65536):
                if b.read(len(data))!=data:raise ValueError('Original recovery body differs')
            if b.read(1):raise ValueError('Original recovery body has extra data')
        report.update(phase='OFFLINE_CANDIDATE',candidate=str(candidate),workspace=str(out),
            original_body_byte_exact=True,voice_audio_restored_in_candidate=True,
            note='Original body recovery candidate. Updater trust and physical restoration remain unverified.')
        finish_signing(dict(args,automatic_identity=True),candidate,out,report)
        write_json(status,report);write_json(Path(job)/'backend-workspace.private.json',dict(workspace=str(out)))
        return report
    except BaseException as exc:
        report.update(phase='FAILED',error=type(exc).__name__+': '+str(exc));write_json(status,report);raise
