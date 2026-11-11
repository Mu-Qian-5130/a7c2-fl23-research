"""Publish the four existing landscape/portrait banks from their own live baseline."""
import hashlib
from . import menuicons

NAMES = tuple(f'image_{group:02d}_{orientation}_IPSX.uxc'
              for orientation in ('32', '23') for group in (0, 1))


def replace(files, icons):
    menuicons.vertical_modules()
    from verticaltool import nativeportrait
    if not icons:
        return dict(files)
    if any(name not in files for name in NAMES):
        raise ValueError('本地基线缺少横竖图标资源；请使用新版固件构建的完整 baseline')
    result = dict(files)
    for group in (0, 1):
        name=NAMES[group]
        result[name]=menuicons.replace(files[name],icons,group=group,all_views=True)[0]
    for group in (0, 1):
        name=NAMES[group+2];source=files[name]
        if not nativeportrait.owned(source):
            raise ValueError('竖屏图标资源没有完整的本项目归属记录')
        changed=menuicons.replace(source,icons,group=group,all_views=True)[0]
        origin=hashlib.sha256(result[NAMES[group]]).digest()
        if changed!=source or origin!=source[-72:-40]:
            changed += origin+hashlib.sha256(changed).digest()+nativeportrait.MAGIC
        if not nativeportrait.owned(changed):
            raise ValueError('竖屏图标发布摘要核对失败')
        result[name]=changed
    return result
