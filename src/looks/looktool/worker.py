"""Offline compiler inputs and report checks; no USB or camera execution.

Only selected-table updates from the pinned full7-v4 source are accepted.
This does not authorize an unknown source or install a stock-to-six build.
Generated headers contain private firmware-derived bytes; keep them private.
"""
import struct

NAMES=('appFw.so','cpapp-b.bin')
REPORT=struct.Struct('<8sIIII7q4Q')


def validate_worker_report(raw,mode,contract):
    """Validate the existing installer.c 240-byte ABI against this exact job.

    Native evidence alone is insufficient: complete host readback, settings
    preservation, cleanup and physical acceptance remain separate checks.
    """
    if contract.get('byte_only'):
        from .checkpointworker import program_report
        return program_report(raw,mode,{'windows':contract['window_writes'],'sizes':[contract['sizes'][n] for n in NAMES]})
    if type(mode) is not int or mode not in (0,1,2) or len(raw)!=240:
        raise ValueError('Expected native mode 0/1/2 and exactly 240 report bytes')
    if contract.get('schema')!='a7c2-table-worker-contract/1':raise ValueError('Unknown worker contract')
    try:
        sizes=[contract['sizes'][n] for n in NAMES]
        before=[bytes.fromhex(contract['before'][n]) for n in NAMES]
        after=[bytes.fromhex(contract['after'][n]) for n in NAMES]
        writes=contract['window_writes']
    except (KeyError,TypeError,ValueError) as exc:raise ValueError('Invalid worker contract fields') from exc
    if any(type(n) is not int or n<=0 for n in sizes) or any(len(h)!=32 for h in before+after) or type(writes) is not int or writes<=0:
        raise ValueError('Invalid worker sizes/hashes/write count')
    values=REPORT.unpack_from(raw)
    if values[:4]!=(b'A7IRP001',1,mode,9) or any(values[i] for i in [5,6,7,8,9,10]):
        raise ValueError('Native operation did not finish cleanly; inspect without replay')
    if values[4]!=(0 if mode==0 else writes) or list(values[14:16])!=sizes or any(values[i]<=0 for i in [12,13]):
        raise ValueError('Native counts, sizes or inode evidence differs')
    actual_before=[raw[112:144],raw[144:176]];actual_after=[raw[176:208],raw[208:240]]
    if actual_before!=(after if mode==2 else before):raise ValueError('Native source hashes differ')
    if mode and actual_after!=(before if mode==2 else after):raise ValueError('Native target hashes differ')
    if mode==0 and actual_after!=[bytes(32),bytes(32)]:raise ValueError('Unexpected preflight target hashes')
    return {'mode':mode,'native_verified':True,'window_writes':values[4],
            'host_complete_readback_verified':False,'physical_test_verified':False}
