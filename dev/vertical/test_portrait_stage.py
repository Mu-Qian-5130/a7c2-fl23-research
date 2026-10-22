"""Prior portrait artifacts are accounted from current bytes, without replay."""
from pathlib import Path
import struct
import sys
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'src/vertical'))
from verticaltool import portraitstage,portraitworker


def stage(files):
    obj=object.__new__(portraitstage.Stage)
    obj.owner=SimpleNamespace(raw=MagicMock(),record=MagicMock())
    obj.camera=SimpleNamespace(temp_read=lambda name,missing:files.get(name),temp_remove=lambda name:files.pop(name,None))
    return obj


def test_own_completed_or_failed_artifacts_are_archived_without_old_job():
    raw=struct.pack(portraitworker.FORMAT,portraitworker.MAGIC,1,1,4,0,1,0,-5,0,3,1,0)
    blob=b'\x7fELFportrait.request portrait.result image_00_32_IPSX.uxc'
    request=struct.pack('<8sII',portraitworker.MAGIC,1,0)
    files={'portrait.result':raw,'portrait.staged.so':blob,'portrait.request':request}
    obj=stage(files);obj.reconcile()
    assert not files and obj.owner.raw.call_count==3
    obj.owner.record.assert_called_once()


def test_another_loader_is_preserved():
    blob=b'\x7fELFportrait.request portrait.result image_00_32_IPSX.uxc'
    files={'portrait.staged.so':blob,'libJit.so':b'other active worker'}
    obj=stage(files)
    with pytest.raises(ValueError,match='Another native operation'):obj.reconcile()
    assert len(files)==2
