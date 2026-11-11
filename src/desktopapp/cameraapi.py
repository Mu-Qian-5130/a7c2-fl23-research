"""Fixed camera command client and offline build. No device access on import."""
import json
import os
from pathlib import Path
import shlex
import struct
import subprocess
import sys

from .paths import ROOT

COMMAND='/usr/bin/a7c2-api'

LOOK_RESTART_MESSAGE = (
    '外观文件已保存，本次不会立即更新颜色、名称和图标。'
    '请等读写结束并等存取灯停止，关机并等灯灭，断开 USB／外部供电，'
    '取下电池至少 1 分钟，再装回开机。开机后确认颜色、名称和图标。'
)


def look_payload(document):
    """Encode the complete native recipe, or the bounded legacy stage packet."""
    from looktool import lookfile,photoformat
    icon = document.get('menu_icon')
    if icon is not None:
        # The artwork is carried in a versioned envelope, not discarded to make
        # an old command accept a file it cannot install completely.
        lookfile.validate(document)
        from .iconprotocol import pack
        color = dict(document)
        color.pop('menu_icon')
        return pack(look_payload(color), icon)
    if document.get('edit_native')is not None:
        from looktool.editrecipe import pack
        return b'A7F2LOOK'+lookfile.validate(document)+pack(document['edit_native'])
    table=lookfile.writer_document(document)
    stage=document.get('native_photo')
    values=[0]*54
    if stage:
        basis=stage['runtime_basis']
        values=list(basis['tone_q10'])
        values += [n for row in basis['matrix_planes'] for n in photoformat.expand_matrix(row,(0,0,0))]
        values += [n for row in basis['chroma_planes'] for n in row]
    return table+bytes((stage is not None,))+struct.pack('<54h',*values)


def prepare_look(source,name=None):
    """Read the user's .a7look directly; packed bytes stay in memory."""
    from looktool import lookfile
    document=lookfile.read(source)
    return name or document['name'],look_payload(document)


def apply_look(connection,slot,source,name=None):
    title,payload=prepare_look(source,name)
    from .iconprotocol import MAGIC
    if payload.startswith(MAGIC):
        capabilities = call(connection, 'info')
        if capabilities.get('menu_icons_protocol') != 1:
            raise ValueError('机内外观 API 尚未支持图标；没有发送颜色、名称或图标写入')
    return call(connection,'look',slot,title,payload=payload)


def call(connection,operation,*arguments,payload=None):
    if operation not in ('info','look','sound','task','files','readback','undo','look-status'):raise ValueError('Unknown camera command')
    command=' '.join(shlex.quote(str(v)) for v in (COMMAND,operation,*arguments))
    response=(connection.execute_api(command,payload) if hasattr(connection,'execute_api') else
              json.loads(connection.execute(command,payload).decode('utf-8')))
    if (operation=='look' or operation=='task' and response.get('operation')=='look'):
        if response.get('state')=='pending_reload':
            response.update(reload_required=True,restart_method='battery_removal',
                            live_reload=False,runtime_verified=False,message=LOOK_RESTART_MESSAGE)
        elif operation=='task' and response.get('state')=='active':
            response.update(runtime_verified=False,
                message='已观察到重启；请在相机中确认颜色、名称和图标，任务状态不代表运行数据已核验。')
    return response


def compile_native(source,output,*,zig=None,include=None):
    from looktool.nativebuild import zig_command
    output=Path(output);output.parent.mkdir(parents=True,exist_ok=True)
    env=os.environ.copy();cache=Path(os.environ.get('A7C2_ZIG_CACHE',output.parent/'zig-cache'))
    env.update(ZIG_GLOBAL_CACHE_DIR=str(cache/'global'),ZIG_LOCAL_CACHE_DIR=str(cache/'local'))
    command=zig_command(zig)+['cc','-target','aarch64-linux-musl','-Os','-s','-static']
    if include:command+=['-I',str(Path(include).parent),'-DCAMERA_CONFIG="'+Path(include).name+'"']
    command += [str(source),'-o',str(output)]
    done=subprocess.run(command,env=env,capture_output=True,text=True,encoding='utf-8',errors='replace',timeout=180)
    if done.returncode:raise ValueError('Camera command compilation failed: '+done.stderr[-2500:])
    return output


def configuration(current):
    """Compile known target locations into the camera side, never the client."""
    from looktool import device_layout,nameworker,six,photobuild,photoio,photofull,fixedbank,fixedbankcode,fixedregion
    sys.path.insert(0,str(ROOT/'src/shutter_sound'))
    import candidate,targeted_sound
    ap,cp=current['appFw.so'],current['cpapp-b.bin']
    identity=device_layout.structural_ap(ap)
    mask=identity['mask'];fixed=fixedbankcode.present(cp)
    if fixed:
        device_layout.structural(ap,cp);bank=fixedbank.parse(fixedbank.extract_cp(cp));photo=full_photo=True
    else:
        photo=photoio.present(cp)
        if photo:photoio.inspect(cp)
        full_photo=photofull.present(cp)
    cbytes=lambda raw:'{'+','.join(str(v) for v in raw)+'}'
    rows=[(candidate.TABLE_AFTER,candidate.GATE_MUTED,0),
          (candidate.TABLE_SPLIT,candidate.GATE_MECHANICAL,1),
          (candidate.TABLE_ELECTRONIC,candidate.GATE_ELECTRONIC,2),
          (candidate.TABLE_SPLIT,candidate.GATE_BOTH,3)]
    rows += [(candidate.TABLE_BEFORE,candidate.CONTEXT,1),(candidate.TABLE_BEFORE,candidate.LEGACY_GATE,3),
             (candidate.TABLE_AFTER,candidate.GATE_AFTER,2),(candidate.TABLE_AFTER,candidate.GATE_ELECTRONIC,2)]
    candidate.guard(ap,cp,installed=candidate.is_enabled(cp))
    custom=all(ap[at:at+len(after)]==after for at,_,after in targeted_sound.windows(ap))
    def guards(name,source,windows):
        return 'static const struct api_guard '+name+'[]={'+','.join(
            '{'+f'{at},{size},(const unsigned char[])'+cbytes(source[at:at+size])+'}' for at,size in windows)+'};'
    look_cp=[(0x20124,48)]
    if fixed:
        code,patches,_=fixedbankcode.generate()
        look_cp += [(at,len(raw))for at,raw in patches.items()]
        look_cp += [(fixedbank.ROOT_VA-fixedbankcode.BASE,8),(fixedbank.NATIVE_TABLE-fixedbankcode.BASE,1400),
                    (fixedregion.SOURCE_CODE_START,len(code)),(fixedregion.SOURCE_DATA_START,8)]
    else:look_cp.append((six.TABLE_FILE,8))
    if photo and not fixed:
        value=photofull.template()if full_photo else photoio.template()
        look_cp += [(photobuild.DATA_FILE,8),(photobuild.DATA_FILE+12,4),
                    (photobuild.CODE_FILE,value['code_bytes'])]
        look_cp += [(row['offset'],len(bytes.fromhex(row['after']))) for row in value['hooks']]
    sound_cp=[(0x20124,48)]+[(at,len(raw)) for at,raw in candidate.CP_GUARDS]
    sound_ap=[(0x286cde8,20),(0x2885488,20)]
    custom_ap=[(at,len(after)) for at,_,after in targeted_sound.windows(ap)] if custom else sound_ap
    lines=[f'#define API_FULL_NATIVE {int(full_photo)}',f'#define API_FIXED_BANK {int(fixed)}',
        '#define API_MENU_ICONS 1',
        f'static const unsigned slot_mask={mask},photo_available={int(photo)},sound_available=1,custom_audio_available={int(custom)};',
        f'static const unsigned cp_file_size={len(cp)},ap_file_size={len(ap)};',
        guards('look_cp_guards',cp,look_cp),guards('look_ap_guards',ap,[(0x35287f0,132)]),
        guards('sound_cp_guards',cp,sound_cp),guards('sound_ap_guards',ap,sound_ap),
        guards('custom_ap_guards',ap,custom_ap),
        'static const unsigned char sound_front_before[]='+cbytes(candidate.FRONT_BEFORE)+';',
        'static const unsigned char sound_mechanical_before[]='+cbytes(candidate.MECHANICAL_BEFORE)+';',
        f'static const unsigned table_offset={six.TABLE_FILE},table_magic={six.MAGIC}U,table_layout={six.VERSION};',
        f'static const unsigned photo_mask_offset={photobuild.DATA_FILE+8},photo_params_offset={photobuild.PARAMS_VA-photobuild.BASE};',
        'static const unsigned label_ids[]={'+','.join(str(n) for n in identity['label_ids'])+'};',
        'static const char *name_files[]={'+','.join(json.dumps(n) for n in nameworker.filenames())+'};',
        f'static const unsigned name_count={len(nameworker.filenames())};',
        f'#define SOUND_GATE_SIZE {len(candidate.CONTEXT)}',
        f'static const unsigned sound_table_offset={candidate.SELECTOR_TABLE},sound_gate_offset={candidate.GATE},sound_front_offset={candidate.FRONT},sound_mechanical_offset={candidate.MECHANICAL};',
        'static const unsigned char sound_tables[][5]={'+','.join(cbytes(a) for a,_,_ in rows)+'};',
        'static const unsigned char sound_gates[][SOUND_GATE_SIZE]={'+','.join(cbytes(b) for _,b,_ in rows)+'};',
        'static const unsigned sound_flags[]={'+','.join(str(c) for _,_,c in rows)+'};',
        f'static const unsigned sound_states={len(rows)};',
        'static const unsigned char sound_front[]='+cbytes(candidate.FRONT_AFTER)+';',
        'static const unsigned char sound_mechanical[]='+cbytes(candidate.MECHANICAL_AFTER)+';']
    if fixed:
        lines += [f'#define FIXED_SOURCE {fixedregion.SOURCE_DATA_START}U',f'#define FIXED_BYTES {bank["bytes"]}U',
                  f'#define FIXED_ROOT {fixedbank.ROOT_VA-fixedbankcode.BASE}U',f'#define FIXED_BASE {fixedbank.DATA_START}U',
                  f'#define FIXED_CAPACITY {fixedbank.DATA_BYTES}U',
                  'static const unsigned char fixed_native_basis[]='+cbytes(bank['basis'])+';']
    return '\n'.join(lines)+'\n'


def build(current,output,zig=None):
    output=Path(output);output.mkdir(parents=True,exist_ok=True)
    header=output/'camera.private.h';header.write_text(configuration(current),encoding='ascii',newline='\n')
    return compile_native(ROOT/'src/camera_api/command.c',output/'a7c2-api',zig=zig,include=header)
