"""Builds the JSON description of every parameter/control widget from the layout data files."""
from typing import Dict, Any

from app.web.layout.common import COMMON_LAYOUT_DATA
from app.web.layout.swapper import SWAPPER_LAYOUT_DATA
from app.web.layout.face_editor import FACE_EDITOR_LAYOUT_DATA
from app.web.layout.settings import SETTINGS_LAYOUT_DATA

# Tab id -> (title, layout data, data_type). 'parameter' values are stored per target face,
# 'control' values are global settings.
TABS = [
    ('swap', 'Face Swap', SWAPPER_LAYOUT_DATA, 'parameter'),
    ('editor', 'Face Editor', FACE_EDITOR_LAYOUT_DATA, 'parameter'),
    ('common', 'Common', COMMON_LAYOUT_DATA, 'parameter'),
    ('settings', 'Settings', SETTINGS_LAYOUT_DATA, 'control'),
]


def widget_type(name: str) -> str:
    """Same precedence the original Qt layout builder used."""
    if 'Toggle' in name:
        return 'toggle'
    if 'Selection' in name:
        return 'select'
    if 'DecimalSlider' in name:
        return 'decimal'
    if 'Slider' in name:
        return 'slider'
    if 'Text' in name:
        return 'text'
    raise ValueError(f'Unknown widget type for {name}')


def _resolve(value):
    return value() if callable(value) else value


def build_widget(name: str, data: Dict[str, Any], data_type: str) -> Dict[str, Any]:
    wtype = widget_type(name)
    w: Dict[str, Any] = {
        'name': name,
        'type': wtype,
        'kind': data_type,
        'level': data.get('level', 1),
        'label': data.get('label', name),
        'help': data.get('help', ''),
    }
    if wtype == 'toggle':
        w['default'] = bool(data['default'])
    elif wtype == 'select':
        w['options'] = list(_resolve(data['options']))
        w['default'] = _resolve(data['default'])
    elif wtype == 'decimal':
        w.update(min=float(data['min_value']), max=float(data['max_value']), default=float(data['default']),
                 step=float(data['step']), decimals=int(data['decimals']))
    elif wtype == 'slider':
        w.update(min=int(data['min_value']), max=int(data['max_value']), default=int(data['default']),
                 step=int(data['step']))
    elif wtype == 'text':
        w['default'] = data['default']
        w['width'] = data.get('width', 130)
    for key in ('parentToggle', 'requiredToggleValue', 'parentSelection', 'requiredSelectionValue'):
        if key in data:
            w[key] = data[key]
    fn = data.get('exec_function')
    if fn:
        w['exec'] = fn if isinstance(fn, str) else getattr(fn, '__name__', '')
    return w


def build_schema() -> Dict[str, Any]:
    tabs = []
    flat: Dict[str, Dict[str, Any]] = {}
    for tab_id, title, layout, data_type in TABS:
        groups = []
        for group_name, widgets in layout.items():
            items = []
            for name, data in widgets.items():
                w = build_widget(name, data, data_type)
                items.append(w)
                flat[name] = w
            groups.append({'title': group_name, 'widgets': items})
        tabs.append({'id': tab_id, 'title': title, 'kind': data_type, 'groups': groups})
    return {'tabs': tabs, 'flat': flat}
