"""Execute the original NOR loader's BK4 scalar reader on pinned factory data.

The original initializer, property lookup/size/pointer helpers and memcpy run
continuously on actual immutable input bytes. Host checks validate layout and
checksum first. This is not native boot initialization, a live backup reader,
an AP/CP physical-alias proof or permission to write any settings.
"""
import argparse
import hashlib
import json
from pathlib import Path

from unicorn import Uc, UC_ARCH_ARM64, UC_MODE_ARM
from support.backup import factory_segments
from support.boundaries import BoundaryRunner
from support.reference import NOR_LOADER_SHA

MEM, OUT, STACK, STOP = 0x30000000, 0x35000000, 0x40000000, 0x60000000
KEYS = (0xfa0173, 0xf909d5, 0xf909d6, 0x51005c, 0xfa0170, 0xfa016d, 0xfa016e, 0x510050)


def audit(loader, backup):
    if hashlib.sha256(loader).hexdigest() != NOR_LOADER_SHA:
        raise ValueError('Unsupported original NOR loader')
    name, segments = factory_segments(backup, KEYS)
    cpu = Uc(UC_ARCH_ARM64, UC_MODE_ARM)
    for at, size in ((0,0x20000),(MEM,0x400000),(OUT,4096),(STACK,0x10000),(STOP,4096)):
        cpu.mem_map(at,size)
    cpu.mem_write(0,loader)
    cpu.mem_write(MEM,backup)
    class Services:
        calls={0xb50c:'logging',0x15a8:'output',0xfc84:'NOR_read'}
    run=BoundaryRunner(cpu,(Services(),),stop=STOP,stack=STACK,count=10000)
    cases=[];decoded=[]
    for segment in segments:
        address=MEM+segment['offset']
        before=bytes(cpu.mem_read(MEM,len(backup)))
        got=run.call(0x4564,(address,))
        assert got['at']==STOP and got['args'][0]==0
        assert int.from_bytes(cpu.mem_read(0x17080,8),'little')==address
        assert int.from_bytes(cpu.mem_read(0x17088,8),'little')==address+0x100
        assert int.from_bytes(cpu.mem_read(0x17078,8),'little')==address+segment['property_table']
        cases.append(dict(case='original-BK4-initializer',segment=hex(segment['offset']),
                          header_and_table_pointers_match=True,checksum_validation='independent host check'))
        values={}
        for key,record in segment['records'].items():
            cpu.mem_write(OUT,b'\xa5'*32)
            # Native 36dc executes lookup4444, size43e8, pointer4374 and
            # memcpy2384/3014 itself. No external lookup/copy return is given.
            got=run.call(0x36dc,(key,OUT+8))
            width=len(record['data'])
            assert got['at']==STOP and got['args'][0]==width
            assert bytes(cpu.mem_read(OUT,32))==b'\xa5'*8+record['data']+b'\xa5'*(24-width)
            values[hex(key)]=dict(bytes=width,data=record['data'].hex(),
                                 value=int.from_bytes(record['data'],'little'))
            cases.append(dict(case='original-scalar-reader',segment=hex(segment['offset']),
                              ID=hex(key),returned_bytes=width,payload_and_guards_match=True))
        assert bytes(cpu.mem_read(MEM,len(backup)))==before==backup
        decoded.append(dict(segment=hex(segment['offset']),values=values))
    return dict(factory_source=name,cases=cases,decoded=decoded,
        original_reader_ran_continuously=True,original_backup_bytes_unchanged=True,
        full_boot_wrapper_or_configuration_service_executed=False,
        limits=['Host supplies an explicit backup pointer through the original BK4 initializer',
                'This does not qualify the real boot caller or its active backup bank',
                'Factory configuration and historical body backups are not a current device read',
                'GPIO values, address aliases, CP startup and pre-capture are not established'])


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--loader',type=Path,required=True)
    parser.add_argument('--backup',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args();loader=args.loader.read_bytes();backup=args.backup.read_bytes()
    report=dict(schema='OFFLINE_ORIGINAL_LOADER_FACTORY_BACKUP/1',camera_io=False,
        loader_sha256=hashlib.sha256(loader).hexdigest(),backup_sha256=hashlib.sha256(backup).hexdigest(),
        **audit(loader,backup))
    paths=[Path(__file__),*(Path(__file__).with_name('support')/p for p in ('backup.py','reference.py','boundaries.py'))]
    report['sources']={str(p.relative_to(Path(__file__).parent)):hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}
    with args.output.open('x',encoding='utf-8') as stream:
        json.dump(report,stream,indent=2);stream.write('\n')
    print(f"{len(report['cases'])} original factory-backup initializer/reader contracts; no live configuration or CP boot claim.")


if __name__=='__main__':
    main()
