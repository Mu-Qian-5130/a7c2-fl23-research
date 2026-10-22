"""Build-time paired library; mono entries require accepted independent errors."""
import json
from pathlib import Path

ROOT=Path(__file__).resolve().parents[2]
FUJI=('Astia','Bleach_Bypass','Classic_Chrome','Classic_Negative','Eterna',
      'Nostalgic_Negative','Pro_Neg_Hi','Pro_Neg_Std','Provia','Reala_Ace','Velvia')
RICOH=('Hard Monotone','Monotone','Negative Film','Positive Film','Soft Monotone','Standard','Vivid')
PAIRS=tuple(('Fujifilm','Sony_ILCE-7CM2_'+name) for name in FUJI)+tuple(
    ('Ricoh GR III','Sony_ILCE-7CM2 RICOH GR III Camera '+name+' (GR Look, a7C2 WB)') for name in RICOH)
MONO=('Hard Monotone','Monotone','Soft Monotone')
OPTIONAL={('Ricoh GR III/Sony_ILCE-7CM2 RICOH GR III Camera '+name+' (GR Look, a7C2 WB).dcp',
           'Ricoh GR III/Sony_ILCE-7CM2 RICOH GR III Camera '+name+' (GR Look, a7C2 WB).a7look') for name in MONO}

def paired_paths(document):
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

def files(root=ROOT,*,verify_pairs=True):
    root=Path(root);library=root/'desktop-assets/profile-library-v1'
    catalog=library/'catalog.json'
    if not catalog.is_file():raise FileNotFoundError('Prepare the accepted paired-profile library before packaging: '+str(library))
    document=json.loads(catalog.read_text(encoding='utf-8'))
    paired_paths(document)
    rows=document['profiles']
    values={'catalog.json':catalog}
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
    if (library/'catalog.csv').is_file():values['catalog.csv']=library/'catalog.csv'
    return values

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
    if prefix+'catalog.csv' in names:relative.append('catalog.csv')
    return {name:archive.read(prefix+name) for name in relative}
