"""Pinned on-disk configuration-helper spans; no emulator or device imports."""
import hashlib
from .reference import SPECS

BASE = 0x108000
ENTRY = 0xb74730
SOURCE_SPANS = ((0xb7160a, 0x24), (ENTRY, 0x28), (0x68530a, 0x0a))


def compare_current(stock, current):
    """Admit these spans only, never a whole modified firmware or its RAM."""
    if hashlib.sha256(stock).hexdigest() != SPECS['a7c2-2.01']['sha256']:
        raise ValueError('Unsupported original stock CP')
    if len(current) != len(stock):
        raise ValueError('Current CP file extent differs')
    for address, size in SOURCE_SPANS:
        offset = address - BASE
        if current[offset:offset+size] != stock[offset:offset+size]:
            raise ValueError(f'Current source span differs at {address:#x}')
    return dict(spans=len(SOURCE_SPANS), current_file_spans_equal=True,
                whole_program_admitted=False, loaded_RAM_verified=False)
