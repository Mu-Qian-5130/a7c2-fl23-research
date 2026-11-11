"""Independent fixed CP reservation and early-copy candidate.

This does not enable a feature, change menu slots or install firmware. Payloads
must already be linked for their declared destination (or be position independent).
The original file size and its standard segment addresses stay unchanged.
"""
import struct
from .fixedlayout import REGION_START,REGION_END,CODE_START,STATE_START,DATA_START

BASE = 0x108000
SOURCE_CODE_START, SOURCE_CODE_END = 0xA400, 0x20000
SOURCE_DATA_START = 0x1103000
NOR_FILE_BASE = 0xD0200000
BOOT_STUB_FILE = 0xA000
TABLE_VA, TABLE_CAPACITY = 0x010C6B84, 1148
TABLE_SOURCE_VA, TABLE_ROWS = 0x00EB7D90, 19
MAP_ROWS = ((CODE_START, STATE_START, 15),
            (STATE_START, DATA_START, 12),
            (DATA_START, REGION_END, 12))


def _assembler():
    from keystone import Ks, KS_ARCH_ARM, KS_MODE_ARM
    engine = Ks(KS_ARCH_ARM, KS_MODE_ARM)
    return lambda code, at: bytes(engine.asm(';'.join(code), addr=at)[0])


def _value(register, value):
    return [f'movw {register},#{value & 65535}',
            f'movt {register},#{value >> 16}']


def prepare(cp, code, data):
    """Build an isolated, exactly reversible CP candidate without publishing it."""
    cp, code, data = bytes(cp), bytes(code), bytes(data)
    if len(cp) != 0x1140B80:
        raise ValueError('This CP layout requires the existing original file extent')
    if not 0 < len(code) <= SOURCE_CODE_END-SOURCE_CODE_START:
        raise ValueError('Code exceeds the declared existing source-file window')
    if not 0 < len(data) <= len(cp)-SOURCE_DATA_START:
        raise ValueError('Data exceeds the declared existing source-file tail')
    if len(code) > STATE_START-CODE_START or len(data) > REGION_END-DATA_START:
        raise ValueError('Fixed payload overlaps another fixed subregion')
    text_fields=struct.unpack_from('<3I',cp,0x20124)
    data_fields=struct.unpack_from('<3I',cp,0x2013C)
    if text_fields not in ((0,0xB07490,0x128000),(0,0xB07FB0,0x128000)):
        raise ValueError('Source text extent is not the original or retained look window')
    if data_fields not in ((0xF9F000,0x141B80,0x10C7000),(0xF9F000,0x142FA0,0x10C7000)):
        raise ValueError('Source data extent differs from the retained look layout')
    expected = ((0x20130, (0xB08000, 0x496B84, 0xC30000)),
                (0x20148, (0x10E2000, 0x97BF5C, 0x120A000)),
                (0x20154, (0,0x4000,0x1B88000)),
                (0x20160, (0,0x8000,0x1B8C000)))
    for offset, fields in expected:
        if struct.unpack_from('<3I', cp, offset) != fields:
            raise ValueError('Source program segment differs at '+hex(offset))
    asm = _assembler()
    original_getter = asm(_value('r2', TABLE_SOURCE_VA)+[
        'str r2,[r0]', 'mov r0,#19', 'str r0,[r1]', 'bx lr'], 0x6314A8)
    original_optional = asm(['mov r2,#0','str r2,[r0]','str r2,[r1]','bx lr'],0x6314C0)
    predecessors = ((0x1083A0, asm(['bl 0x108974'],0x1083A0)),
                    (0x108520, asm(['bl 0x108768'],0x108520)),
                    (0x6314A8, original_getter), (0x6314C0, original_optional))
    for address, wanted in predecessors:
        if cp[address-BASE:address-BASE+len(wanted)] != wanted:
            raise ValueError('Original startup instruction differs at '+hex(address))

    records = [list(struct.unpack_from('<5I',cp,TABLE_SOURCE_VA-BASE+20*i))
               for i in range(TABLE_ROWS)]
    if records[4][:3] != [0x128000,0x29D8000,2] or records[4][4] != 0x128000:
        raise ValueError('Original SOLID ownership differs')
    if records[5][:3] != [REGION_END,0x900000,0]:
        raise ValueError('Original STACK boundary differs')
    for index,record in enumerate(records):
        for address in (record[0],record[4]):
            if index!=4 and address!=0xFFFFFFFF and record[1] and (
                    address<REGION_END and address+record[1]>REGION_START):
                raise ValueError('Another original region overlaps the fixed reservation')
    for cpu in range(4):
        for mode in range(6):
            start,size,top=struct.unpack_from('<3I',cp,0x20004+cpu*0x48+mode*12)
            if start+size!=top or (start<REGION_END and top>REGION_START):
                raise ValueError('A CPU mode stack conflicts with the fixed reservation')
    name = b'A7_FIXED\0'
    name_va = TABLE_VA+20*(TABLE_ROWS+1)
    # The original SOLID source keeps owning the complete backing extent.
    # Type3 registers only a named target view (as SOLID_HEAP does); it does
    # not add a second physical source or advertise these bytes as free RAM.
    records.insert(5,[0xFFFFFFFF,REGION_END-REGION_START,3,name_va,REGION_START])
    table = b''.join(struct.pack('<5I',*r) for r in records)+name
    table += bytes((-len(table)) & 3)
    maps_va = TABLE_VA+len(table)
    # Original optional-map kind2: flags, start, exclusive end, backing address.
    table += b''.join(struct.pack('<5I',2,flags,start,end,start)
                      for start,end,flags in MAP_ROWS)
    if len(table)>TABLE_CAPACITY:
        raise ValueError('Resident metadata exceeds the declared rodata window')

    # This entry resides in the already loaded BOOT prefix, including NOR/XIP
    # configurations where the later text is not yet mapped at its final VA.
    copy_at = BASE+BOOT_STUB_FILE
    save = ['mrs r4,apsr','push {r0,r1,r2,r3,r4,r12}']
    restore = ['pop {r0,r1,r2,r3,r4,r12}','msr APSR_nzcvq,r4','pop {r4,pc}']
    copier = ['push {r4,lr}','bl 0x108974',*save,
              *_value('r0',REGION_START),*_value('r1',REGION_END-REGION_START),
              'bl 0x108c54',
              *_value('r0',CODE_START),*_value('r1',BASE+SOURCE_CODE_START),
              *_value('r2',len(code)),'bl 0x108a04',
              *_value('r0',DATA_START),*_value('r1',BASE+SOURCE_DATA_START),
              *_value('r3',0x03E42000),'ldrb r3,[r3]','cmp r3,#0',
              f'movwne r1,#{(NOR_FILE_BASE+SOURCE_DATA_START)&65535}',
              f'movtne r1,#{(NOR_FILE_BASE+SOURCE_DATA_START)>>16}',
              *_value('r2',len(data)),'bl 0x108a04','dsb sy','isb sy',*restore]
    copy_bytes = asm(copier,copy_at)
    map_at = (copy_at+len(copy_bytes)+3)&~3
    mapper = ['push {r4,lr}','bl 0x108768',*save]
    for start,end,flags in MAP_ROWS:
        mapper += [*_value('r0',start),*_value('r1',end-start),
                   'mov r2,r0',f'mov r3,#{flags}','bl 0x108768']
    mapper += restore
    map_bytes = asm(mapper,map_at)
    stub = copy_bytes+bytes(map_at-copy_at-len(copy_bytes))+map_bytes
    if len(stub)>SOURCE_CODE_START-BOOT_STUB_FILE:
        raise ValueError('Bootstrap exceeds its declared prefix ownership')

    # The native runtime erases broad bootstrap mappings before consuming its
    # optional table. Keep the table and this getter below that high cutoff.
    getter_va = text_fields[2]+text_fields[1]
    getter = asm(_value('r2',maps_va)+['str r2,[r0]','mov r2,#3',
                                    'str r2,[r1]','bx lr'],getter_va)
    if getter_va+len(getter)>0xC30000:
        raise ValueError('Native mapping getter exceeds the text alignment window')
    owned = ((BOOT_STUB_FILE,SOURCE_CODE_END),
             (SOURCE_DATA_START,len(cp)),
             (TABLE_VA-BASE,TABLE_VA-BASE+TABLE_CAPACITY),
             (getter_va-BASE,getter_va-BASE+len(getter)))
    # Ownership is declared above from program/file layout, not inferred by
    # scanning for zero bytes. These byte checks reject an existing occupant.
    for start,end in owned:
        if any(cp[start:end]):
            raise ValueError('Declared source window already occupied at '+hex(start))

    target = bytearray(cp)
    patches = {BOOT_STUB_FILE:stub,SOURCE_CODE_START:code,SOURCE_DATA_START:data,
               TABLE_VA-BASE:table,
               0x1083A0-BASE:asm([f'bl {copy_at}'],0x1083A0),
               0x108520-BASE:asm([f'bl {map_at}'],0x108520),
               0x6314A8-BASE:asm(_value('r2',TABLE_VA)+[
                   'str r2,[r0]','mov r0,#20','str r0,[r1]','bx lr'],0x6314A8),
               0x6314C0-BASE:asm([f'b {getter_va}'],0x6314C0),
               getter_va-BASE:getter,
               0x20128:struct.pack('<I',text_fields[1]+len(getter)),
               0x20134:struct.pack('<I',0x496B84+TABLE_CAPACITY)}
    windows=[]
    previous_end=0
    for at,payload in sorted(patches.items()):
        if at<previous_end or at+len(payload)>len(cp):
            raise ValueError('Fixed region edits overlap or extend the source file')
        windows.append(dict(offset=at,before_hex=cp[at:at+len(payload)].hex(),
                            after_hex=payload.hex()))
        target[at:at+len(payload)]=payload
        previous_end=at+len(payload)
    inverse=bytearray(target)
    for edit in reversed(windows):
        before=bytes.fromhex(edit['before_hex'])
        inverse[edit['offset']:edit['offset']+len(before)]=before
    if bytes(inverse)!=cp or len(target)!=len(cp):
        raise ValueError('Fixed region candidate does not restore its exact input')
    report=dict(schema='a7c2-fixed-region-candidate/1',region=[REGION_START,REGION_END],
                subdivisions=[dict(start=a,end=z,flags=f)for a,z,f in MAP_ROWS],
                copy_entry=copy_at,mapper_entry=map_at,resident_table=TABLE_VA,
                optional_table=maps_va,source_code=[SOURCE_CODE_START,len(code)],
                source_data=[SOURCE_DATA_START,len(data)],source_file_bytes=len(cp),
                source_code_capacity=SOURCE_CODE_END-SOURCE_CODE_START,
                source_data_capacity=len(cp)-SOURCE_DATA_START,
                NOR_data_source=NOR_FILE_BASE+SOURCE_DATA_START,
                source_selection='original boot byte0x03e42000: RAM0 / NOR nonzero',
                original_SOLID_split=False,original_SOLID_extent_preserved=True,
                named_subregion_of='SOLID',new_region_name='A7_FIXED',new_region_type=3,
                original_RAM_heap_and_STACK_rows_preserved=True,windows=windows,
                exact_inverse=True,feature_consumers_connected=False,
                firmware_generator_default_changed=False,extra_menu_slots=False,
                physical_boot=False,camera_io=False,new_verification_hashes=False)
    return bytes(target),report
