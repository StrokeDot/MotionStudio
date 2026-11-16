"""Built-in stickers (simple original vector shapes) and text sticker presets,
plus the "Mine" folder where your own sticker files are kept."""
from __future__ import annotations

import math
import os
import shutil

from PySide6.QtCore import QStandardPaths


def _star(points=5, inner=0.45, fill='#ffd23f', stroke='#1b1b1b'):
    pts = []
    for i in range(points * 2):
        r = 48 if i % 2 == 0 else 48 * inner
        a = math.pi / points * i - math.pi / 2
        pts.append(f'{50 + r * math.cos(a):.1f},{50 + r * math.sin(a):.1f}')
    return (f'<polygon points="{" ".join(pts)}" fill="{fill}" stroke="{stroke}" '
            f'stroke-width="3" stroke-linejoin="round"/>')


_SHAPES = {
    'star': _star(),
    'sparkle': _star(4, 0.28, '#fff6b0', '#d9a400'),
    'burst': _star(12, 0.72, '#ff5a3c', '#7a1300') +
             '<text x="50" y="58" font-family="Arial" font-weight="bold" font-size="22" '
             'text-anchor="middle" fill="#fff">NEW</text>',
    'heart': '<path d="M50 88 C20 66 6 50 6 32 C6 18 17 8 30 8 C40 8 46 14 50 22 C54 14 60 8 70 8 '
             'C83 8 94 18 94 32 C94 50 80 66 50 88 Z" fill="#ff3d6e" stroke="#7a0024" stroke-width="3"/>',
    'circle': '<circle cx="50" cy="50" r="44" fill="#3ab0ff" stroke="#0b3d66" stroke-width="4"/>',
    'arrow': '<path d="M8 40 H60 V22 L94 50 L60 78 V60 H8 Z" fill="#ffffff" stroke="#111" '
             'stroke-width="4" stroke-linejoin="round"/>',
    'curved_arrow': '<path d="M14 80 C14 40 40 22 70 24 V10 L94 32 L70 54 V40 C46 38 30 52 30 80 Z" '
                    'fill="#ffd23f" stroke="#111" stroke-width="3" stroke-linejoin="round"/>',
    'check': '<circle cx="50" cy="50" r="44" fill="#27c46b"/><path d="M28 52 L44 68 L74 34" '
             'fill="none" stroke="#fff" stroke-width="10" stroke-linecap="round" stroke-linejoin="round"/>',
    'cross': '<circle cx="50" cy="50" r="44" fill="#e5383b"/><path d="M33 33 L67 67 M67 33 L33 67" '
             'stroke="#fff" stroke-width="10" stroke-linecap="round"/>',
    'speech_bubble': '<path d="M12 14 H88 Q94 14 94 20 V62 Q94 68 88 68 H44 L24 88 L28 68 H12 '
                     'Q6 68 6 62 V20 Q6 14 12 14 Z" fill="#fff" stroke="#111" stroke-width="3"/>',
    'thought_bubble': '<ellipse cx="54" cy="40" rx="40" ry="28" fill="#fff" stroke="#111" stroke-width="3"/>'
                      '<circle cx="24" cy="76" r="8" fill="#fff" stroke="#111" stroke-width="3"/>'
                      '<circle cx="12" cy="92" r="5" fill="#fff" stroke="#111" stroke-width="3"/>',
    'banner': '<path d="M2 30 L16 30 L16 70 L2 70 L10 50 Z M98 30 L84 30 L84 70 L98 70 L90 50 Z" '
              'fill="#a3122a"/><rect x="12" y="24" width="76" height="40" rx="3" fill="#e01e3c" '
              'stroke="#7a0c1f" stroke-width="2"/>',
    'label': '<rect x="4" y="30" width="92" height="40" rx="20" fill="#20d3b0" stroke="#0b5c4c" '
             'stroke-width="3"/>',
    'lightning': '<path d="M58 4 L18 56 H46 L38 96 L82 40 H54 Z" fill="#ffd23f" stroke="#111" '
                 'stroke-width="3" stroke-linejoin="round"/>',
    'sun': ''.join(f'<rect x="47" y="2" width="6" height="16" rx="3" fill="#ffb627" '
                   f'transform="rotate({a} 50 50)"/>' for a in range(0, 360, 45)) +
           '<circle cx="50" cy="50" r="24" fill="#ffd23f" stroke="#e08e00" stroke-width="3"/>',
    'cloud': '<path d="M26 78 H76 C88 78 96 70 96 58 C96 46 86 38 74 40 C70 26 58 18 44 22 '
             'C34 25 28 33 27 42 C14 42 4 50 4 60 C4 70 13 78 26 78 Z" fill="#fff" stroke="#9aa7b5" '
             'stroke-width="3"/>',
    'music_note': '<path d="M38 72 V18 L82 8 V62" fill="none" stroke="#fff" stroke-width="7" '
                  'stroke-linejoin="round"/><ellipse cx="28" cy="74" rx="13" ry="10" fill="#fff"/>'
                  '<ellipse cx="72" cy="64" rx="13" ry="10" fill="#fff"/>',
    'pin': '<path d="M50 96 C30 66 18 52 18 36 A32 32 0 0 1 82 36 C82 52 70 66 50 96 Z" fill="#e5383b" '
           'stroke="#6b0c0e" stroke-width="3"/><circle cx="50" cy="36" r="12" fill="#fff"/>',
}

SHAPE_CATEGORIES = {
    'Shapes': ['star', 'heart', 'circle', 'sparkle', 'burst', 'lightning', 'sun', 'cloud', 'music_note', 'pin'],
    'Arrows': ['arrow', 'curved_arrow'],
    'Signs': ['check', 'cross', 'speech_bubble', 'thought_bubble', 'banner', 'label'],
}


def builtin_svg(name: str) -> str:
    body = _SHAPES.get(name, _SHAPES['star'])
    return f'<svg xmlns="http://www.w3.org/2000/svg" width="400" height="400" viewBox="0 0 100 100">{body}</svg>'


TEXT_PRESETS = {
    'Title': dict(text='Title', family='Segoe UI', size=140, bold=True, color='#ffffff',
                  outline_color='#000000', outline_width=8),
    'Handwritten': dict(text='Hello', family='Segoe Script', size=130, bold=False, color='#e8213c',
                        outline_color='#ffffff', outline_width=4),
    'Yellow pop': dict(text='WOW!', family='Impact', size=160, bold=False, color='#ffd23f',
                       outline_color='#1b1b1b', outline_width=10),
    'Clean': dict(text='Your text', family='Segoe UI', size=110, bold=False, color='#ffffff',
                  outline_color='#000000', outline_width=0),
    'Dark': dict(text='Caption', family='Segoe UI', size=100, bold=True, color='#1b1b1b',
                 outline_color='#ffffff', outline_width=6),
}


def mine_dir() -> str:
    d = os.path.join(QStandardPaths.writableLocation(QStandardPaths.StandardLocation.AppDataLocation),
                     'stickers')
    os.makedirs(d, exist_ok=True)
    return d


def import_sticker(path: str) -> str:
    """Copy a file into the Mine folder (renaming on clashes); returns the copy's path."""
    base = os.path.basename(path)
    stem, ext = os.path.splitext(base)
    dest = os.path.join(mine_dir(), base)
    n = 2
    while os.path.exists(dest):
        dest = os.path.join(mine_dir(), f'{stem} ({n}){ext}')
        n += 1
    shutil.copy2(path, dest)
    return dest


def mine_files() -> list[str]:
    exts = {'.png', '.jpg', '.jpeg', '.webp', '.svg', '.gif', '.bmp', '.tif', '.tiff'}
    d = mine_dir()
    return sorted(os.path.join(d, f) for f in os.listdir(d) if os.path.splitext(f)[1].lower() in exts)
