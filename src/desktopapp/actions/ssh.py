"""Desktop adapter for the existing temporary SSH implementation."""
import importlib.util
from pathlib import Path

from ..paths import ROOT, write_json


def engine():
    source = ROOT / 'dev/ssh/session.py'
    spec = importlib.util.spec_from_file_location('a7c2_temporary_ssh', source)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def run(action, args, job):
    if args.get('firmware') != '2.01':
        raise ValueError('Temporary SSH supports ILCE-7CM2 2.01 only')
    module = engine()
    folder = Path(args['workspace']).resolve()
    if action == 'ssh_prepare':
        if not args.get('client_key'):
            raise ValueError('请选择电脑端 Ed25519 公钥（.pub）')
        result = module.prepare(args.get('artifacts') or ROOT / 'desktop-assets/ssh', None,
                                args['client_key'], args['bind_ip'], folder,
                                listen_all=bool(args.get('listen_all')))
    elif action == 'ssh_verify_login':
        if not args.get('client_private'):
            raise ValueError('请选择与准备时公钥配对的电脑端 SSH 私钥；私钥只留在电脑')
        result = module.verify_login(folder, args['client_private'])
    elif action in ('ssh_start', 'ssh_status', 'ssh_stop'):
        result = module.run_device(folder, action.removeprefix('ssh_'))
    else:
        raise ValueError('Unknown temporary SSH action: ' + action)
    write_json(Path(job) / 'backend-workspace.private.json',
               dict(action=action, workspace=str(folder)))
    response = dict(workspace=str(folder), phase=result['phase'],
                    camera_io=action in ('ssh_start', 'ssh_status', 'ssh_stop'),
                    firmware_written=False, settings_written=False,
                    persistent_startup=False, ssh_login_verified=result.get('ssh_login_verified', False),
                    camera_ip=result['camera_ip'], port=2222)
    response['message'] = {
        'ssh_prepare': '临时 SSH 已离线准备。接回 USB 后点“启动临时 SSH”；本步骤未访问相机。',
        'ssh_start': '临时 SSH 监听已核对。保持相机开机，拔 USB 并连接 Wi-Fi，再点“核对 SSH 登录”。',
        'ssh_status': 'USB 查询已完成；监听状态见日志。本步骤不重复启动 SSH。',
        'ssh_stop': '停止结果见日志；只有 STOPPED 表示监听消失已核对。',
        'ssh_verify_login': 'SSH 公钥登录、root 身份及相同开机身份已核对。',
    }[action]
    print(response['message'], flush=True)
    return response
