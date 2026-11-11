"""Build-time paired library; mono entries require accepted independent errors."""
import json
from pathlib import Path,PurePosixPath

ROOT=Path(__file__).resolve().parents[2]
FUJI=('Astia','Bleach_Bypass','Classic_Chrome','Classic_Negative','Eterna',
      'Nostalgic_Negative','Pro_Neg_Hi','Pro_Neg_Std','Provia','Reala_Ace','Velvia')
RICOH=('Hard Monotone','Monotone','Negative Film','Positive Film','Soft Monotone','Standard','Vivid')
PAIRS=tuple(('Fujifilm','Sony_ILCE-7CM2_'+name) for name in FUJI)+tuple(
    ('Ricoh GR III','Sony_ILCE-7CM2 RICOH GR III Camera '+name+' (GR Look, a7C2 WB)') for name in RICOH)
MONO=('Hard Monotone','Monotone','Soft Monotone')
OPTIONAL={('Ricoh GR III/Sony_ILCE-7CM2 RICOH GR III Camera '+name+' (GR Look, a7C2 WB).dcp',
           'Ricoh GR III/Sony_ILCE-7CM2 RICOH GR III Camera '+name+' (GR Look, a7C2 WB).a7look') for name in MONO}

def refresh_labels(root=ROOT):
    """Refresh known presentation names, preserving paired DCP and fitting data."""
    import csv
    import io
    import sys
    root=Path(root);sys.path[:0]=[str(root/'src'),str(root/'src/looks')]
    from looktool import lookfile,looklabels
    library=root/'desktop-assets/profile-library-v1';path=library/'catalog.json'
    if not path.is_file():return []
    document=json.loads(path.read_text(encoding='utf-8'));changed=[]
    for row in document['profiles']:
        target=library/row['a7look'];look=lookfile.read(target)
        reviewed=looklabels.lookup(look['name']) or looklabels.lookup(row['name'])
        if reviewed is None:continue
        look=looklabels.relabel(look);row['name']=reviewed['name']
        row['menu_icon_text']=reviewed['icon_text']
        target.write_text(json.dumps(look,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
        row['menu_a7look']='MenuIcons/'+row['a7look']
        menu=library/row['menu_a7look'];menu.parent.mkdir(parents=True,exist_ok=True)
        menu.write_text(json.dumps(looklabels.relabel(look,include_icon=True),ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
        changed.append(dict(a7look=row['a7look'],name=row['name'],icon_text=reviewed['icon_text']))
    path.write_text(json.dumps(document,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    csv_path=library/'catalog.csv'
    if csv_path.is_file():
        reader=csv.DictReader(io.StringIO(csv_path.read_text(encoding='utf-8-sig')))
        columns=reader.fieldnames;rows=list(reader)
        by_path={row['a7look']:row for row in document['profiles']}
        for row in rows:
            if row.get('a7look') in by_path and 'name' in row:row['name']=by_path[row['a7look']]['name']
        with csv_path.open('w',encoding='utf-8',newline='') as output:
            writer=csv.DictWriter(output,columns);writer.writeheader();writer.writerows(rows)
    return changed


def menu_paths(document):
    paths=[]
    for row in document['profiles']:
        value=row.get('menu_a7look')
        if value is None:continue
        if not isinstance(value,str):raise ValueError('Menu look path must be text')
        path=PurePosixPath(value)
        if '\\'in value or ':'in value or path.is_absolute() or '..'in path.parts or path.suffix!='.a7look' or path.parts[0]!='MenuIcons':
            raise ValueError('Menu look path must stay inside MenuIcons')
        if value.casefold()in {p.casefold()for p in paths}:raise ValueError('Duplicate menu look path')
        paths.append(value)
    return paths


def paired_paths(document):
    if document.get('schema')=='a7c2-profile-library/2':
        rows=document.get('profiles',[])
        if not rows or document.get('count')!=len(rows):raise ValueError('Profile catalog count differs')
        present=set();names=set();paths=set()
        for row in rows:
            name=row.get('name','')
            if not isinstance(name,str)or not name or name.casefold()in names:raise ValueError('Duplicate or empty profile name')
            names.add(name.casefold());pair=[]
            for key,suffix in [('dcp','.dcp'),('a7look','.a7look')]:
                value=row.get(key,'')
                if not isinstance(value,str)or not value:raise ValueError('Profile path must be text')
                path=PurePosixPath(value)
                if '\\'in value or ':'in value or path.is_absolute()or '..'in path.parts or path.suffix!=suffix:
                    raise ValueError('Profile path must stay inside the library')
                if value.casefold()in paths:raise ValueError('Duplicate profile path')
                paths.add(value.casefold());pair.append(value)
            if PurePosixPath(pair[0]).with_suffix('')!=PurePosixPath(pair[1]).with_suffix(''):raise ValueError('Profile pair stems differ')
            if row.get('monochrome')or any(term in name.casefold()for term in ('monotone','monochrome')):
                metrics=row.get('independent_prediction',{})
                if metrics.get('RGB_MAE_8bit',float('inf'))>3 or metrics.get('RGB_P95_8bit',float('inf'))>12:
                    raise ValueError('Monochrome profile does not meet independent inclusion criteria: '+pair[0])
            present.add(tuple(pair))
        return present
    allowed={(group+'/'+stem+'.dcp',group+'/'+stem+'.a7look') for group,stem in PAIRS}
    rows=document['profiles'];present={(r['dcp'],r['a7look']) for r in rows}
    if len(present)!=len(rows) or not allowed-OPTIONAL<=present<=allowed:
        raise ValueError('Profile library must include 11 Fujifilm and 4 Ricoh color pairs; mono pairs are optional')
    for row in rows:
        if (row['dcp'],row['a7look']) in OPTIONAL:
            metrics=row.get('independent_prediction',{})
            if metrics.get('RGB_MAE_8bit',float('inf'))>3 or metrics.get('RGB_P95_8bit',float('inf'))>12:
                raise ValueError('Monochrome profile does not meet independent inclusion criteria: '+row['dcp'])
    return present

def files(root=ROOT,*,verify_pairs=True,document=None):
    root=Path(root);library=root/'desktop-assets/profile-library-v1'
    catalog=library/'catalog.json'
    if not catalog.is_file():raise FileNotFoundError('Prepare the accepted paired-profile library before packaging: '+str(library))
    if document is None:document=json.loads(catalog.read_text(encoding='utf-8'))
    paired_paths(document)
    rows=document['profiles']
    values={'catalog.json':catalog}
    for name in menu_paths(document):
        path=library/name
        if not path.is_file():raise FileNotFoundError(path)
        values[name]=path
    for row in rows:
        for key in ('dcp','a7look'):
            path=library/row[key]
            if not path.is_file():raise FileNotFoundError(path)
            values[row[key]]=path
        if verify_pairs:
            import sys
            sys.path.insert(0,str(root/'src/looks'))
            from looktool import lookfile,rawidentity
            look=lookfile.read(library/row['a7look']);lookfile.writer_document(look)
            if rawidentity.source_bytes(look['raw_profile'])!=(library/row['dcp']).read_bytes():
                raise ValueError('DCP / A7Look source differs: '+row['a7look'])
            if row.get('menu_a7look'):
                menu=lookfile.read(library/row['menu_a7look'])
                if not menu.get('menu_icon') or {k:v for k,v in menu.items()if k!='menu_icon'}!={k:v for k,v in look.items()if k!='menu_icon'}:
                    raise ValueError('Menu companion changes color or source: '+row['menu_a7look'])
                if row.get('menu_icon_text') and menu['menu_icon'].get('label')!=row['menu_icon_text']:
                    raise ValueError('Menu companion label differs: '+row['menu_a7look'])
    if (library/'catalog.csv').is_file():values['catalog.csv']=library/'catalog.csv'
    for name in ('README.zh-CN.md','NATIVE-COLOR-COMPARISON.md','NATIVE-ALGORITHM-COMPARISON.md'):
        if (library/name).is_file():values[name]=library/name
    return values

def default_files(root=ROOT,*,verify_pairs=True):
    """Select the six Windows defaults without changing the full source library."""
    import csv
    import sys
    root=Path(root);library=root/'desktop-assets/profile-library-v1'
    sys.path[:0]=[str(root/'src'),str(root/'src/looks')]
    from looktool.looklabels import defaults
    document=json.loads((library/'catalog.json').read_text(encoding='utf-8'))
    by_name={row['name']:row for row in document['profiles']}
    rows=[by_name[row['name']] for row in defaults()]
    document={key:document[key] for key in ('schema','desktop_version','native_source_release',
              'native_refitting_repeated','physical_color_accuracy_verified') if key in document}
    document.update(schema='a7c2-profile-library/2',count=len(rows),profiles=rows,distribution='windows-default-six')
    values=files(root,verify_pairs=verify_pairs,document=document)
    # Derived metadata is small; the selected color files remain untouched.
    metadata=root/'build/desktop-default-profiles';metadata.mkdir(parents=True,exist_ok=True)
    catalog=metadata/'catalog.json'
    catalog.write_text(json.dumps(document,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    csv_path=metadata/'catalog.csv'
    columns=['name','dcp','a7look','menu_a7look','menu_icon_text']
    with csv_path.open('w',encoding='utf-8',newline='')as output:
        writer=csv.DictWriter(output,columns,extrasaction='ignore');writer.writeheader();writer.writerows(rows)
    readme=metadata/'README.zh-CN.md'
    readme.write_text('# 3.10 Windows 默认六款\n\n'+''.join(
        '- '+row['name']+' / '+row['menu_icon_text']+'\n'for row in rows)+
        '\n每款包含配对DCP、普通A7Look和MenuIcons图标副本。完整41款单独供云创分发。\n',encoding='utf-8')
    selected={key:value for key,value in values.items()if Path(key).suffix.lower()in ('.dcp','.a7look')}
    selected.update({'catalog.json':catalog,'catalog.csv':csv_path,'README.zh-CN.md':readme})
    return selected


def archive_values(archive):
    """Read only exact library paths from exported assets or a desktop ZIP."""
    names=archive.namelist()
    candidates=[name for name in names if name.endswith('/profile-library-v1/catalog.json') or
                name=='profile-library-v1/catalog.json' or name.endswith('/Profiles/catalog.json')]
    if len(candidates)!=1:raise ValueError('Build inputs must include one accepted paired-profile library')
    prefix=candidates[0][:-len('catalog.json')]
    document=json.loads(archive.read(prefix+'catalog.json'))
    expected=paired_paths(document)
    relative=['catalog.json']+[name for pair in sorted(expected) for name in pair]
    relative+=menu_paths(document)
    if prefix+'catalog.csv' in names:relative.append('catalog.csv')
    return {name:archive.read(prefix+name) for name in relative}
