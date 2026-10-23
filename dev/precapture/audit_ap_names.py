"""Compare generated Timeshift names in supplied AP files; strictly offline.

Names identify metadata entries, not code, a working feature, runtime values,
remote properties or permission to write a parameter/patch.
"""
import argparse
import hashlib
import json
from pathlib import Path
import re

from support.ap_names import Names

RELATED=re.compile(r'pre_?cap|pre_?shoot|half_?press|time_?shift',re.I)


def audit(raw):
    table=Names(raw)
    selected=[row for row in table.entries if RELATED.search(row['name'])]
    return dict(source_sha256=hashlib.sha256(raw).hexdigest(),source_bytes=len(raw),
        array_file_offset=table.array_file_offset,array_address=table.array_address,
        entries=len(table.entries),sections=table.sections,related_names=selected,
        array_sha256=hashlib.sha256(raw[table.array_file_offset:
            table.array_file_offset+8*len(table.entries)]).hexdigest(),
        generated_metadata_only=True,loaded_state_proven=False)


def compare(target,donor):
    a={row['name'] for row in target['related_names']}
    b={row['name'] for row in donor['related_names']}
    return dict(shared=sorted(a&b),target_only=sorted(a-b),donor_only=sorted(b-a),
                compared_by_name_not_cross_model_ID=True)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--ap',type=Path,required=True)
    parser.add_argument('--donor-ap',type=Path)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args();target=audit(args.ap.read_bytes())
    report=dict(schema='OFFLINE_GENERATED_AP_TIMESHIFT_NAMES/1',camera_io=False,target=target,
        limits=['Generated PRM/VAL/FUNC strings are not a complete C++/ELF symbol table',
                'A FUNC ID or its string pointer is not a callable code address',
                'Array indices are not Backup/Adjust keys or remote property codes',
                'Metadata presence does not prove sensor, retained RAW, save or cancellation support',
                'Donor-only rules are clues, not patch targets or feature-enable evidence'])
    if args.donor_ap:
        donor=audit(args.donor_ap.read_bytes())
        report.update(donor=donor,comparison=compare(target,donor))
    with args.output.open('x',encoding='utf-8') as stream:
        json.dump(report,stream,indent=2);stream.write('\n')
    print(f"{target['entries']} generated names;{len(target['related_names'])} Timeshift-related entries; no camera I/O")


if __name__=='__main__':main()
