"""Actual writer completion paths publish host metadata only after verification."""
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from looktool import photolab,lookfile,devicejob,rawidentity
from test_lookfile import MemoryCamera,PreparedJob
from test_rawprofiles import profile


class FakeCamera:
    identity={'model':'ILCE-7CM2'}
    def __enter__(self):return self
    def __exit__(self,*args):pass


class HookTests(unittest.TestCase):
    def lab(self):
        lab=object.__new__(photolab.Lab)
        lab.state=dict(phase='AWAITING_RELOAD',installed_case='compiled-six',trial='test-trial',
                       identity=FakeCamera.identity,boot_before='before',
                       installed_documents=[{'name':str(i)} for i in range(6)])
        lab.load=lambda:None;lab.original=lambda:{};lab.target=lambda *a:({},{});
        lab.factory=lambda *a:FakeCamera();lab.native=lambda *a:{}
        lab.trial=lambda:None
        lab.check_runtime=lambda *a:None;lab.boot_id=lambda *a:'after'
        lab.save=lambda phase,**kw:lab.state.update(phase=phase,**kw)
        return lab

    def test_loaded_but_not_accepted_lab_does_not_publish(self):
        lab=self.lab()
        with patch.object(photolab.checkpoint,'same_body'),patch.object(rawidentity,'after_verified') as publish:
            photolab.Lab.verify.__wrapped__(lab,False,full_readback=False)
        self.assertEqual(lab.state['phase'],'LOADED');publish.assert_not_called()

    def test_verified_lab_passes_exact_six_documents_to_automatic_publisher(self):
        lab=self.lab()
        with patch.object(photolab.checkpoint,'same_body'),patch.object(rawidentity,'after_verified') as publish:
            photolab.Lab.verify.__wrapped__(lab,True,full_readback=False)
        self.assertEqual(lab.state['phase'],'VERIFIED')
        self.assertEqual(publish.call_args.args[2],'test-trial')
        self.assertEqual(publish.call_args.args[3],lab.state['installed_documents'])
        self.assertEqual(publish.call_args.args[4],[1,2,3,4,5,6])

    def test_compiled_source_DCP_is_frozen_without_refitting_or_changing_table(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);dcp=root/'source.dcp';dcp.write_bytes(profile('NC'))
            descriptor=rawidentity.descriptor(dcp,'NC');raw=bytes(1215)
            source=root/'source.a7look'
            lookfile.write(source,'NC',raw,method='test',attribution='test',raw_profile=descriptor)
            job=PreparedJob(root/'job',factory=MemoryCamera())
            with patch.object(devicejob.native,'fit_reference',side_effect=AssertionError('Refit forbidden')):
                state=job.create(source,'NC',1,None,root/'backup')
            self.assertEqual(state['raw_profile_binding'],descriptor)
            self.assertEqual(job.received,raw)


if __name__=='__main__':unittest.main()
