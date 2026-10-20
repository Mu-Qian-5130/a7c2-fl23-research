"""Independently verify exported virtual-device files and lifecycle journals.

This checks artifacts, not their origin. Kernel/ELF/source identity and process
termination must be collected separately by the private VM operator.
"""
import argparse
import hashlib
import json
from pathlib import Path


EXPECTED = {
    # result, saved files, controller-owned frees, rejected caller refs, starts
    7: (1, 3, 6, 0, 1), 8: (2, 0, 2, 0, 1), 9: (1, 2, 2, 0, 1),
    10: (1, 2, 2, 1, 1), 11: (2, 0, 0, 0, 0), 12: (3, 0, 0, 0, 1),
    13: (2, 0, 0, 1, 1), 14: (1, 1, 1, 0, 1),
}
SAVED = {7: (2, 3, 4), 9: (1, 2), 10: (1, 2), 14: (1,)}


def verify(folder):
    rows = [tuple(map(int, line.split())) for line in (folder/'results.txt').read_text().splitlines()]
    assert rows == [(g, *values) for g, values in EXPECTED.items()], 'Scenario results differ'
    expected_files = {f'g{g}-f{lease}.pgm' for g, leases in SAVED.items() for lease in leases}
    assert {p.name for p in folder.iterdir()} == expected_files | {'events.txt', 'results.txt'}
    hashes = {}
    for g, leases in SAVED.items():
        for lease in leases:
            # Independent formula over every generated pixel, no controller state.
            words = [(g*1237 + lease*9001 + i*257) % 65536 for i in range(512)]
            expected = b'P5\n32 16\n65535\n' + b''.join(n.to_bytes(2, 'big') for n in words)
            name = f'g{g}-f{lease}.pgm'
            raw = (folder/name).read_bytes()
            assert raw == expected, f'Pixel mismatch: {name}'
            hashes[name] = hashlib.sha256(raw).hexdigest()
    requests, pending, events = {}, {}, []
    for line in (folder/'events.txt').read_text().splitlines():
        name, *numbers = line.split()
        g, ticket, kind, lease = map(int, numbers)
        assert g in EXPECTED
        events.append((name, g, ticket, kind, lease))
        if name in ('offer', 'reject', 'S2'):
            assert ticket == kind == 0
            continue
        key = (g, ticket)
        if name == 'request':
            assert key not in requests and g not in pending, 'Duplicate or overlapping action'
            requests[key] = (kind, lease)
            pending[g] = (ticket, kind, lease, 'request')
        elif name == 'applied':
            assert pending[g] == (ticket, kind, lease, 'request')
            pending[g] = (ticket, kind, lease, 'applied')
        elif name == 'completed':
            assert pending[g] == (ticket, kind, lease, 'applied')
            del pending[g]
        else:
            raise AssertionError(f'Unexpected event: {name}')
    assert not pending, 'Action completion is missing'
    for g, result in EXPECTED.items():
        actions = [(kind, lease) for (generation, _), (kind, lease) in requests.items() if generation == g]
        kinds = [kind for kind, _ in actions]
        assert kinds[:2] == [1, 2] and kinds[-2:] == [8, 9]
        assert all(kinds.count(kind) == 1 for kind in (1, 2, 8, 9))
        assert kinds.count(3) == result[4] and kinds.count(4) == result[4]
        assert kinds.count(5) == 1
        fence = kinds.index(5)
        assert all(i > fence for i, (kind, _) in enumerate(actions) if kind == 6)
        assert [lease for kind, lease in actions if kind == 6] == list(SAVED.get(g, ()))
        consumed = {lease for kind, lease in actions if kind == 6 and not lease % 2}
        assert all(lease not in consumed for kind, lease in actions if kind == 7), 'Double release after consuming save'
        offers = [lease for name, generation, _, _, lease in events if generation == g and name == 'offer']
        assert len(offers) == len(set(offers)), 'Duplicate transferred reference'
        assert sum(name == 'reject' and generation == g for name, generation, *_ in events) == result[3]
        owned = set(offers)
        releases = [lease for kind, lease in actions if kind == 7] + list(consumed)
        assert len(releases) == len(set(releases)) and set(releases) == owned
    reused_tickets = [ticket for (g, ticket) in requests if g in (7, 8, 9)]
    assert all(a < b for a, b in zip(reused_tickets, reused_tickets[1:])), 'Rearm reused an action ticket'
    seq = [(name, kind, lease) for name, g, _, kind, lease in events if g == 7]
    s2 = seq.index(('S2', 0, 0))
    assert all(seq.index(('offer', 0, lease)) > s2 for lease in (5, 6))
    assert all(lease not in SAVED[7] for lease in (1, 5, 6))
    return dict(schema='VIRTUAL_CAPTURE_GUEST_ARTIFACTS/1', camera_io=False,
                scenarios=len(rows), pixel_files=len(hashes), pixels_per_file=512,
                pixel_sha256=hashes, events=len(events), actions=len(requests),
                continuous_save_cancel_rearm=True, exact_release_accounting=True,
                native_camera_bindings=False, physical_precapture_complete=False,
                limits=['Artifacts alone do not attest execution/kernel/source identity',
                        'Pixel exposures, ownership and completion are explicit virtual actors',
                        'Guest tmpfs fsync/readback does not prove physical SD durability'])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run-dir', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    report = verify(args.run_dir)
    with args.output.open('x', encoding='utf-8') as stream:
        json.dump(report, stream, indent=2)
        stream.write('\n')
    print(f"{report['scenarios']} virtual transactions; {report['pixel_files']} pixel files and {report['actions']} action lifecycles verified.")


if __name__ == '__main__':
    main()
