"""Compatibility import; implementation lives in desktopapp.platforms."""
import sys
from .platforms import macos_authorization as _implementation
sys.modules[__name__] = _implementation
