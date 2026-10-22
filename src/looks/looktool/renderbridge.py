"""Small JSON-RPC stdio client for a configured Lightroom MCP renderer.

No AI is involved. Lightroom and its bridge/plugin are dependencies. The
bridge's broker shares an existing plugin connection instead of replacing it.
This client owns and closes only its own subprocess, never another process.
"""
import json
import os
from pathlib import Path
import queue
import subprocess
import threading
import time


class Lightroom:
    def __init__(self, command, log, timeout=300):
        self.timeout=timeout;self.serial=0;self.responses=queue.Queue()
        self.log=Path(log).open('a',encoding='utf-8')
        self.process=subprocess.Popen(command,stdin=subprocess.PIPE,stdout=subprocess.PIPE,
            stderr=self.log,text=True,encoding='utf-8',bufsize=1,
            creationflags=0x08000000 if os.name=='nt' else 0)
        def read():
            try:
                for line in self.process.stdout:
                    try:self.responses.put(json.loads(line))
                    except ValueError:continue
            finally:self.responses.put(None)
        self.reader=threading.Thread(target=read,daemon=True);self.reader.start()
        try:
            self.request('initialize',dict(protocolVersion='2024-11-05',capabilities={},
                clientInfo=dict(name='a7look-offline-compiler',version='0.1')))
            self.send(dict(jsonrpc='2.0',method='notifications/initialized'))
        except BaseException:
            self.close();raise

    def send(self, value):
        self.process.stdin.write(json.dumps(value,ensure_ascii=False)+'\n');self.process.stdin.flush()

    def request(self, method, params):
        self.serial+=1;current=self.serial
        self.send(dict(jsonrpc='2.0',id=current,method=method,params=params))
        deadline=time.monotonic()+self.timeout
        while True:
            remaining=deadline-time.monotonic()
            if remaining<=0:raise TimeoutError('Lightroom renderer did not finish '+method)
            try:value=self.responses.get(timeout=remaining)
            except queue.Empty:raise TimeoutError('Lightroom renderer did not finish '+method)
            if value is None:raise RuntimeError('Lightroom renderer exited; inspect renderer.log')
            if value.get('id')!=current:continue
            if 'error' in value:raise RuntimeError(str(value['error']))
            return value.get('result')

    def call(self, name, **arguments):
        value=self.request('tools/call',dict(name=name,arguments=arguments))
        if value.get('isError'):raise RuntimeError(str(value.get('content')))
        texts=[item['text'] for item in value.get('content',[]) if item.get('type')=='text']
        for text in texts:
            try:
                result=json.loads(text)
                if isinstance(result,dict) and result.get('success') is False:raise RuntimeError(text)
                return result
            except json.JSONDecodeError:continue
        return value

    def render(self, path, destination, settings=None):
        path=str(Path(path).resolve());destination=str(Path(destination).resolve())
        Path(destination).mkdir(parents=True,exist_ok=True)
        try:
            self.call('get_photo_metadata',photo_id=path)
        except RuntimeError as exc:
            if not any(word in str(exc).lower() for word in ('not found','no photo','could not find')):
                raise
            self.call('import_photos',source_path=path)
        if settings:self.call('set_develop_settings',photo_id=path,settings=settings)
        self.call('export_photos',photo_ids=[path],destination=destination,
                  format='jpeg',quality=100,on_existing='skip')
        result=Path(destination)/(Path(path).stem+'.jpg')
        if not result.is_file():raise RuntimeError('Renderer returned without producing '+str(result))
        return result

    def close(self):
        try:
            if self.process.stdin:self.process.stdin.close()
            self.process.wait(timeout=5)
        except (OSError,subprocess.TimeoutExpired):
            self.process.terminate()
            try:self.process.wait(timeout=5)
            except subprocess.TimeoutExpired:self.process.kill();self.process.wait()
        self.log.close()

    def __enter__(self):return self
    def __exit__(self,*args):self.close()
