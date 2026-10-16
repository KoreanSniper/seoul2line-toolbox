from enum import Enum


class ThemeMode(Enum):
    """Keep bool-based tools compatible with the three named themes."""
    DARK = 'dark'
    LIGHT = 'light'
    GREEN = 'green'

    def __bool__(self):
        return self is ThemeMode.DARK


THEME_LABELS = {'dark': '어두운 모드', 'light': '밝은 모드', 'green': '그린 모드'}

_PALETTES = {
    'dark': {
        'app': '#17040c', 'sidebar': '#030817', 'nav': '#2b0613',
        'panel': '#28080f', 'panel_soft': '#300a13', 'surface': '#220912',
        'surface_hover': '#43101a', 'field': '#110914',
        'border': '#7c1c27', 'border_soft': '#4c1823',
        'text': '#fcf9f2', 'muted': '#c9bfc5', 'subtle': '#bdb5c1',
        'accent': '#ffba08', 'accent_text': '#17040c', 'accent_soft': '#451018',
        'danger': '#ff8791', 'warning': '#ffba08', 'secondary': '#dc2f02',
        'highlight': '#ffba08', 'danger_hover': '#d00000',
        'sidebar_text': '#fcf9f2', 'sidebar_muted': '#c0c0cc',
        'header': '#030817', 'nav_title': '#fcf9f2',
        'selection': '#950811', 'selection_end': '#d32105', 'selection_text': '#fff9ee',
        'nav_idle': '#110914', 'nav_idle_text': '#fcf9f2',
        'sidebar_idle': '#030817', 'sidebar_border': '#50333b',
        'hero_start': '#3a090f', 'hero_end': '#160711', 'hero_glow': '#a62008',
        'card_start': '#310b12', 'card_end': '#200a14',
        'icon_start': '#8f0b08', 'icon_end': '#650710', 'icon_ink': '#ffba08',
        'brand': '#ffad08', 'hero_accent': '#ffb515', 'action_ink': '#ffba08',
        'card_accent': '#ffbd28', 'search_border': '#bd1031',
    },
    'light': {
        'app': '#fffaf6', 'sidebar': '#fffaf6', 'nav': '#fff1e8',
        'panel': '#fffaf4', 'panel_soft': '#fff2e9', 'surface': '#fffaf5',
        'surface_hover': '#ffeddf', 'field': '#fffaf7',
        'border': '#ffbfa8', 'border_soft': '#f0dcd1',
        'text': '#080c30', 'muted': '#565967', 'subtle': '#626574',
        'accent': '#a9004d', 'accent_text': '#ffffff', 'accent_soft': '#ffe4eb',
        'danger': '#b51c42', 'danger_hover': '#8e1234', 'warning': '#a64200',
        'secondary': '#c44100', 'highlight': '#e3004d',
        'sidebar_text': '#080c30', 'sidebar_muted': '#575966',
        'header': '#fffaf6', 'nav_title': '#90003d',
        'selection': '#f00052', 'selection_end': '#ff7117', 'selection_text': '#ffffff',
        'nav_idle': '#fff9f3', 'nav_idle_text': '#080c30',
        'sidebar_idle': '#fffaf6', 'sidebar_border': '#eeded4',
        'hero_start': '#fffaf5', 'hero_end': '#fff8f1', 'hero_glow': '#fff0c7',
        'card_start': '#fffaf5', 'card_end': '#fff8f0',
        'icon_start': '#ffe3e4', 'icon_end': '#ffe1c6', 'icon_ink': '#e0004d',
        'brand': '#ad0053', 'hero_accent': '#e40047', 'action_ink': '#e95b00',
        'card_accent': '#a9004d', 'search_border': '#ff6576',
        'selection_icon': '#ffcf22',
    },
    'green': {
        'app': '#f7f4da', 'sidebar': '#303d1b', 'nav': '#d9d8b3',
        'panel': '#fcf7df', 'panel_soft': '#f3edcf', 'surface': '#fcf7e4',
        'surface_hover': '#eee8c9', 'field': '#fcf8e6',
        'border': '#d7c79e', 'border_soft': '#b6b68c',
        'text': '#17270e', 'muted': '#4f5843', 'subtle': '#596145',
        'accent': '#304316', 'accent_text': '#fff9df', 'accent_soft': '#dce0b7',
        'danger': '#96551d', 'warning': '#96551d', 'secondary': '#a96116',
        'highlight': '#aa6011', 'sidebar_text': '#fffbe4', 'sidebar_muted': '#e0dfbd',
        'header': '#303d1b', 'nav_title': '#223611',
        'selection': '#ddaa64', 'selection_end': '#e9bd87', 'selection_text': '#24310e',
        'nav_idle': '#f3efd2', 'nav_idle_text': '#1c2b11',
        'sidebar_idle': '#303d1b', 'sidebar_border': '#7e855b',
        'hero_start': '#fcf8e0', 'hero_end': '#f6f1d7', 'hero_glow': '#fff4ce',
        'card_start': '#fcf8e4', 'card_end': '#faf5df',
        'icon_start': '#c47b24', 'icon_end': '#af621a', 'icon_ink': '#ffdc87',
        'brand': '#ffbe5b', 'hero_accent': '#aa6011', 'action_ink': '#a85b0b',
        'card_accent': '#1d2e10', 'search_border': '#92956c',
        'selection_icon': '#8d520d', 'search_field': '#4c5333',
        'search_text': '#f5f0d9', 'search_muted': '#d4d4b7',
        'shortcut_bg': '#4a5232', 'shortcut_text': '#ffcf75',
    },
}

THEME_SWATCHES = {name: tuple(dict.fromkeys([colors[key] for key in (
    'sidebar', 'nav', 'app', 'hero_start', 'card_start', 'selection',
    'hero_accent', 'brand', 'text', 'muted')] + list(colors.values())))[:10]
    for name, colors in _PALETTES.items()}


def palette(dark_mode: bool | str | ThemeMode) -> dict[str, str]:
    if isinstance(dark_mode, ThemeMode):
        name = dark_mode.value
    elif isinstance(dark_mode, str):
        name = dark_mode if dark_mode in _PALETTES else 'dark'
    else:
        name = 'dark' if dark_mode else 'light'
    return dict(_PALETTES[name])
