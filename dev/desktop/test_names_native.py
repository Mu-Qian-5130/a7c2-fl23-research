"""Run the real ARM64 inverse worker with finite /usr space and I/O faults.

Synthetic syscalls test resource bytes, inode replacement, and reports. This
does not establish camera boot safety or live UI behavior.
"""
import importlib.util
from pathlib import Path
import struct
import sys
import tempfile
import unittest
from unittest.mock import patch
from unicorn import UC_HOOK_INTR
from unicorn.arm64_const import (UC_ARM64_REG_X0, UC_ARM64_REG_X1, UC_ARM64_REG_X2,
    UC_ARM64_REG_X3, UC_ARM64_REG_X4, UC_ARM64_REG_X8)
from looktool import checkpointworker, nameworker, nativebuild, resources

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location('names_elf_loader', ROOT / 'dev/shutter_sound/verify_worker.py')
sys.path.insert(0, str(ROOT / 'dev/shutter_sound'))
loader = importlib.util.module_from_spec(spec)
spec.loader.exec_module(loader)

DIR = '/usr/share/app/'
REQUEST = '/tmp/jiritsu/checkpoint.names.request'
RESULT = '/tmp/jiritsu/checkpoint.names.result'
PLUGIN = '/tmp/jiritsu/libJit.so'


class FS:
    def __init__(self, current, free_blocks=8, fault=None, mapped=False, forward=False):
        self.forward=forward
        self.files = {DIR + n: bytearray(b) for n, b in current.items()}
        self.retained = list(self.files.values()) if mapped else []
        self.limit = self.used() + free_blocks
        self.free_inodes = 100
        self.fault = fault
        self.injected = False
        self.renames = 0
        self.ro = True
        self.peak_extra = 0
        self.initial_used = self.used()
        self.allowed = set(self.files)
        self.counter = 10

    def used(self):
        unique = {id(b): b for p, b in self.files.items() if p.startswith(DIR)}
        unique.update({id(b): b for b in self.retained})
        return sum((len(b) + 4095) // 4096 for b in unique.values())

    def run(self, worker, mode=2):
        cpu, start, end = loader.load(worker)
        self.files[REQUEST] = bytearray(struct.pack('<8sII', b'A7NAM001', mode, 0))
        self.files[PLUGIN] = bytearray(b'owned')
        handles = {}
        def string(at):
            value = bytearray()
            while len(value) < 1024:
                c = bytes(cpu.mem_read(at + len(value), 1))
                if c == b'\0':
                    return value.decode('ascii')
                value += c
            raise AssertionError('Unterminated syscall path')
        def syscall(uc, number, user):
            no = uc.reg_read(UC_ARM64_REG_X8)
            a = [uc.reg_read(r) for r in (UC_ARM64_REG_X0, UC_ARM64_REG_X1,
                UC_ARM64_REG_X2, UC_ARM64_REG_X3, UC_ARM64_REG_X4)]
            result = 0
            if no in (172, 175):
                result = 519 if no == 172 else 0
            elif no == 56:
                path, flags = string(a[1]), a[2]
                if path == '/proc/mounts':
                    self.files[path] = bytearray(('/dev/nflasha15 /usr ext2 '
                        + ('ro' if self.ro else 'rw') + ',sync 0 0\n').encode())
                if path == DIR.rstrip('/'):
                    inode = bytearray()
                elif flags & 64:
                    if path.startswith(DIR):
                        assert not self.ro
                        assert (path.startswith(DIR + '.a7c2-checkpoint-') and path.endswith('.original')) or (self.forward and path.startswith(DIR+'.a7c2-lut-') and path.endswith(('.stage','.original')))
                        assert self.free_inodes > 0
                    else:
                        assert path == RESULT
                    if path in self.files and flags & 128:
                        result = -17
                    else:
                        self.files[path] = bytearray()
                    inode = self.files.get(path)
                else:
                    inode = self.files.get(path)
                    if inode is None:
                        result = -2
                if not result:
                    self.counter += 1
                    result = self.counter
                    handles[result] = [path, inode, 0]
            elif no == 57:
                handles.pop(a[0])
            elif no == 80:
                path, inode, _ = handles[a[0]]
                assert path.startswith(DIR)
                st = bytearray(128)
                struct.pack_into('<QQIII', st, 0, 15, id(inode), 0o100644, 1, 57285)
                struct.pack_into('<I', st, 28, 1000)
                struct.pack_into('<q', st, 48, len(inode))
                uc.mem_write(a[1], bytes(st))
            elif no in (63, 67):
                path, inode, pos = handles[a[0]]
                at = a[3] if no == 67 else pos
                data = bytes(inode[at:at + a[2]])
                if data:
                    uc.mem_write(a[1], data)
                result = len(data)
                handles[a[0]][2] = at + result
            elif no == 64:
                path, inode, pos = handles[a[0]]
                data = bytes(uc.mem_read(a[1], a[2]))
                if path.startswith(DIR):
                    assert not self.ro and (path.endswith('.original') or (self.forward and path.endswith('.stage')))
                    if self.fault == 'write' and self.renames == 3 and not self.injected:
                        self.injected = True
                        result = -28
                    else:
                        needed = (max(len(inode), pos + len(data)) + 4095) // 4096 - (len(inode) + 4095) // 4096
                        if self.used() + needed > self.limit:
                            result = -28
                if not result:
                    inode[pos:pos + len(data)] = data
                    result = len(data)
                    handles[a[0]][2] += result
                    self.peak_extra = max(self.peak_extra, self.used() - self.initial_used)
            elif no == 35:
                path = string(a[1])
                assert path == PLUGIN or path.startswith(DIR + '.a7c2-checkpoint-') or (self.forward and path.startswith(DIR+'.a7c2-lut-'))
                if path not in self.files:
                    result = -2
                else:
                    self.files.pop(path)
            elif no == 38:
                src, dst = string(a[1]), string(a[3])
                assert (src.endswith('.original') or (self.forward and src.endswith('.stage'))) and dst in self.allowed and not self.ro
                if self.fault == 'rename' and self.renames == 3 and not self.injected:
                    self.injected = True
                    result = -5
                else:
                    self.files[dst] = self.files.pop(src)
                    self.renames += 1
            elif no in (55, 52):
                assert handles[a[0]][0].endswith('.original') or (self.forward and handles[a[0]][0].endswith('.stage'))
            elif no == 82:
                path = handles[a[0]][0]
                if self.fault == 'fsync' and path == DIR.rstrip('/') and self.renames == 3 and not self.injected:
                    self.injected = True
                    result = -5
            elif no == 40:
                assert string(a[1]) == '/usr'
                if a[3] & 1 and self.fault == 'readonly_busy' and self.renames:
                    result = -16
                else:
                    self.ro = bool(a[3] & 1)
            elif no == 43:
                assert string(a[0]) == DIR.rstrip('/')
                st = bytearray(120)
                struct.pack_into('<qqQQQQQ', st, 0, 0xef53, 4096, self.limit,
                    self.limit - self.used(), self.limit - self.used(), 1000, self.free_inodes)
                uc.mem_write(a[1], bytes(st))
            else:
                raise AssertionError('Unexpected syscall ' + str(no))
            uc.reg_write(UC_ARM64_REG_X0, result & ((1 << 64) - 1))
        cpu.hook_add(UC_HOOK_INTR, syscall)
        cpu.emu_start(start, end, count=100_000_000)
        raw = bytes(self.files[RESULT])
        assert len(raw) == nameworker.REPORT.size
        return nameworker.REPORT.unpack(raw)


class NamesNativeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        cls.root = Path(cls.temp.name)
        # Eight resources are enough to exceed one-file space. Also exercise
        # the production count 68 in a separate compiled build below.
        cls.files = nameworker.filenames()[:8]
        raw = bytearray(b'uxc\x07\0\0\0\0' + struct.pack('<HHI', 8, 5, 2860 | (2860 << 12)) + b'\xff\xff' * 2860)
        struct.pack_into('<H', raw, 16, 0)
        raw.extend(struct.pack('<I', 0x1e00a000) + b'Native\0\0')
        raw.extend(bytes(8192 - len(raw)))
        cls.original = bytes(raw)
        cls.named = resources.rename(cls.original, {1: 'Classic Neg.', 2: 'Classic Chrome'})[0]
        with patch.object(nameworker, 'filenames', return_value=cls.files):
            cls.build = checkpointworker.build_names(
                {'resources/' + n: cls.named for n in cls.files},
                {'resources/' + n: cls.original for n in cls.files}, cls.root / 'stream', 'test')
        header = (cls.root / 'stream/names.private.h').read_text()
        old = cls.root / 'legacy.h'
        old.write_text(header.replace('#define CHECKPOINT_STREAM_RESTORE 1', ''))
        cls.legacy = cls.root / 'legacy.so'
        nativebuild.compile_worker(ROOT / 'src/looks/native/names.c', old, cls.legacy, fingerprints=False)

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def fs(self, **kw):
        return FS({n: self.named for n in self.files}, **kw)

    def assert_clean(self, fs):
        self.assertTrue(fs.ro)
        self.assertFalse(any('.a7c2-checkpoint-' in n for n in fs.files))
        self.assertNotIn(PLUGIN, fs.files)

    def test_reproduces_old_enospc_without_committing_then_stream_succeeds(self):
        old = self.fs(free_blocks=8)
        report = old.run(self.legacy)
        self.assertEqual(report[5], -28)
        self.assertEqual(report[15], 0)
        self.assertGreater(report[12], 0)
        self.assert_clean(old)
        fs = self.fs(free_blocks=8)
        report = fs.run(self.build['path'])
        self.assertEqual(report[3], 9)
        self.assertEqual(report[5], 0)
        self.assertEqual(report[15], len(self.files))
        self.assertLessEqual(fs.peak_extra, 2)
        self.assertTrue(all(bytes(fs.files[DIR + n]) == self.original for n in self.files))
        self.assert_clean(fs)

    def test_mode_four_checks_space_and_inodes_without_resource_writes(self):
        for free_blocks, free_inodes in ((0, 100), (3, 100), (8, 0)):
            with self.subTest(free_blocks=free_blocks, free_inodes=free_inodes):
                fs = self.fs(free_blocks=free_blocks)
                fs.free_inodes = free_inodes
                report = fs.run(self.build['path'], 4)
                self.assertEqual(report[5], -28)
                self.assertEqual(fs.renames, 0)
                self.assert_clean(fs)

    def test_partial_failures_clean_pending_inode_and_resume_without_replaying_restored_files(self):
        for fault in ('write', 'rename', 'fsync'):
            with self.subTest(fault=fault):
                fs = self.fs(fault=fault)
                report = fs.run(self.build['path'])
                self.assertLess(report[5], 0)
                self.assertEqual(report[15], 3)
                self.assert_clean(fs)
                for index, n in enumerate(self.files):
                    self.assertEqual(bytes(fs.files[DIR + n]), self.original if index < 3 else self.named)
                fs.fault = None
                report = fs.run(self.build['path'])
                self.assertEqual(report[5], 0)
                self.assertEqual(report[15], len(self.files) - 3)
                self.assert_clean(fs)

    def test_mapped_old_inodes_remain_intact_and_space_failure_is_reported(self):
        fs = self.fs(free_blocks=8, mapped=True)
        report = fs.run(self.build['path'])
        self.assertEqual(report[5], -28)
        self.assertEqual(report[15], 4)
        self.assertTrue(all(bytes(b) == self.named for b in fs.retained))
        self.assert_clean(fs)

    def test_production_68_resource_count_with_one_file_space(self):
        files = nameworker.filenames()
        build = checkpointworker.build_names({'resources/' + n: self.named for n in files},
            {'resources/' + n: self.original for n in files}, self.root / 'all68', 'all68')
        fs = FS({n: self.named for n in files}, free_blocks=8)
        report = fs.run(build['path'])
        self.assertEqual(report[3:6], (9, 68, 0))
        self.assertEqual(report[15], 68)
        self.assertLessEqual(fs.peak_extra, 2)
        self.assert_clean(fs)

    def test_completed_resource_replacement_can_leave_readonly_remount_busy(self):
        fs = self.fs(free_blocks=100, mapped=True, fault='readonly_busy')
        report = fs.run(self.build['path'])
        self.assertEqual(report[3], 9)
        self.assertEqual(report[5], -16)
        self.assertEqual(report[8], -16)
        self.assertEqual(report[15], len(self.files))
        self.assertFalse(fs.ro)
        self.assertTrue(all(bytes(fs.files[DIR + n]) == self.original for n in self.files))
        self.assertTrue(all(bytes(b) == self.named for b in fs.retained))
        raw = nameworker.REPORT.pack(*report)
        with self.assertRaises(ValueError):
            checkpointworker.names_report(raw, 2, self.build)
        build = dict(self.build, defer_busy_readonly=True)
        parsed = checkpointworker.names_report(raw, 2, build)
        self.assertFalse(parsed['readonly_verified'])
        self.assertTrue(parsed['readonly_deferred_busy'])
        broken = list(report); broken[15] -= 1
        with self.assertRaises(ValueError):
            checkpointworker.names_report(nameworker.REPORT.pack(*broken), 2, build)
