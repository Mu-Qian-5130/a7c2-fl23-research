"""FL2／FL3 色彩記錄的離線測試：數值來自 A7R V 專案公布值，不接觸相機。"""
import json
from pathlib import Path
import struct
import sys
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import core
import fl23_color

BASE=Path(__file__).resolve().parents[1]

# 0.5.0 交付記錄指紋；任何數值變動都應同時更新移植文件。
# 色度與 0.4.0 相同（FX2 照片 bank 的差分係數本來就一致），矩陣改為逐槽值。
RECORDS={
 55:{'slot':23,
     'chroma':'32767d91a81ff06298add694cc951ef01f86ef02317ff89bbf8c1c8d7bc8f008',
     'matrix':'753e57f9c4edaf26dd957987a2f8f23c33504ee50dab9eb65fa413cd2c25ead4'},
 56:{'slot':25,
     'chroma':'45a1dfdcb23334ebae46b8e1ce7e31efc76cdb9cd3c864ec91c9bda8005193ae',
     'matrix':'a5b7d763d95fc0061124f18765337d1e4683e83f11a25bd5c186afa75f271cc3'}}
# 0.4.0 的色度指紋，用來證明本版沒有動色度。
CHROMA_UNCHANGED_SINCE_040={
 55:'32767d91a81ff06298add694cc951ef01f86ef02317ff89bbf8c1c8d7bc8f008',
 56:'45a1dfdcb23334ebae46b8e1ce7e31efc76cdb9cd3c864ec91c9bda8005193ae'}

class ColourTests(unittest.TestCase):
    def rows(self):return {r['parameter']:r for r in fl23_color.read_json(fl23_color.ASSETS/'colors.json')}
    def test_reference_cc1_round_trip(self):
        for look in fl23_color.reference()['looks']:
            raw=[look['raw']['0x7842'],look['raw']['0x7844'],look['raw']['0x7845']]
            self.assertEqual(fl23_color.cc1_from_raw(raw),look['cc1_int16'])
            self.assertEqual(fl23_color.cc1_to_raw(look['cc1_int16']),raw)
    def test_reference_matrix_round_trip(self):
        for look in fl23_color.reference()['looks']:
            self.assertEqual(fl23_color.matrix_from_ab(look['matrix_ab']),look['matrix_3x3'])
            self.assertEqual(fl23_color.ab_from_matrix(look['matrix_3x3']),look['matrix_ab'])
    def test_published_matrices_keep_row_sum_1024(self):
        for look in fl23_color.reference()['looks']:
            self.assertTrue(all(sum(row)==1024 for row in look['matrix_3x3']))
    def test_assets_carry_r5_values(self):
        rows,looks=self.rows(),fl23_color.reference_by_parameter()
        for parameter,look in looks.items():
            chroma=bytes.fromhex(rows[parameter]['chroma']);matrix=bytes.fromhex(rows[parameter]['matrix'])
            self.assertEqual(chroma,fl23_color.target_chroma(look))
            self.assertEqual(matrix,fl23_color.target_matrix(look,matrix))
            self.assertEqual(chroma[48:],bytes(16))
    def test_every_slot_matches_the_donor(self):
        """0.5.0：48 槽逐槽等於 FX2 供體值，不再要求端點內部統一。"""
        rows=self.rows()
        for parameter,row in rows.items():
            matrix=bytes.fromhex(row['matrix'])
            matched,missing=fl23_color.counts_toward_donor(matrix,parameter)
            self.assertEqual(matched,48)
            self.assertEqual(missing,[])
            self.assertEqual(matrix,fl23_color.donor_matrix(parameter))
            # 每個端點內都應有多個不同槽值（原生外觀是 15～16 個）
            for count in fl23_color.distinct_slots(matrix):
                self.assertGreaterEqual(count,15)
    def test_slots_are_not_all_the_endpoint_primary(self):
        """0.4.x 把端點主槽鋪滿 16 槽；0.5.0 必須保留逐槽差異。"""
        rows=self.rows()
        matrix=bytes.fromhex(rows[55]['matrix'])
        blocks=[fl23_color.slot0(b) for b in fl23_color.endpoints(matrix)]
        self.assertNotEqual(blocks[0],blocks[1])
        self.assertNotEqual(blocks[2],blocks[1])
        self.assertFalse(fl23_color.uniform_all_slots(matrix))
        self.assertFalse(fl23_color.uniform_primary(matrix))
        for block in fl23_color.endpoints(matrix):
            self.assertFalse(fl23_color.uniform_endpoint(block))
    def test_donor_slot0_equals_the_published_endpoint_value(self):
        """供體 A1 槽 0 必須等於 R5 公布的六係數：兩份獨立來源互相印證。"""
        ref=fl23_color.reference_by_parameter()
        for parameter,look in ref.items():
            slots=fl23_color.donor_by_parameter()[parameter]['matrix_slots']
            for name in fl23_color.ENDPOINT_NAMES:
                self.assertEqual(slots[name][0],list(look['endpoint_matrix_ab'][name]),
                                 (parameter,name))
            self.assertEqual(slots['A1'][0],list(look['matrix_ab']))
    def test_donor_chroma_equals_the_published_cc1(self):
        """供體 CC1 差分係數必須等於 R5 公布的機內值。"""
        ref=fl23_color.reference_by_parameter()
        for parameter,look in ref.items():
            self.assertEqual(fl23_color.donor_chroma(parameter),fl23_color.target_chroma(look))
    def test_chroma_is_unchanged_since_040(self):
        for parameter,expected in CHROMA_UNCHANGED_SINCE_040.items():
            self.assertEqual(fl23_color.sha(bytes.fromhex(self.rows()[parameter]['chroma'])),
                             expected)
    def test_every_slot_expands_to_row_sum_1024(self):
        for parameter in self.rows():
            matrix=fl23_color.donor_matrix(parameter)
            for index in range(0,576,12):
                ab=struct.unpack('<6h',matrix[index:index+12])
                for row in fl23_color.matrix_from_ab(ab):
                    self.assertEqual(sum(row),1024)
    def test_core_rejects_any_byte_that_is_not_the_donor_value(self):
        """任何偏離供體目標的槽都不得進入安裝流程（含 0.2.0 的混合填充）。"""
        row=dict(self.rows()[55])
        matrix=bytearray.fromhex(row['matrix'])
        matrix[12:24]=struct.pack('<6h',155,-310,113,154,176,193)
        row['matrix']=bytes(matrix).hex()
        with self.assertRaises(ValueError):core.colour_record(row)
        row=dict(self.rows()[55])
        matrix=bytearray.fromhex(row['matrix']);matrix[300]^=0x01
        row['matrix']=bytes(matrix).hex()
        with self.assertRaises(ValueError):core.colour_record(row)
    def test_port_defaults_to_per_slot_fill(self):
        rows,looks=self.rows(),fl23_color.reference_by_parameter()
        for parameter,look in looks.items():
            matrix=bytes.fromhex(rows[parameter]['matrix'])
            want=fl23_color.donor_matrix(parameter)
            self.assertEqual(fl23_color.target_matrix(look,matrix),want)
            self.assertEqual(len(want),576)
    def test_endpoint_fill_still_reproduces_0_4_0(self):
        """--fill endpoints 仍可重建 0.4.0 的記錄，供回退比對。"""
        rows,looks=self.rows(),fl23_color.reference_by_parameter()
        for parameter,look in looks.items():
            want=b''.join(struct.pack('<6h',*ab)*16 for ab in fl23_color.endpoint_ab(look))
            self.assertEqual(fl23_color.target_matrix(look,bytes(576),'endpoints'),want)
            self.assertNotEqual(want,fl23_color.donor_matrix(parameter))
    def test_unified_fill_reproduces_0_3_x(self):
        """--fill unified 仍可重建 0.3.x 的三端點同值記錄，供回退比對。"""
        look=fl23_color.reference_by_parameter()[55]
        unified=fl23_color.target_matrix(look,bytes(576),'unified')
        self.assertEqual(unified,struct.pack('<6h',*look['matrix_ab'])*48)
        self.assertTrue(fl23_color.uniform_all_slots(unified))
        self.assertNotEqual(unified,fl23_color.target_matrix(look,bytes(576)))
    def test_record_fingerprints(self):
        rows=self.rows()
        for parameter,expected in RECORDS.items():
            self.assertEqual(rows[parameter]['slot'],expected['slot'])
            self.assertEqual(fl23_color.sha(bytes.fromhex(rows[parameter]['chroma'])),expected['chroma'])
            self.assertEqual(fl23_color.sha(bytes.fromhex(rows[parameter]['matrix'])),expected['matrix'])
    def test_manifest_lists_reference_asset(self):
        manifest=fl23_color.read_json(fl23_color.ASSETS/'manifest.json')
        self.assertEqual(manifest['release'],'0.6.0-preview')
        self.assertEqual(set(manifest['files']),set(fl23_color.ASSET_NAMES))
        self.assertIn('ILCE-FX2',manifest['colour_donor'])
        self.assertIn('48 block13 slots',manifest['colour_fill'])
    def test_core_accepts_shipped_records(self):
        for row in self.rows().values():
            chroma,matrix=core.colour_record(row)
            self.assertEqual((len(chroma),len(matrix)),(64,576))
    def test_core_rejects_a_record_outside_the_donor_target(self):
        row=dict(self.rows()[55])
        matrix=bytearray.fromhex(row['matrix']);matrix[192:204]=struct.pack('<6h',1,2,3,4,5,6)
        row['matrix']=bytes(matrix).hex()
        with self.assertRaises(ValueError):core.colour_record(row)
    def test_core_rejects_nonzero_chroma_tail(self):
        row=dict(self.rows()[55])
        chroma=bytearray.fromhex(row['chroma']);chroma[50]=1
        row['chroma']=bytes(chroma).hex()
        with self.assertRaises(ValueError):core.colour_record(row)
    def test_merge_writes_reference_bytes_only_to_new_slots(self):
        unit01=bytearray(8192);unit0d=bytearray(28672)
        unit01[0x100:0x108]=b'AAAAAAAA';unit0d[0x80:0x88]=b'BBBBBBBB'
        unit01[0x1250:0x1290]=bytes([9])*64;unit0d[0x1e0:0x1e0+576]=bytes([9])*576
        a,b=core.merge_colors(bytes(unit01),bytes(unit0d))
        self.assertEqual(a[0x100:0x108],b'AAAAAAAA');self.assertEqual(b[0x80:0x88],b'BBBBBBBB')
        self.assertEqual(a[0x1250:0x1290],bytes([9])*64);self.assertEqual(b[0x1e0:0x1e0+576],bytes([9])*576)
        for row in self.rows().values():
            slot=row['slot']
            self.assertEqual(a[0x1200+row['parameter']],slot);self.assertEqual(b[0x196+row['parameter']],slot)
            self.assertEqual(a[0x1250+slot*64:0x1250+slot*64+64],bytes.fromhex(row['chroma']))
            self.assertEqual(b[0x1e0+slot*768:0x1e0+slot*768+576],bytes.fromhex(row['matrix']))
            self.assertEqual(b[0x1e0+slot*768+576:0x1e0+slot*768+768],bytes(192))
    def test_colour_write_spans_cover_every_merged_byte(self):
        """merge_colors 的實際改動必須全部落在 colour_write_spans() 之內。"""
        unit01=bytes(8192);unit0d=bytes(28672)
        a,b=core.merge_colors(unit01,unit0d)
        spans=core.colour_write_spans()
        for index,(current,original) in enumerate([(a,unit01),(b,unit0d)]):
            touched={offset for offset in range(len(original)) if current[offset]!=original[offset]}
            beyond=[offset for offset in touched
                    if not any(start<=offset<end for start,end in spans[index])]
            self.assertEqual(beyond,[])
            self.assertEqual(core.matches_outside_colour(current,original,index),True)
            self.assertIsNone(core.colour_window_diff(current,original,index))
    def test_restore_accepts_output_of_an_older_package(self):
        """0.2.0 只填槽 0；回復流程仍應認得並允許覆寫回原版。"""
        unit0d=bytearray(28672);unit01=bytearray(8192)
        _,installed=core.merge_colors(bytes(unit01),bytes(unit0d))
        older=bytearray(unit0d)
        for parameter,slot in core.COLOUR_SLOTS:
            older[0x196+parameter]=slot
            base=0x1e0+slot*768
            for endpoint in range(3):
                # 只保留每個端點的主槽，其餘十五槽退回原版的空值。
                older[base+endpoint*192+12:base+(endpoint+1)*192]=bytes(180)
        self.assertNotEqual(bytes(older),installed)
        self.assertTrue(core.matches_outside_colour(bytes(older),bytes(unit0d),1))
        self.assertIsNone(core.colour_window_diff(bytes(older),bytes(unit0d),1))
    def test_restore_rejects_changes_outside_the_colour_window(self):
        unit0d=bytearray(28672);unit01=bytearray(8192)
        _,installed=core.merge_colors(bytes(unit01),bytes(unit0d))
        alien=bytearray(installed);alien[0x400]^=0xFF
        self.assertFalse(core.matches_outside_colour(bytes(alien),bytes(unit0d),1))
        self.assertEqual(core.colour_window_diff(bytes(alien),bytes(unit0d),1),0x400)
    def test_inspect_matches_reference(self):
        for row in fl23_color.inspect()['records']:
            self.assertFalse(any(row['endpoint_uniform']))
            self.assertFalse(row['all_slots_uniform'])
            self.assertEqual(row['slots_matching_reference'],48)
            self.assertEqual(row['slots_missing_reference'],[])
            self.assertTrue(row['chroma_matches_r5']);self.assertTrue(row['chroma_tail_zero'])
            for count in row['distinct_slots_per_endpoint']:
                self.assertGreaterEqual(count,15)
    def test_endpoint_reference_keeps_row_sum_1024(self):
        for look in fl23_color.reference()['looks']:
            for name,matrix in look['endpoint_matrix_3x3'].items():
                self.assertTrue(all(sum(row)==1024 for row in matrix),(look['look'],name))
                self.assertEqual(fl23_color.matrix_from_ab(look['endpoint_matrix_ab'][name]),matrix)
    def test_a2_endpoint_shifts_green_further_than_a1(self):
        """A2 端點把綠色往高色相角推得比 A1 多；紅橙幾乎不變。"""
        look=fl23_color.reference_by_parameter()[55]
        ab=look['endpoint_matrix_ab']
        for hue in (125,135,150):
            a1,_=fl23_color.hue_shift(ab['A1'],hue)
            a2,_=fl23_color.hue_shift(ab['A2'],hue)
            self.assertGreater(a2,a1+2)
        for hue in (30,45):
            self.assertLess(abs(fl23_color.hue_shift(ab['A2'],hue)[0]
                                -fl23_color.hue_shift(ab['A1'],hue)[0]),2.5)
    def test_hue_report_covers_every_look_and_endpoint(self):
        report=fl23_color.hue_report()
        self.assertEqual([r['look'] for r in report['looks']],['FL2','FL3'])
        for row in report['looks']:
            self.assertEqual([e['endpoint'] for e in row['endpoints']],['B','A1','A2'])
            self.assertEqual(len(row['endpoints'][0]['samples']),360//15)

if __name__=='__main__':unittest.main()
