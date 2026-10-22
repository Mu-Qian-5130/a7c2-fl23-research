"""Look-page batches call the combined writer once, without unrelated toggles."""
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch
from desktopapp import lookbatch, presets, worker

AVAILABLE = Path(presets.catalog()[0]['path']).is_file()


class LookBatchTests(unittest.TestCase):
    def setUp(self):
        tmp=tempfile.TemporaryDirectory();self.addCleanup(tmp.cleanup)
        self.root=Path(tmp.name)
        env=patch.dict(os.environ,{'A7C2_DESKTOP_DATA':str(self.root/'app')})
        env.start();self.addCleanup(env.stop)

    def test_empty_or_bad_input_stops_before_constructing_camera_job(self):
        for rows in ([],[dict(slot=5,path='not-a-file.a7look')]):
            with self.subTest(rows=rows),patch('looktool.direct.DirectJob') as factory:
                with self.assertRaises((ValueError,FileNotFoundError)):
                    worker.run('direct_looks_import',dict(workspace=str(self.root/'work'),firmware='2.01',
                        power_confirmed=True,looks=rows),self.root)
                factory.assert_not_called()

    def test_restore_only_needs_no_file_and_uses_one_combined_writer(self):
        obj=Mock();obj.root=self.root/'restore'
        obj.run_direct.return_value=dict(mode='install_all',phase='AWAITING_RELOAD')
        operations=[dict(slot=2,action='restore'),dict(slot=6,action='restore')]
        with patch('looktool.direct.DirectJob',return_value=obj):
            result=worker.run('direct_looks_import',dict(workspace=str(obj.root),firmware='2.01',
                power_confirmed=True,operations=operations),self.root)
        obj.run_direct.assert_called_once()
        obj.verify_direct.assert_not_called()
        options=obj.run_direct.call_args.kwargs['bundle_options']
        self.assertEqual(options['reset_slots'],[2,6]);self.assertEqual(options['looks'],[])
        self.assertFalse(options['fl23']);self.assertFalse(options['sound'])
        self.assertFalse(options['vertical_persistent'])
        self.assertEqual(result['slots'],[2,6]);self.assertEqual(result['operations'],operations)

    def test_invalid_operations_do_not_construct_camera_job(self):
        bad_rows=[[],[dict(slot=0,action='restore')],[dict(slot=7,action='restore')],
            [dict(slot=True,action='restore')],[dict(slot='2',action='restore')],
            [dict(slot=2,action='restore'),dict(slot=2,action='restore')],
            [dict(slot=2,action='restore'),dict(slot=2,action='write',path='absent.a7look')],
            [dict(slot=2,action='unknown')],[dict(slot=2,action='write')],
            [dict(slot=2,action='write',path='absent.a7look')],
            [dict(slot=2,action='write',path='absent.a7look',name=42)]]
        for operations in bad_rows:
            with self.subTest(operations=operations),patch('looktool.direct.DirectJob') as factory:
                with self.assertRaises((ValueError,FileNotFoundError)):
                    worker.run('direct_looks_import',dict(workspace=str(self.root/'bad'),firmware='2.01',
                        power_confirmed=True,operations=operations),self.root)
                factory.assert_not_called()

    @unittest.skipUnless(AVAILABLE,'Distribution preset asset')
    def test_mixed_operations_keep_requested_order_and_one_backend_transaction(self):
        obj=Mock();obj.root=self.root/'mixed'
        obj.run_direct.return_value=dict(mode='install_all',phase='AWAITING_RELOAD')
        rows=[dict(presets.catalog()[5],action='write',name='  My GR  '),
              dict(slot=4,action='restore'),dict(presets.catalog()[1],action='write')]
        with patch('looktool.direct.DirectJob',return_value=obj):
            result=worker.run('direct_looks_import',dict(workspace=str(obj.root),firmware='2.01',
                power_confirmed=True,operations=rows,options=dict(fl23=True,sound=True)),self.root)
        obj.run_direct.assert_called_once()
        options=obj.run_direct.call_args.kwargs['bundle_options']
        self.assertEqual(options['reset_slots'],[4])
        self.assertEqual([r['slot'] for r in options['looks']],[6,2])
        self.assertEqual(options['looks'][0]['name'],'My GR')
        self.assertEqual(result['slots'],[6,4,2])
        self.assertFalse(options['fl23']);self.assertFalse(options['sound'])

    def test_bundle_documents_rejects_reset_write_collisions_before_file_access(self):
        from looktool import bundle
        for resets,looks in (([2,2],[]),([False],[]),([7],[]),('2',[]),
                             ([2],[dict(slot=2,path='absent.a7look')])):
            with self.subTest(resets=resets),patch('looktool.lookfile.read') as reader:
                with self.assertRaises(ValueError):bundle.documents(dict(reset_slots=resets,looks=looks))
                reader.assert_not_called()

    @unittest.skipUnless(AVAILABLE,'Distribution preset asset')
    def test_defaults_keep_six_order_without_enabling_fl23_or_sound(self):
        result=lookbatch.options(presets.catalog())
        self.assertFalse(result['fl23']);self.assertFalse(result['sound'])
        self.assertEqual([r['name'] for r in result['looks']],list(presets.NAMES))
        self.assertEqual([r['slot'] for r in result['looks']],list(range(1,7)))

    @unittest.skipUnless(AVAILABLE,'Distribution preset asset')
    def test_sparse_selected_slots_and_custom_name_are_not_filled_in(self):
        rows=[presets.catalog()[1],dict(presets.catalog()[4],name='My GR')]
        result=lookbatch.options(rows)
        self.assertEqual([r['slot'] for r in result['looks']],[2,5])
        self.assertEqual(result['looks'][1]['name'],'My GR')
        for bad in ([rows[0],rows[0]],[dict(rows[0],name='x'*64)]):
            with self.assertRaises(ValueError):lookbatch.options(bad)

    @unittest.skipUnless(AVAILABLE,'Distribution preset asset')
    def test_one_backend_transaction_for_all_six_and_no_mid_install_verify(self):
        obj=Mock();obj.root=self.root/'batch'
        obj.run_direct.return_value=dict(mode='install_all',phase='AWAITING_RELOAD')
        with patch('looktool.direct.DirectJob',return_value=obj):
            result=worker.run('direct_looks_import',dict(workspace=str(obj.root),firmware='2.01',
                power_confirmed=True,looks=presets.catalog(),options=dict(fl23=True,sound=True)),self.root)
        obj.run_direct.assert_called_once()
        obj.verify_direct.assert_not_called()
        args=obj.run_direct.call_args
        self.assertEqual(args.args,('install_all',))
        self.assertEqual(len(args.kwargs['bundle_options']['looks']),6)
        self.assertFalse(args.kwargs['bundle_options']['fl23'])
        self.assertFalse(args.kwargs['bundle_options']['sound'])
        self.assertEqual(result['phase'],'COMPLETED')
        self.assertTrue(result['reload_required'])
        self.assertEqual(result['slots'],list(range(1,7)))
