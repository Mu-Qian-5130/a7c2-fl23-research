"""Compatibility import; implementation lives in desktopapp.platforms."""
import sys
from .platforms import usb_drivers as _implementation
sys.modules[__name__] = _implementation
