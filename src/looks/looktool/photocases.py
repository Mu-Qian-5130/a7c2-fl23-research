"""Native-photo lab cases. Diagnostic records are not fitted film looks."""
import copy
from pathlib import Path
from . import lookfile, native, photoformat, photobuild, photobasis, photomeasure, six

NAMES = ('disabled', 'native-identity', 'diagnostic-pairs', 'optimized-six',
         'compiled-six', 'measure-1', 'measure-2', 'measure-3', 'restore') + photomeasure.CASES


def specs(name):
    if name not in NAMES:raise ValueError('Unknown native-photo test case')
    knobs = [{} for _ in range(6)]
    mask = 0 if name in ('disabled', 'optimized-six', 'compiled-six', 'restore') else 63
    if name == 'diagnostic-pairs':
        knobs[0] = {'tone': [-128, 0, 0]}
        knobs[1] = {'tone': [128, 0, 0]}
        for index, sign in ((2, -1), (3, 1)):
            knobs[index] = {'matrices': [[sign*x for x in (0, 64, -32, 32, -64, 0)] for _ in range(3)]}
        for index, sign in ((4, -1), (5, 1)):
            knobs[index] = {'chroma': [[0, 0, 0, 0] + [sign*64]*4 for _ in range(3)]}
    elif name.startswith('measure-'):
        probes = []
        for component, amount in enumerate((64, 128, 128)):
            values = [0]*3;values[component] = amount
            probes.append({'tone': values})
        for component in range(6):
            values = [0]*6;values[component] = 32
            probes.append({'matrices': [values[:] for _ in range(3)]})
        for component in range(8):
            values = [0]*8;values[component] = 32
            probes.append({'chroma': [values[:] for _ in range(3)]})
        probes.append({'tone': [32, -32, 16],
                       'matrices': [[8, -8, 4, -4, 8, -8] for _ in range(3)],
                       'chroma': [[8, -8, 4, -4, 8, -8, 4, -4] for _ in range(3)]})
        start = (int(name[-1])-1)*6
        knobs = copy.deepcopy(probes[start:start+6])
    elif name in photomeasure.CASES:
        knobs = [photomeasure.knobs(row['controls']) for row in photomeasure.case(name)]
    return {'case': name, 'active_mask': mask, 'knobs': knobs,
            'zero_residual_tables': name == 'diagnostic-pairs' or name.startswith('measure-'),
            'fitted_film_looks': name == 'optimized-six',
            'requires_physical_validation': True}


def make_target(programs, baseline, name, *, looks=None, documents=None):
    description = specs(name)
    if name == 'restore':return dict(programs), description
    tables = [bytes(native.RAW_BYTES) for _ in range(6)]
    if name in ('optimized-six', 'compiled-six'):
        if documents is None:
            if looks is None:raise ValueError('Provide the six compiled candidate files')
            documents = [lookfile.read(Path(looks)/('slot'+str(slot)+'.a7look')) for slot in range(1, 7)]
        if len(documents) != 6:raise ValueError('Six compiled look documents required')
        for index, document in enumerate(documents):
            tables[index] = lookfile.validate(document)
            if document.get('native_photo') is not None:
                if name == 'optimized-six':raise ValueError('The correction-only control case cannot contain native photo stages')
                photobasis.compile_delta(baseline, document['native_photo'])
                basis = document['native_photo']['runtime_basis']
                description['knobs'][index] = {'tone': basis['tone_q10'],
                    'matrices': basis['matrix_planes'], 'chroma': basis['chroma_planes']}
                description['active_mask'] |= 1 << index
        description['documents'] = documents
        description['titles_modified'] = False
    cp, report = photobuild.build(programs['cpapp-b.bin'], baseline,
                                  description['knobs'], active_mask=description['active_mask'])
    if name in photomeasure.CASES:
        description['measurement'] = photomeasure.case(name)
        tables = [photomeasure.table(row['table']) for row in description['measurement']]
        description['zero_residual_tables'] = all(row['table'] == 'zero' for row in description['measurement'])
    if description['zero_residual_tables'] or name in ('optimized-six', 'compiled-six') or name in photomeasure.CASES:
        payload = six.prefix(tables)
        cp = bytearray(cp);cp[six.TABLE_FILE:six.TABLE_FILE+len(payload)] = payload;cp = bytes(cp)
    description['native_build'] = report
    return {'appFw.so': programs['appFw.so'], 'cpapp-b.bin': cp}, description


def write_priority(restoring=False):
    """Stage new storage before redirecting code; reverse that for restoration.

    This orders one in-place native execution. It does not make a firmware
    write power-loss atomic. Native failure rollback reverses this order.
    """
    def order(span):
        chip, at, _, _ = span
        if chip != 1:raise ValueError('Native photo lab may change CP program bytes only')
        owned = 0xb27590 <= at < 0xb27f0e or 0x1101ae0 <= at < 0x1101fa0
        activation = at <= 0xb27500 < at + len(span[2])
        rank = (2 if owned else -1 if activation else 0) if restoring else (0 if owned else 2 if activation else 1)
        return rank, at
    return order
