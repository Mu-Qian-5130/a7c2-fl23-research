"""Prepare the existing C2 public-key policy offline; no installer or device I/O."""
import importlib.util
from pathlib import Path
from .paths import ROOT,write_json
from .identity import signing_paths


def validate_source(value):
    if value is None or not str(value).strip():
        raise ValueError('请先选择更新器解包目录；它应包含 usr/lib 下的四个更新器库。此工具只准备电脑文件，不会写入机身公钥。')
    source=Path(value).expanduser().resolve()
    if not source.is_dir():raise ValueError('更新器解包目录不存在，或所选路径不是文件夹：'+str(source))
    spec=importlib.util.spec_from_file_location('c2_trust_policy',ROOT/'dev/firmware/trust_image.py')
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    missing=[name for name in module.LIBRARIES if not (source/'usr/lib'/name).is_file()]
    if missing:
        raise ValueError('所选目录不是完整的 C2 更新器解包根目录。缺少 usr/lib 下的文件：'+
            '、'.join(missing)+'。仅有普通固件构建结果不够。')
    return source,module


def validate(args):
    source,module=validate_source(args.get('updater_root'))
    value=args.get('workspace')
    if value is None or not str(value).strip():raise ValueError('请选择新的输出目录。')
    out=Path(value).expanduser().resolve()
    if out.exists():raise ValueError('输出目录已存在，请选择新的目录，保留原有文件：'+str(out))
    return source,module,out


def prepare(args,job):
    source,module,out=validate(args)
    originals={name:(source/'usr/lib'/name).read_bytes() for name in module.LIBRARIES}
    _,public=signing_paths();public_bytes=public.read_bytes()
    prepared={name:module.pin_library(raw,public_bytes) for name,raw in originals.items()}
    out.mkdir(parents=True,exist_ok=False)
    for name,(data,_) in prepared.items():
        path=out/'usr/lib'/name;path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(data)
    path=out/'etc/VerificationKey.pem';path.parent.mkdir(parents=True);path.write_bytes(public_bytes)
    report=dict(phase='OFFLINE_TRUST_POLICY',workspace=str(out),camera_io=False,device_ready=False,
        private_key_in_camera_files=False,installation_performed=False,installer_available=True,
        libraries={name:row for name,(_,row) in prepared.items()},
        note='Offline policy files only. Use the separate USB installer for first body installation.')
    write_json(out/'trust-policy.private.json',report)
    write_json(Path(job)/'backend-workspace.private.json',dict(workspace=str(out)))
    return report
