"""Location of the bundled, paired DCP/A7Look files; no conversion or USB."""
import sys
from pathlib import Path
from .paths import ROOT

def location():
    bundled=ROOT/'desktop-assets/profile-library-v1'
    if getattr(sys,'frozen',False) and sys.platform=='win32':
        external=Path(sys.executable).parent/'Profiles'
        if (external/'catalog.json').is_file():return external
        if (bundled/'catalog.json').is_file():return bundled
        return external
    return bundled
