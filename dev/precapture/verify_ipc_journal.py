"""Offline corruption controls on an explicit private successful context journal.

No camera/process operations. A success-looking file alone never grants cleanup.
"""
import argparse
import hashlib
import json
from pathlib import Path
import struct

from support.ipc_journal import decode


def check(raw,nonce):
    clean=decode(raw,nonce)
    assert clean['success_record'] and not clean['cleanup_allowed']
    cases=[]
    def reject(name,data):
        try:decode(bytes(data),nonce)
        except (ValueError,struct.error):cases.append(dict(case=name,rejected=True))
        else:raise AssertionError(name)
    reject('truncated-tail',raw[:-1])
    reject('duplicate-final',raw+raw[-352:])
    parent=struct.unpack_from('<Q',raw,2*352+64)[0]
    parent=parent+1 if parent<0x7fffffff else parent-1
    changes=[('wrong-nonce',16,'I',nonce^1),('sequence-gap',352+20,'I',5),
             ('parent-drift',2*352+64,'Q',parent),('unmatched-after',352+24,'I',2),
             ('wrong-after-action',2*352+80,'Q',222),('final-ownership',19*352+116,'I',1),
             ('send-attempt',19*352+104+176+28,'I',1),('fd-count-drift',19*352+48,'I',3),
             ('native-counter-drift',19*352+36,'I',5),('used-start-context',104,'I',1),
             ('missing-release',19*352+104+176+32,'I',0),
             ('negative-native-return',8*352+88,'q',-5),
             ('failed-start-claimed-success',96,'q',-5),('reserved-used',352+52,'I',1),
             ('context-nonce-drift',4*352+120,'I',nonce^1),
             ('final-context-version',19*352+108,'I',2),
             ('zero-allocation-pointer',19*352+344,'Q',0),
             ('probe-nonce-drift',19*352+300,'I',nonce^1),
             ('configuration-mode',19*352+296,'I',1),
             ('map-return-drift',19*352+192,'q',0),
             ('positive-native-failure',8*352+88,'q',1),
             ('shared-size-drift',19*352+248,'Q',0),
             ('query-shape-drift',19*352+256,'I',0)]
    for name,offset,fmt,value in changes:
        altered=bytearray(raw);struct.pack_into('<'+fmt,altered,offset,value);reject(name,altered)
    pending=[]
    for count in range(1,20):
        result=decode(raw[:count*352],nonce)
        assert not result['success_record'] and not result['cleanup_allowed']
        pending.append(count)
    return dict(rejected_corruptions=cases,incomplete_record_prefixes_retained=pending,
                success_record_alone_grants_cleanup=False)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--journal',type=Path,required=True)
    parser.add_argument('--nonce',type=lambda value:int(value,0),required=True)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    if not 0<args.nonce<1<<32:parser.error('A nonzero 32-bit job nonce is required')
    raw=args.journal.read_bytes();result=check(raw,args.nonce)
    source=Path(__file__).parent/'support/ipc_journal.py'
    result.update(camera_io=False,process_operations=False,
                  parser_sha256=hashlib.sha256(source.read_bytes()).hexdigest(),
                  journal_sha256=hashlib.sha256(raw).hexdigest())
    with args.output.open('x',encoding='utf-8') as stream:
        json.dump(result,stream,indent=2);stream.write('\n')
    print(f'{len(result["rejected_corruptions"])} corruptions rejected;19 incomplete prefixes retained; no device/process operations')


if __name__=='__main__':main()
