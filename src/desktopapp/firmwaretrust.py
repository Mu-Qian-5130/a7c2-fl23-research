"""Prepare the existing C2 public-key policy offline; no installer or device I/O."""
import importlib.util
from pathlib import Path
from .paths import ROOT,write_json
from .identity import signing_paths


def prepare(args,job):
    source=Path(args['updater_root']);out=Path(args['workspace'])
    spec=importlib.util.spec_from_file_location('c2_trust_policy',ROOT/'dev/firmware/trust_image.py')
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    originals={name:(source/'usr/lib'/name).read_bytes() for name in module.LIBRARIES}
    _,public=signing_paths();public_bytes=public.read_bytes()
    prepared={name:module.pin_library(raw,public_bytes) for name,raw in originals.items()}
    out.mkdir(parents=True,exist_ok=False)
    for name,(data,_) in prepared.items():
        path=out/'usr/lib'/name;path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(data)
    path=out/'etc/VerificationKey.pem';path.parent.mkdir(parents=True);path.write_bytes(public_bytes)
    report=dict(phase='OFFLINE_TRUST_POLICY',workspace=str(out),camera_io=False,device_ready=False,
        private_key_in_camera_files=False,first_install_implemented=False,
        libraries={name:row for name,(_,row) in prepared.items()},
        note='Public-key policy files only. First camera installation is not implemented.')
    write_json(out/'trust-policy.private.json',report)
    write_json(Path(job)/'backend-workspace.private.json',dict(workspace=str(out)))
    return report
