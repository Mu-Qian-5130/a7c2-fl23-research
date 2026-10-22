"""Slot history and non-destructive XMP routing, without private photos/USB."""
from datetime import datetime
import json
from pathlib import Path
import struct
import tempfile
import unittest
from unittest.mock import patch
import xml.etree.ElementTree as ET
from looktool import rawprofiles as raw


def profile(name='NC',copyright='Test'):
    records=[(50708,b'Sony ILCE-7CM2\0'),(50936,name.encode()+b'\0'),(50942,copyright.encode()+b'\0')]
    header=bytearray(b'II'+struct.pack('<HIH',0x4352,8,len(records)))
    end=8+2+12*len(records)+4;payload=bytearray()
    for code,value in records:
        header.extend(struct.pack('<HHI',code,2,len(value)))
        if len(value)<=4:header.extend(value.ljust(4,b'\0'))
        else:header.extend(struct.pack('<I',end+len(payload)));payload.extend(value)
    return bytes(header+bytes(4)+payload)


def existing(profile_name='Old'):
    return ('<x:xmpmeta xmlns:x="adobe:ns:meta/" xmlns:rdf="'+raw.RDF+'" xmlns:crs="'+raw.CRS+'" '
        'xmlns:xmp="http://ns.adobe.com/xap/1.0/"><rdf:RDF><rdf:Description rdf:about="" '
        'crs:CameraProfile="'+profile_name+'" crs:CameraProfileDigest="old-digest" '
        'crs:Exposure2012="1.25" crs:WhiteBalance="Custom" crs:CropTop="0.1" '
        'xmp:Rating="5"><crs:ToneCurvePV2012><rdf:Seq><rdf:li>0, 2</rdf:li>'
        '<rdf:li>255, 255</rdf:li></rdf:Seq></crs:ToneCurvePV2012></rdf:Description></rdf:RDF></x:xmpmeta>').encode()


class RegistryTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name);self.registry=raw.Registry(self.root/'registry')
        self.nc=self.root/'nc.dcp';self.nc.write_bytes(profile('NC'))
        self.cc=self.root/'cc.dcp';self.cc.write_bytes(profile('CC'))

    def test_only_project_custom_markers_identify_slots(self):
        self.assertEqual([raw.slot_number(x) for x in range(249,255)],list(range(1,7)))
        for marker in (0,15,19,20,248,255,None,'Standard'):self.assertIsNone(raw.slot_number(marker))

    def test_history_uses_capture_time_when_slot_changes(self):
        self.registry.bind(1,self.nc,'2026-10-18')
        self.registry.bind(1,self.cc,'2026-10-19 12:00:00')
        self.assertEqual(self.registry.match(1,datetime(2026,10,18,20))['profile'],'NC')
        self.assertEqual(self.registry.match(1,datetime(2026,10,19,12))['profile'],'CC')

    def test_expired_latest_binding_does_not_fall_back_to_old_look(self):
        self.registry.bind(1,self.nc,'2026-10-17')
        self.registry.bind(1,self.cc,'2026-10-18','2026-10-19')
        self.assertIsNone(self.registry.match(1,datetime(2026,10,20)))

    def test_measurement_period_suspends_matching_until_new_binding(self):
        self.registry.bind(1,self.nc,'2026-10-18')
        self.registry.suspend(1,'2026-10-20 10:00:00')
        self.registry.bind(1,self.cc,'2026-10-20 16:00:00')
        self.assertIsNone(self.registry.match(1,datetime(2026,10,20,11)))
        self.assertEqual(self.registry.match(1,datetime(2026,10,20,17))['profile'],'CC')

    def test_binding_keeps_independent_source_bytes_and_is_idempotent(self):
        first=self.registry.bind(2,self.cc,'2026-10-18')
        second=self.registry.bind(2,self.cc,'2026-10-18')
        self.assertEqual(first,second)
        self.assertEqual((self.registry.root/first['dcp']).read_bytes(),self.cc.read_bytes())
        self.assertEqual(len(self.registry.read()['entries']),1)

    def test_different_profile_versions_cannot_silently_share_adobe_name(self):
        self.registry.bind(1,self.nc,'2026-10-18')
        self.nc.write_bytes(profile('NC','Other version'))
        with self.assertRaisesRegex(ValueError,'distinct DCP profile names'):
            self.registry.bind(1,self.nc,'2026-10-19')

    def test_camera_time_preserves_sony_millisecond_padding(self):
        self.assertEqual(raw.camera_time('2026:10:18 19:00:00',68).microsecond,68000)
        self.assertEqual(raw.camera_time('2026:10:18 19:00:00','068').microsecond,68000)
        with self.assertRaises(ValueError):raw.camera_time('2026-10-18T19:00:00+08:00')

    def test_plan_leaves_native_looks_and_unknown_history_unassigned(self):
        self.registry.bind(1,self.nc,'2026-10-18')
        rows=[dict(SourceFile='native.ARW',Model='ILCE-7CM2',CreativeStyle=19),
              dict(SourceFile='nc.ARW',Model='ILCE-7CM2',CreativeStyle=249,DateTimeOriginal='2026:10:18 19:00:00'),
              dict(SourceFile='unknown.ARW',Model='ILCE-7CM2',CreativeStyle=250,DateTimeOriginal='2026:10:18 19:00:00'),
              dict(SourceFile='no-time.ARW',Model='ILCE-7CM2',CreativeStyle=249),
              dict(SourceFile='other.ARW',Model='ILCE-7M4',CreativeStyle=249)]
        with patch.object(raw,'metadata',return_value=rows):result=raw.plan([],self.registry,'unused')
        self.assertEqual([row['action'] for row in result],['native','profile','skip','skip','skip'])
        self.assertEqual(result[1]['profile'],'NC')

    def test_metadata_uses_utf8_stdin_file_list(self):
        result=type('Result',(),dict(returncode=0,stdout='[]',stderr=''))()
        with patch.object(raw.subprocess,'run',return_value=result) as run:
            raw.metadata([Path('D:/照片/one.ARW')],'exiftool')
        self.assertIn(str(Path('D:/照片/one.ARW')),run.call_args.kwargs['input'])
        self.assertEqual(run.call_args.args[0][-2:],['-@','-'])

    def test_install_reuses_existing_exact_dcp_without_overwriting(self):
        row=self.registry.bind(1,self.nc,'2026-10-18')
        destination=self.root/'Adobe';destination.mkdir();(destination/'source.dcp').write_bytes(self.nc.read_bytes())
        reports=raw.install_profiles([dict(action='profile',profile='NC',dcp=str(self.registry.root/row['dcp']))],destination)
        self.assertEqual(reports[0]['status'],'already_installed')
        self.assertEqual(len(list(destination.rglob('*.dcp'))),1)


class XMPTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.raw=Path(self.temp.name)/'test.ARW';self.raw.write_bytes(b'original RAW samples')

    def test_new_sidecar_assigns_only_profile_and_as_shot_defaults(self):
        result=raw.merge_xmp(self.raw,'NC')
        root=ET.parse(result['file']);node=next(root.iter('{'+raw.RDF+'}Description'))
        self.assertEqual(node.get('{'+raw.CRS+'}CameraProfile'),'NC')
        self.assertEqual(node.get('{'+raw.CRS+'}WhiteBalance'),'As Shot')
        self.assertIsNone(node.get('{'+raw.CRS+'}Exposure2012'))
        self.assertEqual(self.raw.read_bytes(),b'original RAW samples')

    def test_existing_edits_and_rating_survive_profile_replacement(self):
        sidecar=self.raw.with_suffix('.xmp');old=existing();sidecar.write_bytes(old)
        result=raw.merge_xmp(self.raw,'NC',True)
        root=ET.parse(sidecar);node=next(root.iter('{'+raw.RDF+'}Description'))
        self.assertEqual(node.get('{'+raw.CRS+'}CameraProfile'),'NC')
        self.assertEqual(node.get('{'+raw.CRS+'}Exposure2012'),'1.25')
        self.assertEqual(node.get('{'+raw.CRS+'}CropTop'),'0.1')
        self.assertEqual(node.get('{http://ns.adobe.com/xap/1.0/}Rating'),'5')
        self.assertIsNotNone(node.find('{'+raw.CRS+'}ToneCurvePV2012'))
        self.assertIsNone(node.get('{'+raw.CRS+'}CameraProfileDigest'))
        self.assertEqual(Path(result['backup']).read_bytes(),old)

    def test_existing_different_profile_is_preserved_by_default(self):
        sidecar=self.raw.with_suffix('.xmp');old=existing();sidecar.write_bytes(old)
        result=raw.merge_xmp(self.raw,'NC')
        self.assertEqual(result['status'],'profile_conflict')
        self.assertEqual(sidecar.read_bytes(),old)

    def test_repeat_is_idempotent_and_keeps_first_backup(self):
        sidecar=self.raw.with_suffix('.xmp');old=existing();sidecar.write_bytes(old)
        result=raw.merge_xmp(self.raw,'NC',True);data=sidecar.read_bytes()
        self.assertEqual(raw.merge_xmp(self.raw,'NC')['status'],'already_prepared')
        self.assertEqual(data,sidecar.read_bytes())
        raw.merge_xmp(self.raw,'CC',True)
        self.assertEqual(Path(result['backup']).read_bytes(),old)

    def test_broken_xmp_stops_without_changing_any_file(self):
        sidecar=self.raw.with_suffix('.xmp');sidecar.write_bytes(b'<broken')
        with self.assertRaises(ET.ParseError):raw.merge_xmp(self.raw,'NC',True)
        self.assertEqual(sidecar.read_bytes(),b'<broken')

    def test_uppercase_sidecar_is_merged_instead_of_creating_another(self):
        sidecar=self.raw.with_suffix('.XMP');sidecar.write_bytes(existing())
        result=raw.merge_xmp(self.raw,'NC',True)
        self.assertEqual(Path(result['file']),sidecar)


if __name__=='__main__':unittest.main()
