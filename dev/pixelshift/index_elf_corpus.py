"""Index every AArch64 ELF in a private firmware corpus, not a keyword subset.

Writes complete executable-section listings, direct/computed branch indexes,
ELF symbols, relocations, dependencies, unwind ranges and allocated-data ASCII
candidates. This is section decoding, not proof that every byte executes or
that computed branches and task/peripheral interactions have been resolved.
"""
import argparse
import gc
import json
from pathlib import Path
import re


def field(value):
    return str(value).replace('\\', '\\\\').replace('\t', '\\t').replace('\n', '\\n').replace('\r', '\\r')


def index_one(path, prefix):
    from capstone import Cs, CS_ARCH_ARM64, CS_MODE_LITTLE_ENDIAN
    from elftools.elf.elffile import ELFFile
    from elftools.elf.sections import SymbolTableSection
    from elftools.elf.relocation import RelocationSection
    from elftools.dwarf.callframe import FDE
    from elftools.common.exceptions import ELFParseError

    report = dict(file=str(path), sections=[], dependencies=[], instructions=0,
                  undecoded_bytes=0, symbols=0, relocations=0, unwind_ranges=0)
    with path.open('rb') as source:
        elf = ELFFile(source)
        if elf['e_machine'] != 'EM_AARCH64' or not elf.little_endian:
            raise ValueError('Expected AArch64 little-endian ELF: ' + str(path))
        decoder = Cs(CS_ARCH_ARM64, CS_MODE_LITTLE_ENDIAN)
        decoder.skipdata = True
        with (prefix.with_suffix('.instructions.tsv')).open('x', encoding='utf-8') as listing, \
                (prefix.with_suffix('.branches.tsv')).open('x', encoding='utf-8') as branches, \
                (prefix.with_suffix('.strings.tsv')).open('x', encoding='utf-8') as strings:
            listing.write('section\taddress\tbytes\tmnemonic\toperands\n')
            branches.write('section\tfrom\tmnemonic\ttarget\tcomputed\n')
            strings.write('section\taddress\tbytes\tascii_candidate\n')
            for section in elf.iter_sections():
                flags = section['sh_flags']
                if section['sh_type'] == 'SHT_NOBITS' or not section['sh_size']:
                    continue
                if flags & 4:  # SHF_EXECINSTR; do not Thumb-sweep CP data.
                    data = section.data()
                    base = section['sh_addr']
                    row = dict(name=section.name, address=hex(base), bytes=len(data),
                               decoded_bytes=0, undecoded_bytes=0, instructions=0)
                    for address, size, mnemonic, operands in decoder.disasm_lite(data, base):
                        listing.write(f'{section.name}\t{address:x}\t{size}\t{mnemonic}\t{field(operands)}\n')
                        if mnemonic == '.byte':
                            row['undecoded_bytes'] += size
                            continue
                        row['decoded_bytes'] += size
                        row['instructions'] += 1
                        if mnemonic in ('b', 'bl', 'cbz', 'cbnz', 'tbz', 'tbnz') or mnemonic.startswith('b.'):
                            target = operands.rsplit(',', 1)[-1].strip().lstrip('#')
                            branches.write(f'{section.name}\t{address:x}\t{mnemonic}\t{target}\tfalse\n')
                        elif mnemonic in ('br', 'blr', 'braa', 'brab', 'blraa', 'blrab', 'ret', 'eret'):
                            branches.write(f'{section.name}\t{address:x}\t{mnemonic}\t{field(operands)}\ttrue\n')
                    consumed = row['decoded_bytes'] + row['undecoded_bytes']
                    if consumed < len(data):
                        row['undecoded_bytes'] += len(data) - consumed
                        listing.write(f'{section.name}\t{base+consumed:x}\t{len(data)-consumed}\tundecoded_tail\t\n')
                    report['instructions'] += row['instructions']
                    report['undecoded_bytes'] += row['undecoded_bytes']
                    report['sections'].append(row)
                    del data
                elif flags & 2:  # SHF_ALLOC; strings are candidates, not semantics.
                    for match in re.finditer(rb'[ -~]{4,}', section.data()):
                        strings.write(f'{section.name}\t{section["sh_addr"]+match.start():x}\t'
                                      f'{len(match[0])}\t{field(match[0].decode("ascii"))}\n')
        with prefix.with_suffix('.symbols.tsv').open('x', encoding='utf-8') as symbols, \
                prefix.with_suffix('.relocations.tsv').open('x', encoding='utf-8') as relocations:
            symbols.write('table\tname\tvalue\tsize\ttype\tsection\n')
            relocations.write('table\toffset\ttype\tsymbol\taddend\n')
            for section in elf.iter_sections():
                if isinstance(section, SymbolTableSection):
                    for symbol in section.iter_symbols():
                        symbols.write(f'{section.name}\t{field(symbol.name)}\t{symbol["st_value"]:x}\t'
                                      f'{symbol["st_size"]}\t{symbol["st_info"]["type"]}\t{symbol["st_shndx"]}\n')
                        report['symbols'] += 1
                elif isinstance(section, RelocationSection):
                    table = elf.get_section(section['sh_link'])
                    for relocation in section.iter_relocations():
                        name = table.get_symbol(relocation['r_info_sym']).name if relocation['r_info_sym'] else ''
                        relocations.write(f'{section.name}\t{relocation["r_offset"]:x}\t'
                                          f'{relocation["r_info_type"]}\t{field(name)}\t'
                                          f'{relocation.entry.get("r_addend", "")}\n')
                        report['relocations'] += 1
        dynamic = elf.get_section_by_name('.dynamic')
        if dynamic:
            report['dependencies'] = [tag.needed for tag in dynamic.iter_tags('DT_NEEDED')]
        with prefix.with_suffix('.unwind.tsv').open('x', encoding='utf-8') as unwind:
            unwind.write('start\tlength\n')
            if elf.get_section_by_name('.eh_frame'):
                # FDE ranges are unwind metadata, not guaranteed function boundaries.
                try:
                    for entry in elf.get_dwarf_info().EH_CFI_entries():
                        if isinstance(entry, FDE):
                            unwind.write(f'{entry["initial_location"]:x}\t{entry["address_range"]}\n')
                            report['unwind_ranges'] += 1
                except ELFParseError as error:
                    # A corpus library has an EH frame pyelftools cannot parse.
                    # Preserve its complete listing and explicitly report this gap.
                    report['unwind_error'] = str(error)
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--corpus', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--resume', action='store_true', help='Reuse completed per-file reports; rebuild unfinished files')
    args = parser.parse_args()
    inventory = json.loads((args.corpus / 'inventory.private.json').read_text(encoding='utf-8'))
    args.output.mkdir(parents=True, exist_ok=args.resume)
    reports = []
    rows = [row for row in inventory['entries'] if row['kind'] == 'elf']
    for index, row in enumerate(rows):
        prefix = args.output / Path(row['file']).name
        report_path = prefix.with_suffix('.report.json')
        if args.resume and report_path.exists():
            reports.append(json.loads(report_path.read_text(encoding='utf-8')))
            continue
        if args.resume:
            # Only remove this indexer's unfinished, explicitly named output files.
            for suffix in ('.instructions.tsv', '.branches.tsv', '.strings.tsv', '.symbols.tsv',
                           '.relocations.tsv', '.unwind.tsv'):
                prefix.with_suffix(suffix).unlink(missing_ok=True)
        report = index_one(args.corpus / row['file'], prefix)
        report.update(source=row['source'], output_prefix=prefix.name)
        report_path.write_text(json.dumps(report, indent=2), encoding='utf-8')
        reports.append(report)
        print(json.dumps(dict(index=index+1, total=len(rows), file=Path(row['file']).name,
                              instructions=report['instructions'], unwind_ranges=report['unwind_ranges'])), flush=True)
        gc.collect()
    summary = dict(schema='a7c2-elf-corpus-index/1', complete=True, camera_io=False, files=reports,
                   unwind_metadata_complete=all('unwind_error' not in row for row in reports),
                   computed_branches_resolved=False, hardware_behavior_verified=False)
    (args.output / 'summary.private.json').write_text(json.dumps(summary, indent=2), encoding='utf-8')


if __name__ == '__main__':
    main()
