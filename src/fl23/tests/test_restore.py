"""回復原版的前置條件：跨版本相容，但窗口外一位元組都不許動。

用樁 Session 模擬機身讀寫，全程離線、不接觸相機。原始單元用全零假體，
只驗證判準與流程分支，不驗證實際色彩。
"""
from pathlib import Path
import sys
import tempfile
import unittest
from types import SimpleNamespace
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import app
import core

ORIGINAL_01=bytes(8192)
ORIGINAL_0D=bytes(28672)
FULL_01,FULL_0D=core.merge_colors(ORIGINAL_01,ORIGINAL_0D)

class Camera:
    def getBackupPresetData(self,live):return b'RAW'
    def readBackup(self,key):return self.session.ap[key]
    def saveBackup(self,key):self.session.saved.append(hex(key))

class Session:
    """最小可用的機身替身；CP／AP 存在記憶體裡。"""
    healthy=True
    def __init__(self,cp,ap):
        self.cp=dict(cp);self.ap=dict(ap);self.writes=[];self.saved=[]
        self.camera=Camera();self.camera.session=self
    def call(self,fn,*args):return fn(*args)
    def cp_read(self,key):return self.cp[key]
    def cp_write(self,key,data):self.writes.append(('cp',hex(key)));self.cp[key]=data
    def ap_write(self,key,data):self.writes.append(('ap',hex(key)));self.ap[key]=data

class RestoreGuardTests(unittest.TestCase):
    def setUp(self):
        self.saved_records=core.backup_records
        def records(raw):
            session=self.current
            return [dict((k,SimpleNamespace(data=v,attr=0)) for k,v in session.ap.items()),
                    dict((k,SimpleNamespace(data=v,attr=0)) for k,v in session.cp.items())]
        core.backup_records=records
        self.current=None
    def tearDown(self):
        core.backup_records=self.saved_records
    def workspace(self):
        folder=Path(tempfile.mkdtemp())
        (folder/'original').mkdir()
        (folder/'original'/'unit-02a40001.bin').write_bytes(ORIGINAL_01)
        (folder/'original'/'unit-02a4000d.bin').write_bytes(ORIGINAL_0D)
        job=app.Job(folder)
        job.state={'format':1,'model':core.MODEL,'backup_files':{},'journal':[]}
        return job
    def previous_release(self):
        """模擬 0.2.0 的產物：只填每端點的槽 0，其餘十五槽維持原版。"""
        unit01=bytearray(ORIGINAL_01);unit0d=bytearray(ORIGINAL_0D)
        for parameter,slot in core.COLOUR_SLOTS:
            unit01[0x1200+parameter]=slot;unit0d[0x196+parameter]=slot
            chroma=0x1250+slot*64
            unit01[chroma:chroma+64]=FULL_01[chroma:chroma+64]
            matrix=0x1e0+slot*768
            for endpoint in range(3):
                start=matrix+endpoint*192
                unit0d[start:start+12]=FULL_0D[start:start+12]
        return bytes(unit01),bytes(unit0d)
    def restore(self,unit01,unit0d):
        session=Session({core.CP_KEYS[0]:unit01,core.CP_KEYS[1]:unit0d},
                        {core.AP_KEYS[0]:b'\x0a',core.AP_KEYS[1]:b'\x0b'})
        self.current=session
        self.workspace().settings(session,True)
        return session
    def test_restore_accepts_record_written_by_another_release(self):
        unit01,unit0d=self.previous_release()
        session=self.restore(unit01,unit0d)
        self.assertEqual(session.cp[core.CP_KEYS[0]],ORIGINAL_01)
        self.assertEqual(session.cp[core.CP_KEYS[1]],ORIGINAL_0D)
        self.assertEqual([session.ap[k] for k in core.AP_KEYS],[b'\0',b'\0'])
    def test_restore_accepts_current_release(self):
        session=self.restore(FULL_01,FULL_0D)
        self.assertEqual(session.cp[core.CP_KEYS[1]],ORIGINAL_0D)
    def test_restore_rejects_change_outside_colour_window(self):
        unit01,unit0d=self.previous_release()
        alien=bytearray(unit0d);alien[0x400]^=0xFF
        with self.assertRaises(ValueError) as caught:self.restore(unit01,bytes(alien))
        self.assertIn('0x2a4000d',str(caught.exception))
    def test_restore_rejects_partial_unit_length(self):
        unit01,unit0d=self.previous_release()
        with self.assertRaises(ValueError):self.restore(unit01[:-1],unit0d)

if __name__=='__main__':unittest.main()
