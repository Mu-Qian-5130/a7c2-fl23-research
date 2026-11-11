"""Shared full display names and portable glyph choices; no color conversion."""
import copy
from functools import lru_cache
import json
from pathlib import Path
import unicodedata


def _key(value):
    value = Path(str(value)).stem if str(value).lower().endswith(('.a7look', '.dcp', '.cube')) else str(value)
    return ''.join(c for c in unicodedata.normalize('NFKC', value).casefold() if c.isalnum())


@lru_cache(maxsize=1)
def _registry():
    path = Path(__file__).resolve().parents[1] / 'assets/look-labels-v1.json'
    data = json.loads(path.read_text(encoding='utf-8'))
    if data.get('schema') != 'a7c2-look-labels/1' or data.get('count') != len(data['looks']):
        raise ValueError('Look label registry differs')
    index = {}
    for row in data['looks']:
        if not 1 <= len(row['icon_text']) <= 4 or len(row['name'].encode('utf-8')) > 63:
            raise ValueError('Look label is outside its bounded layout')
        for alias in [row['name'], *row['aliases']]:
            key = _key(alias)
            if key in index and index[key]['id'] != row['id']:
                raise ValueError('Ambiguous look label alias: ' + alias)
            index[key] = row
    return data, index


def catalog():
    return copy.deepcopy(_registry()[0]['looks'])


def lookup(name):
    row = _registry()[1].get(_key(name))
    return copy.deepcopy(row) if row else None


def defaults():
    data = _registry()[0]
    rows = {row['id']: row for row in data['looks']}
    return [copy.deepcopy(rows[number]) for number in data['default_six']]


def full_name(name):
    row = lookup(name)
    return row['name'] if row else name


def metadata(name, *, source=None, icon_text=None, include_icon=True):
    """Keep a custom title; a known source may supply its default glyph only."""
    from . import iconfile
    row = lookup(name)
    known = row or (lookup(source) if source else None)
    title = row['name'] if row else name
    text = icon_text if icon_text is not None else known['icon_text'] if known else ''
    return title, iconfile.from_text(text) if include_icon and text else None


def relabel(document, *, include_icon=None):
    """Change presentation fields only. None retains the existing icon policy."""
    result = copy.deepcopy(document)
    row = lookup(result['name'])
    if row is None:
        raise ValueError('No reviewed label for look: ' + result['name'])
    result['name'] = row['name']
    if include_icon is None:
        include_icon = result.get('menu_icon') is not None
    if include_icon:
        from .iconfile import from_text
        result['menu_icon'] = from_text(row['icon_text'])
    else:
        result.pop('menu_icon', None)
    return result
