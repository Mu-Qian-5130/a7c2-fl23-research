"""Versioned source DCPs and automatic activation receipts, without USB."""
import base64
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from looktool import rawidentity,rawprofiles
from test_rawprofiles import profile


class IdentityTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name);self.dcp=self.root/'source.dcp';self.dcp.write_bytes(profile('Same Name'))
        self.settings=self.root/'settings.json'
        rawprofiles.write_json(self.settings,dict(library=str(self.root/'library'),registry=str(self.root/'registry'),
                                                  adobe_profiles=str(self.root/'Adobe')))

    def test_descriptor_keeps_source_bytes_and_unique_version(self):
        a=rawidentity.descriptor(self.dcp,'NC');b=rawidentity.descriptor(self.dcp,'NC')
        self.assertNotEqual(a['id'],b['id'])
        self.assertNotEqual(a['adobe_profile'],b['adobe_profile'])
        self.assertEqual(rawidentity.source_bytes(a),self.dcp.read_bytes())

    def test_renaming_changes_no_other_dcp_fields(self):
        source=self.dcp.read_bytes();renamed=rawidentity.renamed_dcp(source,'A new version')
        self.assertEqual(rawprofiles.dcp_info(renamed)['profile'],'A new version')
        self.assertEqual(rawprofiles.dcp_info(renamed)['model'],rawprofiles.dcp_info(source)['model'])
        self.assertEqual(rawprofiles.dcp_info(renamed)['copyright'],rawprofiles.dcp_info(source)['copyright'])
        self.assertEqual(self.dcp.read_bytes(),source)

    def test_materialized_version_is_immutable(self):
        value=rawidentity.descriptor(self.dcp)
        path=rawidentity.materialize(value,self.root/'library')
        self.assertEqual(rawprofiles.dcp_info(path)['profile'],value['adobe_profile'])
        value['dcp_base64']=base64.b64encode(profile('Same Name','changed')).decode()
        with self.assertRaisesRegex(ValueError,'cannot be replaced'):rawidentity.materialize(value,self.root/'library')

    def test_automatic_slot_replacement_preserves_old_capture_mapping(self):
        old=rawidentity.descriptor(self.dcp,'Old NC')
        self.dcp.write_bytes(profile('Same Name','new version'))
        new=rawidentity.descriptor(self.dcp,'New CC')
        rawidentity.activated([{'name':'NC','raw_profile':old}],[1],'event-one','2026-10-18T00:00:00',self.settings)
        rawidentity.activated([{'name':'CC','raw_profile':new}],[1],'event-two','2026-10-19T00:00:00',self.settings)
        registry=rawprofiles.Registry(self.root/'registry')
        self.assertEqual(registry.match(1,rawprofiles.camera_time('2026-10-18 12:00:00'))['look_id'],old['id'])
        self.assertEqual(registry.match(1,rawprofiles.camera_time('2026-10-19 12:00:00'))['look_id'],new['id'])
        self.assertEqual(len(list((self.root/'Adobe').rglob('*.dcp'))),2)

    def test_activation_receipt_is_idempotent(self):
        document={'name':'NC','raw_profile':rawidentity.descriptor(self.dcp)}
        first=rawidentity.activated([document],[1],'same-event','2026-10-18T00:00:00',self.settings)
        second=rawidentity.activated([document],[1],'same-event','2026-10-18T00:00:00',self.settings)
        self.assertEqual(first,second)
        self.assertEqual(len(rawprofiles.Registry(self.root/'registry').read()['entries']),1)

    def test_previous_source_is_recovered_only_for_matching_slot_bytes(self):
        value=rawidentity.descriptor(self.dcp,'NC');signature=dict(table_hex='1234',native_hex=None)
        rawidentity.activated([dict(name='NC',raw_profile=value,camera_signature=signature)],
            [1],'verified-film','2026-01-01T00:00:00',self.settings)
        self.assertEqual(rawidentity.previous(1,signature,self.settings),value)
        self.assertIsNone(rawidentity.previous(1,dict(table_hex='changed',native_hex=None),self.settings))

    def test_old_history_without_observed_slot_signature_is_not_guessed(self):
        value=rawidentity.descriptor(self.dcp,'NC')
        rawidentity.activated([dict(name='NC',raw_profile=value)],[1],'old-film','2026-01-01T00:00:00',self.settings)
        self.assertIsNone(rawidentity.previous(1,dict(table_hex='1234',native_hex=None),self.settings))

    def test_replacing_same_named_canonical_profile_does_not_change_old_versions(self):
        canonical=self.root/'Adobe/canonical.dcp';canonical.parent.mkdir()
        canonical.write_bytes(self.dcp.read_bytes())
        old=rawidentity.descriptor(self.dcp,'Old')
        rawidentity.activated([dict(name='Old',raw_profile=old)],[1],'old-canonical','2026-01-01T00:00:00',self.settings)
        self.dcp.write_bytes(profile('Same Name','new colors'));canonical.write_bytes(self.dcp.read_bytes())
        new=rawidentity.descriptor(self.dcp,'New')
        rawidentity.activated([dict(name='New',raw_profile=new)],[1],'new-canonical','2026-02-01T00:00:00',self.settings)
        registry=rawprofiles.Registry(self.root/'registry')
        a=registry.match(1,rawprofiles.camera_time('2026-01-02 12:00:00'))
        b=registry.match(1,rawprofiles.camera_time('2026-02-02 12:00:00'))
        self.assertEqual(a['profile'],old['adobe_profile']);self.assertEqual(b['profile'],new['adobe_profile'])
        self.assertNotEqual(a['profile'],b['profile'])

    def test_measurement_activation_suspends_previous_dcp(self):
        document={'name':'NC','raw_profile':rawidentity.descriptor(self.dcp)}
        rawidentity.activated([document],[1],'film','2026-10-18T00:00:00',self.settings)
        rawidentity.activated([None],[1],'measurement','2026-10-19T00:00:00',self.settings)
        self.assertIsNone(rawprofiles.Registry(self.root/'registry').match(1,rawprofiles.camera_time('2026-10-19 12:00:00')))

    def test_unconfirmed_write_does_not_publish_bindings(self):
        state={'phase':'NEEDS_REVIEW'}
        with patch.object(rawidentity,'activated') as publish:
            result=rawidentity.after_verified(state,lambda *a,**kw:None,'uncertain',[None],[1])
        publish.assert_not_called();self.assertEqual(result['status'],'awaiting_verified_activation')

    def test_host_sync_failure_does_not_relabel_or_retry_a_verified_write(self):
        state={'phase':'VERIFIED','raw_profile_effective_since':'2026-10-18T00:00:00'};saved=[]
        with patch.object(rawidentity,'activated',side_effect=OSError('read-only host folder')):
            result=rawidentity.after_verified(state,lambda phase,**kw:saved.append(phase),'done',[None],[1])
        self.assertEqual(result['status'],'profile_sync_failed')
        self.assertEqual(state['phase'],'VERIFIED');self.assertEqual(saved,['VERIFIED'])


if __name__=='__main__':unittest.main()
