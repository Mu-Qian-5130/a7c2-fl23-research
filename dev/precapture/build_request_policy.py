"""Derive a private sparse command-word experiment policy from exact stock CP.

The policy records inferred software requests, not physical clocks/reset or
ready state. It is not firmware, an installer or a camera deployment artifact.
"""
import argparse
import hashlib
import json
from pathlib import Path
from support.request_words import derive,encode


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--cp',type=Path,required=True);parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args();report=derive(args.cp.read_bytes());payload=encode(report)
    args.output.mkdir(parents=True,exist_ok=False)
    artifact=args.output/'request-policy.private.bin';artifact.write_bytes(payload)
    (args.output/'source-audit.private.json').write_text(json.dumps(report,indent=2)+'\n',encoding='utf-8')
    manifest=dict(camera_io=False,artifact=artifact.name,bytes=len(payload),sha256=hashlib.sha256(payload).hexdigest(),
        CP_sha256=report['CP_sha256'],code_sha256=report['code_sha256'],original_executions=report['original_executions'],
        paired_selectors=len(report['paired_selectors']),sparse_words=len(report['policy']),physical_hardware_qualified=False)
    (args.output/'manifest.private.json').write_text(json.dumps(manifest,indent=2)+'\n',encoding='utf-8')
    print(f"Private sparse policy: {manifest['paired_selectors']} paired selectors, {manifest['sparse_words']} words; no physical hardware success supplied")


if __name__=='__main__':main()
