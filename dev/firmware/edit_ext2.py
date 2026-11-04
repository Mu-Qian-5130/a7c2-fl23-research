"""Use e2fsprogs only on an explicit local image copy, then check it read-only."""
import json
from pathlib import Path
import re
import subprocess
import sys


def quoted(value):
    if '\n' in value or '\r' in value:raise ValueError('Unexpected newline in image path')
    return '"'+value.replace('\\','\\\\').replace('"','\\"')+'"'


def main():
    plan=json.loads(Path(sys.argv[1]).read_text())
    image=Path(plan['image']).resolve()
    if not image.is_file() or image.suffix!='.img' or str(image).startswith('/dev/'):
        raise ValueError('Explicit regular .img file required')
    def command(text,write=False):
        result=subprocess.run(['debugfs',*(['-w'] if write else []),'-R',text,str(image)],
                              capture_output=True,text=True,check=True)
        print(result.stdout+result.stderr,end='',flush=True)
        return result.stdout
    for target,row in plan['files'].items():
        if not target.startswith('/') or '..' in Path(target).parts:raise ValueError('Invalid internal image path')
        info=command('stat '+quoted(target));exists='Inode:' in info
        if row.get('delete'):
            if not exists or 'Type: regular' not in info:raise ValueError('Missing or non-regular resource deletion target')
            command('rm '+quoted(target),True)
            if 'Inode:' in command('stat '+quoted(target)):raise ValueError('Resource deletion failed')
            continue
        source=Path(row['source']).resolve()
        if not source.is_file():raise ValueError('Missing local replacement')
        if exists:
            if 'Type: regular' not in info:raise ValueError('Refusing to replace a non-regular image entry')
            mode=int(re.search(r'Mode:\s+([0-7]+)',info)[1],8)
            user=int(re.search(r'User:\s+(\d+)',info)[1]);group=int(re.search(r'Group:\s+(\d+)',info)[1])
            command('rm '+quoted(target),True)
        else:
            mode=row['mode'];user=group=0
            parent=Path(target).parent;parts=list(parent.parts[1:]);current=''
            for part in parts:
                current+='/'+part
                parent_info=command('stat '+quoted(current))
                if 'Inode:' not in parent_info:command('mkdir '+quoted(current),True)
                elif 'Type: directory' not in parent_info:raise ValueError('Image parent is not a directory')
        command('write '+quoted(str(source))+' '+quoted(target),True)
        for field,value in (('mode',0o100000|mode),('uid',user),('gid',group)):
            command('set_inode_field '+quoted(target)+' '+field+' '+str(value),True)
    checked=subprocess.run(['e2fsck','-fn',str(image)],capture_output=True,text=True)
    print(checked.stdout+checked.stderr,flush=True)
    if checked.returncode:raise ValueError('Edited image failed read-only filesystem check')


if __name__=='__main__':main()
