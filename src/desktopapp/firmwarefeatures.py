"""Offline feature dependencies and byte ownership for the final firmware."""
import base64
import copy


def options(args):
    custom=bool(args.get('custom_looks',bool(args.get('preset_pack') or args.get('looks'))))
    if args.get('voice_cleanup') is False:
        raise ValueError('本地固件必须删除无障碍语音音频并禁用语音指南')
    if (args.get('ssh') or args.get('preset_pack') or args.get('looks')) and not custom:
        raise ValueError('索尼云创接口和外观素材依赖启用自定义创意外观')
    if args.get('precapture'):
        raise ValueError('预拍摄支线尚未完成整合与连续流程验证，本次不生成固件；其他选项未被忽略')
    return dict(custom_looks=custom,vertical=bool(args.get('vertical')),voice_cleanup=True,precapture=False,
                ssh=bool(args.get('ssh')),sound=bool(args.get('sound')),fl23=bool(args.get('fl23',True)),
                whitebalance=bool(args.get('whitebalance')))


class Composition:
    """A later feature may not replace bytes already assigned to another feature."""
    def __init__(self,current):
        self.current=dict(current);self.owners={};self.rows=[]

    def apply(self,name,changes):
        from looktool.checkpointworker import differences
        rows=[]
        for filename,after in changes.items():
            before=self.current[filename]
            if len(before)!=len(after):raise ValueError('Feature resized a program: '+name)
            for at,old,new in differences(before,after):
                # differences() coalesces nearby edits; ownership covers changed bytes only.
                for i,(a,b) in enumerate(zip(old,new)):
                    if a==b:continue
                    key=(filename,at+i)
                    if key in self.owners:raise ValueError('功能写入冲突：'+name+' / '+self.owners[key]+' / '+filename+' / '+hex(at+i))
                    rows.append(key)
        for key in rows:self.owners[key]=name
        self.current.update(changes);self.rows.append(dict(feature=name,changed_bytes=len(rows)))


def neutral_looks(current,records):
    from looktool import device_layout,lookfile,photoformat,photobasis
    cp=device_layout.replace(current['appFw.so'],current['cpapp-b.bin'],{1:bytes(1215)},hash_checks=False,transitions=False)[2]['cpapp-b.bin']
    bank=photoformat.extract_bank(cp,records[1][0x02a40001].data,records[1][0x02a4000d].data,
        gamma_table_va=0x1209480,regular_row=0,still_row=10,color_parameter=0)[0]
    stage=photobasis.pack(bank)[1]
    return [dict(slot=i,name='ST',document=dict(schema=lookfile.SCHEMA,target=lookfile.TARGET,base='ST',name='ST',
        table_format=lookfile.FORMAT,table_base64=base64.b64encode(bytes(1215)).decode(),native_photo=copy.deepcopy(stage))) for i in range(1,7)]


def resources(current,records,features,selected=()):
    from looktool import voicelock,verticalpersist,nativebuild
    import sys
    result={'appFw.so':voicelock.patch(current['appFw.so'])}
    wanted=[voicelock.settings(current['appFw.so'],records),{}]
    wanted[0].update(verticalpersist.field(current['appFw.so'],records,features['vertical']))
    files={}
    icons={row['slot']:row['document']['menu_icon'] for row in selected if row['document'].get('menu_icon') is not None}
    if icons:
        from .menuicons import replace
        current=dict(current)
        name='image_00_32_IPSX.uxc'
        changed,_=replace(current['images/'+name],icons)
        current['images/'+name]=changed
        files['/share/app/'+name]=changed
    if features['vertical']:
        sys.path.insert(0,str(nativebuild.ROOT/'src/vertical'))
        from verticaltool import nativeportrait,portraitlayout,portraitgauge
        # Starting from official bytes: no old compensated AP layout is accepted.
        if portraitlayout.active(current['appFw.so']):raise ValueError('旧竖屏补偿不能与独立竖屏资源组合')
        for at,expected in ((portraitgauge.OFFSET,portraitgauge.BEFORE),(portraitgauge.VERTICAL_OFFSET,portraitgauge.VERTICAL_BEFORE)):
            if current['appFw.so'][at:at+len(expected)]!=expected:raise ValueError('Native portrait gauge layout differs')
        names=[f'image_{i:02d}_32_IPSX.uxc' for i in range(3)]
        for i,raw in enumerate(nativeportrait.targets([current['images/'+name] for name in names])):
            files[f'/share/app/image_{i:02d}_23_IPSX.uxc']=raw
    return result,wanted,files


def compose(current,records,args):
    from looktool import bundle,whitebalance,device_layout,photoio
    features=options(args);looks=args.get('looks',[])
    if args.get('preset_pack'):
        from .presets import resolve
        looks=resolve(dict(preset_pack=args['preset_pack'],looks=looks))['looks']
    selection,selected=bundle.documents(dict(fl23=features['fl23'],sound=features['sound'],looks=looks),allow_menu_icons=True)
    if features['custom_looks'] and not selected:selected=neutral_looks(current,records)
    target,wanted,_=bundle.plan(current,records,selection,selected)
    composition=Composition({n:current[n] for n in ('appFw.so','cpapp-b.bin')})
    composition.apply('looks-and-native-sound',{n:target[n] for n in composition.current})
    if features['whitebalance']:
        composition.apply('whitebalance',{'cpapp-b.bin':whitebalance.plan(target['cpapp-b.bin'],True)})
        target.update(composition.current)
    if features['sound']:
        import boot_sound,targeted_sound
        composition.apply('sound-loader',{'appFw.so':boot_sound.patch(target['appFw.so'],targeted_sound.windows(target['appFw.so']))})
        target.update(composition.current)
    programs,fields,files=resources(target,records,features,selected)
    composition.apply('voice-disable',programs);target.update(composition.current)
    for chip in (0,1):
        for key,value in fields[chip].items():
            if key in wanted[chip] and wanted[chip][key]!=value:raise ValueError('功能设置冲突：'+hex(key))
        wanted[chip].update(fields[chip])
    device_layout.structural(target['appFw.so'],target['cpapp-b.bin'])
    if photoio.present(target['cpapp-b.bin']):photoio.inspect(target['cpapp-b.bin'])
    return target,wanted,selected,files,dict(features=features,stages=composition.rows,
        menu_icon_slots=[row['slot'] for row in selected if row['document'].get('menu_icon') is not None],camera_io=False)
