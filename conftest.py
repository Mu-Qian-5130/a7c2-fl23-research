"""Automated tests must never access a physical camera."""
import pytest
from pathlib import Path
import sys

sys.path.insert(0,str(Path(__file__).resolve().parent/'src/shutter_sound'))


@pytest.fixture(autouse=True)
def no_physical_usb(monkeypatch):
    import usb.core
    def forbidden(*args,**kwargs):
        raise AssertionError('Physical USB enumeration is forbidden in offline tests; supply a fake camera')
    monkeypatch.setattr(usb.core,'find',forbidden)
