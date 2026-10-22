"""Actual ARM64 forward worker under limited space; no physical camera."""
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from looktool import nameworker,nativebuild
from test_names_native import FS,DIR,PLUGIN,REQUEST,RESULT


class ForwardNamesTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp=tempfile.TemporaryDirectory();cls.root=Path(cls.tmp.name)
        # Reuse a valid synthetic native resource, not any camera data.
        import struct
        raw=bytearray(b'uxc\7\0\0\0\0'+struct.pack('<HHI',8,5,2860|(2860<<12))+b'\xff\xff'*2860)
        struct.pack_into('<H',raw,16,0);raw.extend(struct.pack('<I',0x1e00a000)+b'Native\0\0');raw.extend(bytes(8192-len(raw)))
        cls.original=bytes(raw);cls.files=nameworker.filenames()[:8]
        cls.target,cls.build=cls.make(cls.files,cls.root/'eight')
        header=Path(cls.build['path']).with_name('names.private.h')
        old=header.with_name('legacy.h');old.write_text(header.read_text().replace('#define BYTE_NAME_STREAM_INSTALL 1',''))
        cls.legacy=old.with_suffix('.so')
        nativebuild.compile_worker(nativebuild.ROOT/'src/looks/native/names.c',old,cls.legacy,fingerprints=False)

    @classmethod
    def make(cls,files,folder):
        with patch.object(nameworker,'filenames',return_value=files):
            target,build=nameworker.prepare({n:cls.original for n in files},{1:'Classic Neg.',2:'Classic Chrome'},
                b'fixture app','abcd'*4,folder,byte_only=True)
        header=folder/'names.private.h'
        header.write_text(header.read_text()+'\n#define NAMES_REQUEST "'+REQUEST+'"\n#define NAMES_RESULT "'+RESULT+'"\n')
        nativebuild.compile_worker(nativebuild.ROOT/'src/looks/native/names.c',header,Path(build['path']),fingerprints=False)
        return target,build

    @classmethod
    def tearDownClass(cls):cls.tmp.cleanup()

    def fs(self,**kwargs):return FS({n:self.original for n in self.files},forward=True,free_blocks=16,**kwargs)

    def clean(self,fs):
        self.assertTrue(fs.ro)
        self.assertNotIn(PLUGIN,fs.files)
        self.assertFalse(any('.a7c2-lut-' in path for path in fs.files))

    def test_old_forward_reproduces_enospc_but_stream_commits_all(self):
        fs=self.fs();v=fs.run(self.legacy,1)
        self.assertEqual(v[5],-28);self.assertEqual(v[14],0);self.clean(fs)
        fs=self.fs();v=fs.run(self.build['path'],1)
        self.assertEqual(v[3:6],(9,len(self.files),0))
        self.assertEqual(v[12:15],(8,0,8));self.clean(fs)
        for n in self.files:self.assertEqual(bytes(fs.files[DIR+n]),self.target[n])
        self.assertLessEqual(fs.peak_extra,len(self.files)+3)
        self.assertTrue(nameworker.validate(nameworker.REPORT.pack(*v),1,self.build)['native_verified'])

    def test_partial_write_rename_and_sync_failure_rolls_back_exact_originals(self):
        for fault in ('write','rename','fsync'):
            with self.subTest(fault=fault):
                fs=self.fs(fault=fault);v=fs.run(self.build['path'],1)
                self.assertLess(v[5],0);self.assertEqual(v[6],0)
                self.assertEqual(v[14],v[15]);self.clean(fs)
                for n in self.files:self.assertEqual(bytes(fs.files[DIR+n]),self.original)

    def test_preflight_low_space_or_inode_exhaustion_changes_nothing(self):
        for free,inodes in ((0,100),(5,100),(16,0),(16,1)):
            fs=FS({n:self.original for n in self.files},forward=True,free_blocks=free);fs.free_inodes=inodes
            v=fs.run(self.build['path'],0)
            self.assertEqual(v[5],-28);self.assertEqual(fs.renames,0);self.clean(fs)

    def test_live_old_mmaps_are_not_modified_when_space_runs_out(self):
        fs=self.fs(mapped=True);v=fs.run(self.build['path'],1)
        self.assertEqual(v[5],-28);self.assertEqual(v[6],0);self.clean(fs)
        self.assertTrue(all(bytes(inode)==self.original for inode in fs.retained))
        self.assertTrue(all(bytes(fs.files[DIR+n])==self.original for n in self.files))

    def test_production_68_files_fit_without_68_staging_copies(self):
        files=nameworker.filenames();target,build=self.make(files,self.root/'all68')
        fs=FS({n:self.original for n in files},forward=True,free_blocks=80)
        v=fs.run(build['path'],1)
        self.assertEqual(v[3:6],(9,68,0));self.assertEqual(v[12:15],(68,0,68));self.clean(fs)
        self.assertTrue(all(bytes(fs.files[DIR+n])==target[n] for n in files))

    def test_reported_language_sizes_match_host_bytes_on_first_and_later_install(self):
        # The recipient report identifies these lengths and a 132-byte first
        # extension. Use synthetic contents, never redistributed camera files.
        files=nameworker.filenames()
        sources={n:self.original for n in files}
        for name,size in (('string_arabic_horizontal.uxc',161360),
                          ('string_croatian_vertical.uxc',119160)):
            sources[name]=self.original+bytes(size-len(self.original))
        names={1:'GR Negative Film',2:'GR Positive Film',3:'Classic Neg.',
               4:'Classic Chrome',5:'Reala Ace',6:'Kodak 5207'}
        for generation in range(2):
            folder=self.root/('reported-sizes-'+str(generation))
            target,build=nameworker.prepare(sources,names,b'fixture app','abcd'*4,
                folder,byte_only=True)
            header=folder/'names.private.h'
            header.write_text(header.read_text()+'\n#define NAMES_REQUEST "'+REQUEST+'"\n#define NAMES_RESULT "'+RESULT+'"\n')
            nativebuild.compile_worker(nativebuild.ROOT/'src/looks/native/names.c',
                header,Path(build['path']),fingerprints=False)
            fs=FS(sources,forward=True,free_blocks=256)
            result=fs.run(build['path'],1)
            self.assertEqual(result[3:6],(9,68,0));self.clean(fs)
            for name in files:
                self.assertEqual(bytes(fs.files[DIR+name]),target[name],name)
            if generation==0:
                self.assertEqual(len(target['string_arabic_horizontal.uxc']),161492)
                self.assertEqual(len(target['string_croatian_vertical.uxc']),119292)
            sources=target
            names[5]='Kodak 2383'

    def test_readonly_remount_failure_reports_committed_names_without_claiming_success(self):
        fs=self.fs(fault='readonly_busy');v=fs.run(self.build['path'],1)
        self.assertEqual(v[3],9);self.assertEqual(v[5],-16);self.assertEqual(v[8],-16)
        self.assertEqual(v[14],8);self.assertFalse(fs.ro)
        self.assertTrue(all(bytes(fs.files[DIR+n])==self.target[n] for n in self.files))
        with self.assertRaisesRegex(ValueError,'EBUSY'):
            nameworker.validate(nameworker.REPORT.pack(*v),1,self.build)
