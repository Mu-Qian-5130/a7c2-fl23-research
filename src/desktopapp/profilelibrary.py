"""Location of the bundled, paired DCP/A7Look files; no conversion or USB."""
import sys
from pathlib import Path
from .paths import ROOT

def location():
    if getattr(sys,'frozen',False) and sys.platform=='win32':
        return Path(sys.executable).parent/'Profiles'
    return ROOT/'desktop-assets/profile-library-v1'
