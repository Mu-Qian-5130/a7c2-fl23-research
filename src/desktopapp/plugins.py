"""Install the existing RAW-profile plugin with this app as its worker."""
import json
import os
from pathlib import Path
import shutil
import sys
import uuid
from .paths import ROOT, data_root, write_json


def install(arguments):
    from .exiftool import ensure,persist_windows
    tool = ensure(arguments.get('exiftool'))
    if sys.platform == 'win32':
        tool = persist_windows(tool)
    if not getattr(sys, 'frozen', False):
        from looktool.rawauto import install as original_install
        return original_install(tool, root=Path(arguments.get('data_root') or data_root() / 'raw-profiles'),
                                copy_exiftool=False)
    modules = (Path(os.environ['APPDATA']) / 'Adobe/Lightroom/Modules' if sys.platform == 'win32'
               else Path.home() / 'Library/Application Support/Adobe/Lightroom/Modules')
    plugin = modules / 'A7LookAuto.lrplugin'
    plugin.mkdir(parents=True, exist_ok=True)
    for source in (ROOT / 'plugins/A7LookAuto.lrplugin').glob('*.lua'):
        shutil.copy2(source, plugin / source.name)
    root = Path(arguments.get('data_root') or data_root() / 'raw-profiles')
    root.mkdir(parents=True, exist_ok=True)
    settings = dict(schema='a7c2-LR-auto-settings/1', library=str(root / 'library'),
                    registry=str(root / 'registry'),
                    adobe_profiles=str(Path(os.environ['APPDATA']) / 'Adobe/CameraRaw/CameraProfiles'
                       if sys.platform == 'win32' else Path.home() / 'Library/Application Support/Adobe/CameraRaw/CameraProfiles'),
                    python=sys.executable, exiftool=str(tool), worker=sys.executable,
                    worker_prefix=['--raw-profile-worker'], work_root=str(root / 'jobs'),
                    install_id=uuid.uuid4().hex, interval=5,
                    log=str(root / 'plugin.log'), status=str(root / 'plugin-status.txt'))
    write_json(root / 'settings.json', settings)
    write_json(root / 'plugin-settings.json', settings)
    fields = {'settings': str(root / 'plugin-settings.json'), 'python': sys.executable,
              'worker': sys.executable, 'worker_prefix': '--raw-profile-worker',
              'work_root': settings['work_root'], 'interval': 5,
              'install_id': settings['install_id'], 'log': settings['log'], 'status': settings['status']}
    lines = ['return {'] + ['    ' + key + ' = ' + (str(value) if isinstance(value, int)
               else json.dumps(value, ensure_ascii=False)) + ',' for key, value in fields.items()] + ['}']
    (plugin / 'Config.lua').write_text('\n'.join(lines) + '\n', encoding='utf-8')
    return {'plugin': str(plugin), 'settings': str(root / 'settings.json'),
            'next_step': 'Enable A7Look Auto Profiles once in Lightroom Plug-in Manager.'}
