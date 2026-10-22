"""Repeated data-only look imports must not rewrite unchanged UI resources."""
import tempfile,unittest
from pathlib import Path
from unittest.mock import Mock,patch
from looktool import devicejob,nameworker,resources
from test_device_components import resource_fixture

class NameNoopTests(unittest.TestCase):
    def sources(self):
        raw=resources.rename(resource_fixture(),{3:'Nostalgic Neg.'})[0]
        return {name:raw for name in nameworker.filenames()}

    def test_identical_titles_in_every_language_need_no_native_worker(self):
        sources=self.sources()
        with tempfile.TemporaryDirectory() as folder,patch.object(nameworker,'compile_worker') as compiler:
            target,build=nameworker.prepare(sources,{3:'Nostalgic Neg.'},b'ap','1'*16,folder,byte_only=True)
            compiler.assert_not_called()
            self.assertEqual(target,sources);self.assertTrue(build['unchanged'])
            for spec in build['files']:
                self.assertEqual(spec['before_bytes'],spec['after_bytes'])
                self.assertEqual(resources.inverse(target[spec['file']],spec['inverse']),sources[spec['file']])
            job=devicejob.Job(Path(folder)/'unused');job.state={'name_build':build};job.record=Mock()
            job.source=lambda name:sources[name.removeprefix('resources/')]
            for mode in range(4):self.assertEqual(job._invoke(None,'names',mode),{'unchanged':True})
            self.assertEqual(job.resource_target(next(iter(sources))),next(iter(sources.values())))

    def test_later_names_allow_only_other_slot_append_and_index_changes(self):
        expected=resources.rename(resource_fixture(),{1:'Classic Neg.'})[0]
        later=resources.rename(expected,{2:'Classic Chrome'})[0]
        self.assertTrue(resources.later_unselected_names(expected,later,1))
        self.assertFalse(resources.later_unselected_names(expected,later,2))
        self.assertFalse(resources.later_unselected_names(expected,resources.rename(later,{1:'Other'})[0],1))
        damaged=bytearray(later);at=damaged.index(b'Original 4');damaged[at]=ord('X')
        self.assertFalse(resources.later_unselected_names(expected,bytes(damaged),1))

    def test_strict_readback_stays_strict_and_cleanup_preserves_job_backup_paths(self):
        sources={name:resource_fixture() for name in nameworker.filenames()}
        with tempfile.TemporaryDirectory() as folder,patch.object(nameworker,'compile_worker',return_value={}):
            root=Path(folder)
            expected,build=nameworker.prepare(sources,{1:'Classic Neg.'},b'ap','1'*16,root/'worker/names',byte_only=True)
            actual={name:resources.rename(raw,{2:'Classic Chrome'})[0] for name,raw in expected.items()}
            job=devicejob.Job(root);job.record=Mock()
            job.state={'byte_checks':True,'name_build':build,'slot':1,'name':'Classic Neg.','layout':{'label_ids':resources.LABEL_IDS}}
            job.source=lambda name:sources[name.removeprefix('resources/')]
            camera=Mock();camera.read.side_effect=lambda path:actual[path.removeprefix('/usr/share/app/')]
            with self.assertRaises(ValueError):job._resource_readback(camera,True)
            self.assertEqual(job._resource_readback(camera,True,allow_later_slots=True),actual)
            self.assertTrue(job._later_name_updates)
            old=(root/'worker/names/names.private.h').read_text()
            cleanup=nameworker.prepare_cleanup(build,root/'worker/names/names.private.h',actual,root/'worker/names-cleanup')
            new=(root/'worker/names-cleanup/names.private.h').read_text()
            self.assertEqual([line for line in old.splitlines() if not line.startswith('static const u32 after_sizes')],
                             [line for line in new.splitlines() if not line.startswith('static const u32 after_sizes')])
            self.assertEqual([s['after_bytes'] for s in cleanup['files']],[len(actual[s['file']]) for s in build['files']])

    def test_one_different_language_still_compiles_the_name_transaction(self):
        sources=self.sources();name=next(iter(sources));sources[name]=resource_fixture()
        with tempfile.TemporaryDirectory() as folder,patch.object(nameworker,'compile_worker',return_value={}) as compiler:
            target,build=nameworker.prepare(sources,{3:'Nostalgic Neg.'},b'ap','1'*16,folder,byte_only=True)
            compiler.assert_called_once();self.assertFalse(build.get('unchanged',False))
            self.assertTrue(all(resources.decode(raw)['entries'][resources.LABEL_IDS[2]]['text']=='Nostalgic Neg.' for raw in target.values()))

    def test_invalid_names_are_rejected_before_any_worker(self):
        with tempfile.TemporaryDirectory() as folder,patch.object(nameworker,'compile_worker') as compiler:
            with self.assertRaises(ValueError):nameworker.prepare(self.sources(),{3:''},b'ap','1'*16,folder,byte_only=True)
            compiler.assert_not_called()

if __name__=='__main__':unittest.main()
