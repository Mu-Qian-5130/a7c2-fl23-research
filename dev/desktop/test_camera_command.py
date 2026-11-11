"""Small portable payload and shell argument contracts; no device access."""
import base64
import json
import shlex
import struct

import pytest

from desktopapp import cameraapi


def document():
    return dict(schema='a7c2-creative-look/1',target={'model':'ILCE-7CM2','firmware':'2.01'},base='ST',
        name='Example',table_format='native-5x9x9-s7-planar',table_base64=base64.b64encode(bytes(1215)).decode())


def test_table_only_payload_explicitly_clears_native_stage():
    raw=cameraapi.look_payload(document())
    assert len(raw)==1324 and raw==bytes(1324)


def test_bad_compiled_table_is_rejected_before_connection():
    doc=document();doc['table_base64']=base64.b64encode(b'\x7f'+bytes(1214)).decode()
    with pytest.raises(ValueError):cameraapi.look_payload(doc)


def test_full_native_packet_keeps_all_parameters_and_rejects_ambiguous_legacy():
    from test_editrecipe import recipe
    from looktool import editrecipe,lookfile
    doc=document();doc['schema']=lookfile.FULL_SCHEMA;doc['edit_native']=recipe()
    raw=cameraapi.look_payload(doc)
    assert len(raw)==3423 and raw[:8]==b'A7F2LOOK'
    assert raw[8:1223]==bytes(1215)
    assert editrecipe.unpack(raw[1223:])==doc['edit_native']
    doc['schema']=lookfile.SCHEMA
    with pytest.raises(ValueError):cameraapi.look_payload(doc)


def test_a7look_is_read_and_sent_without_an_intermediate_file(tmp_path):
    source=tmp_path/'my look.a7look';source.write_text(json.dumps(document()),encoding='utf-8')
    class Connection:
        def execute(self,command,data=None):self.command=command;self.data=data;return b'{"state":"pending_reload"}'
    connection=Connection()
    assert cameraapi.apply_look(connection,4,source)['state']=='pending_reload'
    assert shlex.split(connection.command)==[cameraapi.COMMAND,'look','4','Example']
    assert connection.data==bytes(1324)
    assert list(tmp_path.iterdir())==[source]
    title,data=cameraapi.prepare_look(source,'Custom name');assert title=='Custom name' and data==bytes(1324)


def test_fixed_command_quotes_name_without_shell_expansion():
    class Connection:
        def execute(self,command,data=None):self.command=command;self.data=data;return b'{"state":"pending_reload"}'
    connection=Connection();name="My look ' $(unused)"
    assert cameraapi.call(connection,'look',3,name,payload=b'body')['state']=='pending_reload'
    assert shlex.split(connection.command)==[cameraapi.COMMAND,'look','3',name]
    assert connection.data==b'body'
    with pytest.raises(ValueError):cameraapi.call(connection,'unknown')


def test_ssh_structured_failure_is_preserved(monkeypatch):
    from desktopapp.sshupdates import Connection
    import subprocess
    connection=Connection.__new__(Connection);connection.command=['ssh','fixture']
    monkeypatch.setattr(subprocess,'run',lambda *a,**k:subprocess.CompletedProcess([],1,b'{"state":"failed","error":"busy"}',b''))
    assert cameraapi.call(connection,'task')=={'state':'failed','error':'busy'}
