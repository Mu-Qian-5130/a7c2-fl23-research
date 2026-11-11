"""Bundled six-look selection, resolved before opening a device.

The actual A7Look/DCP assets are distribution attachments, not MIT source.
No fitting or downloading occurs during installation.
"""
import copy
from pathlib import Path
from .paths import ROOT

PACK = 'default-six-v1'
from looktool.looklabels import defaults
NAMES = tuple(row['name'] for row in defaults())
MENU_ICON_LABELS = tuple(row['icon_text'] for row in defaults())
SUMMARY = ' · '.join('%d %s' % (slot,label) for slot,label in enumerate(MENU_ICON_LABELS,1))


def refresh_assets(root=None):
    """Normalize imported built-ins and keep explicit icon-bearing companions."""
    import json
    from looktool import lookfile,looklabels
    folder=Path(root or ROOT)/'desktop-assets/presets'/PACK
    updated=[]
    for slot,row in enumerate(defaults(),1):
        path=folder/('slot%d.a7look'%slot)
        document=lookfile.read(path)
        if looklabels.full_name(document['name'])!=row['name']:
            raise ValueError('Built-in slot identity differs: '+str(path))
        plain=looklabels.relabel(document,include_icon=False)
        menu=looklabels.relabel(document,include_icon=True)
        for target,value in [(path,plain),(folder/'MenuIcons'/path.name,menu)]:
            target.parent.mkdir(parents=True,exist_ok=True)
            target.write_text(json.dumps(value,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
        updated.append(dict(slot=slot,name=row['name'],icon_text=row['icon_text']))
    return updated


def menu_examples(destination):
    """Save portable icon-bearing copies without changing the shipped looks."""
    from looktool import iconfile
    destination=Path(destination);destination.mkdir(parents=True,exist_ok=False)
    rows=[]
    for row,label in zip(catalog(),MENU_ICON_LABELS):
        target=destination/('slot%d.a7look'%row['slot'])
        iconfile.save_copy(row['path'],target,iconfile.from_text(label))
        rows.append(dict(row,path=str(target)))
    return rows


def catalog():
    """Default file choices without disk access or validation during UI startup."""
    return [dict(slot=slot, path=str(ROOT / 'desktop-assets/presets' / PACK / ('slot%d.a7look' % slot)), name=name)
            for slot, name in enumerate(NAMES, 1)]


def resolve(options):
    """Expand an explicit pack choice; ordinary selected-slot jobs stay intact."""
    options = copy.deepcopy(options)
    pack = options.get('preset_pack')
    if not pack:
        return options
    if pack != PACK:
        raise ValueError('Unknown built-in look pack: ' + str(pack))
    if options.get('looks'):
        raise ValueError('Choose the built-in six looks or custom files, not both')
    from looktool import lookfile
    rows = []
    for row in catalog():
        slot, name, path = row['slot'], row['name'], Path(row['path'])
        if not path.is_file():
            raise ValueError('内置六款外观文件缺失，请使用完整工具包；尚未连接相机：' + str(path))
        doc = lookfile.read(path)
        lookfile.writer_document(doc)
        if doc['name'] != name or not (doc.get('native_photo')or doc.get('edit_native')):
            raise ValueError('内置外观名称／照片阶段不符：' + str(path))
        rows.append(dict(slot=slot, path=str(path), name=name))
    options['looks'] = rows
    return options
