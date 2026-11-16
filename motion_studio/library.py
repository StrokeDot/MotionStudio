"""Top-left library: Transitions / Effects / Stickers tabs, categories, search,
and a grid of cards whose thumbnails play when you hover them."""
from __future__ import annotations

import json
import os

from PySide6.QtCore import QMimeData, QPoint, QRect, QSize, QStandardPaths, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QDrag, QIcon, QLinearGradient, QPainter, QPixmap
from PySide6.QtWidgets import (QFileDialog, QHBoxLayout, QLabel, QLineEdit, QListView, QListWidget,
                               QListWidgetItem, QMessageBox, QToolButton, QVBoxLayout, QWidget)

from .effects import IN_OUT_BY_NAME, Phase
from .scene import ObjectSource, TextStyle
from .stickers import SHAPE_CATEGORIES, TEXT_PRESETS, import_sticker, mine_files
from .theme import ACCENT, MUTED, TEXT, icon
from .timeline import (EFFECT_TYPES, EFFECTS_BY_ID, TRANSITION_CATEGORIES, Clip, EffectInstance, Timeline,
                       render_timeline)

MIME = 'application/x-motionstudio-item'
THUMB = QSize(136, 77)
FRAMES = 30            # hover previews play at 30 frames a second


def presets_path() -> str:
    d = QStandardPaths.writableLocation(QStandardPaths.StandardLocation.AppDataLocation)
    os.makedirs(d, exist_ok=True)
    return os.path.join(d, 'my_presets.json')


def read_presets() -> dict:
    try:
        with open(presets_path(), encoding='utf-8') as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def write_presets(data: dict):
    with open(presets_path(), 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=2)


# ---------------------------------------------------------------- items


def sticker_source(item: dict) -> ObjectSource:
    if item['sub'] == 'text':
        return ObjectSource(kind='text', text=TextStyle(**item['payload']))
    if item['sub'] == 'builtin':
        src = ObjectSource(kind='svg', path='builtin:' + item['payload'])
        src.load()
        return src
    return ObjectSource.from_file(item['payload'])


def catalogue(kind: str) -> tuple[list[str], list[dict]]:
    """(categories, items) for one tab."""
    items = []
    presets = read_presets()
    if kind == 'transitions':
        cats = ['All'] + list(TRANSITION_CATEGORIES) + ['Mine']
        for cat, names in TRANSITION_CATEGORIES.items():
            for n in names:
                items.append({'kind': 'transition', 'name': n, 'cat': cat, 'effect': n, 'settings': None,
                              'tip': IN_OUT_BY_NAME[n].hint})
        for name, d in (presets.get('transition') or {}).items():
            items.append({'kind': 'transition', 'name': name, 'cat': 'Mine', 'effect': d.get('effect', 'Fade'),
                          'settings': d, 'tip': 'Your saved transition'})
    elif kind == 'effects':
        cats = ['All', 'Motion', 'Look', 'Mine']
        for et in EFFECT_TYPES:
            items.append({'kind': 'effect', 'name': et.name, 'cat': et.category, 'type': et.id, 'params': None,
                          'tip': et.hint})
        for name, d in (presets.get('effect') or {}).items():
            if d.get('type') in EFFECTS_BY_ID:
                items.append({'kind': 'effect', 'name': name, 'cat': 'Mine', 'type': d['type'],
                              'params': d.get('params'), 'tip': 'Your saved effect'})
    else:
        cats = ['Mine'] + list(SHAPE_CATEGORIES) + ['Text']
        items.append({'kind': 'import', 'name': 'Import', 'cat': 'Mine',
                      'tip': 'Add your own PNG, SVG or GIF to Mine'})
        for path in mine_files():
            items.append({'kind': 'sticker', 'sub': 'file', 'name': os.path.basename(path), 'cat': 'Mine',
                          'payload': path, 'tip': path})
        for cat, names in SHAPE_CATEGORIES.items():
            for n in names:
                items.append({'kind': 'sticker', 'sub': 'builtin', 'name': n.replace('_', ' ').title(),
                              'cat': cat, 'payload': n, 'tip': ''})
        for name, st in TEXT_PRESETS.items():
            items.append({'kind': 'sticker', 'sub': 'text', 'name': name, 'cat': 'Text', 'payload': st,
                          'tip': 'Text sticker; edit the words in Properties'})
    return cats, items


# ---------------------------------------------------------------- thumbnails


def _card_background(w, h) -> QPixmap:
    pm = QPixmap(w, h)
    p = QPainter(pm)
    g = QLinearGradient(0, 0, w, h)
    g.setColorAt(0, QColor('#2c3e50'))
    g.setColorAt(1, QColor('#1d2733'))
    p.fillRect(0, 0, w, h, g)
    p.end()
    return pm


def _sample_clip(tl: Timeline) -> Clip:
    src = ObjectSource(kind='svg', path='builtin:star')
    src.load()
    c = Clip(source=src, start=0, duration=2.0)
    c.fit(tl.width, tl.height, 0.45)
    return c


def thumbnail_frames(item: dict, count: int) -> list[QPixmap]:
    w, h = THUMB.width() * 2, THUMB.height() * 2
    bg = _card_background(w, h)
    tl = Timeline(width=w, height=h, fps=30)
    times = [0.0] * count
    if item['kind'] == 'import':
        pm = QPixmap(bg)
        p = QPainter(pm)
        icon('import', ACCENT, 40).paint(p, QRect(w // 2 - 32, h // 2 - 40, 64, 64))
        p.end()
        return [pm]
    if item['kind'] == 'sticker':
        try:
            src = sticker_source(item)
        except Exception:
            return [bg]
        c = Clip(source=src, start=0, duration=2.0)
        c.fit(w, h, 0.7)
        tl.clips = [c]
        times = [i * 0.1 for i in range(count)] if src.kind == 'animated' else [0.0]
    elif item['kind'] == 'transition':
        c = _sample_clip(tl)
        ph = Phase.from_dict(item['settings']) if item['settings'] else Phase(effect=item['effect'], duration=1.0)
        if not item['settings']:
            ph.direction = 'right' if item['effect'] in ('Slide', 'Wipe', 'Spin', 'Flip') else 'up'
            if item['effect'] in ('Bounce', 'Squash drop'):
                ph.direction = 'down'
        ph.effect = item['effect']
        ph.duration = 1.0
        c.trans_in = ph
        tl.clips = [c]
        times = [1.2 * i / (count - 1) for i in range(count)]
    elif item['kind'] == 'effect':
        c = _sample_clip(tl)
        c.effects = [EffectInstance(item['type'], True, dict(item.get('params') or {}))]
        tl.clips = [c]
        if EFFECTS_BY_ID[item['type']].category == 'Motion':
            cycle = float(c.effects[0].params.get('cycle', 1.0))
            times = [cycle * i / count for i in range(count)]
        else:
            times = [0.0]
    out = []
    for t in times:
        pm = QPixmap(bg)
        p = QPainter(pm)
        p.drawImage(0, 0, render_timeline(tl, t, w))
        p.end()
        out.append(pm)
    return out


def _with_plus(pm: QPixmap) -> QPixmap:
    pm = QPixmap(pm)
    p = QPainter(pm)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    r = 18
    cx, cy = pm.width() - r - 10, pm.height() - r - 10
    p.setBrush(QColor(20, 21, 25, 200))
    p.setPen(Qt.PenStyle.NoPen)
    p.drawEllipse(QPoint(cx, cy), r, r)
    p.setPen(QColor(TEXT))
    f = p.font()
    f.setPixelSize(28)
    p.setFont(f)
    p.drawText(QRect(cx - r, cy - r - 2, 2 * r, 2 * r), Qt.AlignmentFlag.AlignCenter, '+')
    p.end()
    return pm


# ---------------------------------------------------------------- grid


class Grid(QListWidget):
    add_requested = Signal(dict)

    def __init__(self):
        super().__init__()
        self.setObjectName('grid')
        self.setViewMode(QListView.ViewMode.IconMode)
        self.setIconSize(THUMB)
        self.setGridSize(QSize(THUMB.width() + 14, THUMB.height() + 36))
        self.setResizeMode(QListView.ResizeMode.Adjust)
        self.setMovement(QListView.Movement.Static)
        self.setWordWrap(True)
        self.setSpacing(4)
        self.setMouseTracking(True)
        self.setDragEnabled(True)
        self.setUniformItemSizes(True)
        self.itemEntered.connect(self._hover)
        self.itemDoubleClicked.connect(lambda it: self.add_requested.emit(it.data(Qt.ItemDataRole.UserRole)))
        self._anim_item = None
        self._anim_frames = []
        self._anim_i = 0
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._step)
        self._frame_cache: dict = {}
        self._pending = []
        self._fill = QTimer(self)
        self._fill.setSingleShot(True)
        self._fill.timeout.connect(self._fill_step)

    def set_items(self, items: list[dict]):
        """Show the cards at once with a plain placeholder, then fill in the
        thumbnails a few at a time so switching tabs never freezes the window."""
        self._stop()
        self.clear()
        self._pending = []
        blank = QIcon(_card_background(THUMB.width() * 2, THUMB.height() * 2))
        for it in items:
            li = QListWidgetItem(it['name'])
            li.setData(Qt.ItemDataRole.UserRole, it)
            li.setToolTip(it.get('tip') or '')
            key = ('still', self._key(it))
            li.setIcon(QIcon(self._frame_cache[key]) if key in self._frame_cache else blank)
            li.setTextAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
            self.addItem(li)
            if key not in self._frame_cache:
                self._pending.append(li)
        self._fill.start(0)

    def _fill_step(self):
        import time as _t
        t0 = _t.perf_counter()
        while self._pending and _t.perf_counter() - t0 < 0.012:
            li = self._pending.pop(0)
            try:
                if li is not self._anim_item:
                    li.setIcon(QIcon(self._still(li.data(Qt.ItemDataRole.UserRole))))
            except RuntimeError:          # list was cleared meanwhile
                pass
        if self._pending:
            self._fill.start(0)

    def _key(self, it):
        return json.dumps({k: v for k, v in it.items() if k != 'tip'}, sort_keys=True, default=str)

    def _still(self, it) -> QPixmap:
        key = ('still', self._key(it))
        if key not in self._frame_cache:
            frames = thumbnail_frames(it, FRAMES if it['kind'] == 'transition' else 1)
            pick = frames[min(len(frames) - 1, int(len(frames) * 0.75))] if it['kind'] == 'transition' else frames[0]
            self._frame_cache[key] = pick if it['kind'] == 'import' else _with_plus(pick)
        return self._frame_cache[key]

    def _hover(self, li: QListWidgetItem):
        if li is self._anim_item:
            return
        self._stop()
        it = li.data(Qt.ItemDataRole.UserRole)
        if it['kind'] == 'import':
            return
        key = ('anim', self._key(it))
        if key not in self._frame_cache:
            self._frame_cache[key] = [_with_plus(f) for f in thumbnail_frames(it, FRAMES)]
        frames = self._frame_cache[key]
        if len(frames) <= 1:
            return
        self._anim_item, self._anim_frames, self._anim_i = li, frames, 0
        self._timer.start(33)

    def _step(self):
        if self._anim_item is None:
            return
        self._anim_i = (self._anim_i + 1) % len(self._anim_frames)
        self._anim_item.setIcon(QIcon(self._anim_frames[self._anim_i]))

    def _stop(self):
        self._timer.stop()
        if self._anim_item is not None:
            try:
                self._anim_item.setIcon(QIcon(self._still(self._anim_item.data(Qt.ItemDataRole.UserRole))))
            except RuntimeError:
                pass
        self._anim_item = None

    def leaveEvent(self, e):
        self._stop()
        super().leaveEvent(e)

    def mousePressEvent(self, e):
        li = self.itemAt(e.position().toPoint())
        if li is not None and e.button() == Qt.MouseButton.LeftButton:
            it = li.data(Qt.ItemDataRole.UserRole)
            if it['kind'] == 'import':
                self.add_requested.emit(it)
                return
            # The "+" badge in the card's corner adds it straight away.
            r = self.visualItemRect(li)
            icon_left = r.left() + (r.width() - THUMB.width()) // 2
            plus = QRect(icon_left + THUMB.width() - 30, r.top() + THUMB.height() - 26, 30, 30)
            if plus.contains(e.position().toPoint()):
                self.add_requested.emit(it)
                return
        super().mousePressEvent(e)

    def startDrag(self, actions):
        li = self.currentItem()
        if li is None:
            return
        it = li.data(Qt.ItemDataRole.UserRole)
        if it['kind'] == 'import':
            return
        md = QMimeData()
        md.setData(MIME, json.dumps(it, default=str).encode())
        drag = QDrag(self)
        drag.setMimeData(md)
        drag.setPixmap(self._still(it).scaled(THUMB, Qt.AspectRatioMode.KeepAspectRatio,
                                              Qt.TransformationMode.SmoothTransformation))
        drag.exec(Qt.DropAction.CopyAction)


# ---------------------------------------------------------------- panel


class LibraryPanel(QWidget):
    activated = Signal(dict)

    TABS = [('transitions', 'Transitions'), ('effects', 'Effects'), ('stickers', 'Stickers')]

    def __init__(self):
        super().__init__()
        self.kind = 'transitions'
        lay = QVBoxLayout(self)
        lay.setContentsMargins(8, 6, 8, 8)
        lay.setSpacing(6)

        tabs = QHBoxLayout()
        tabs.setSpacing(4)
        self.tab_buttons = {}
        for kind, label in self.TABS:
            b = QToolButton()
            b.setText(label)
            b.setCheckable(True)
            b.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextUnderIcon)
            b.setIconSize(QSize(26, 26))
            b.setMinimumWidth(92)
            b.clicked.connect(lambda _=False, k=kind: self.show_kind(k))
            self.tab_buttons[kind] = b
            tabs.addWidget(b)
        tabs.addStretch(1)
        lay.addLayout(tabs)

        body = QHBoxLayout()
        body.setSpacing(8)
        self.categories = QListWidget()
        self.categories.setObjectName('categories')
        self.categories.setFixedWidth(124)
        self.categories.currentTextChanged.connect(lambda _: self._filter())
        body.addWidget(self.categories)

        right = QVBoxLayout()
        self.search = QLineEdit()
        self.search.setClearButtonEnabled(True)
        self.search.textChanged.connect(lambda _: self._filter())
        right.addWidget(self.search)
        self.hint = QLabel()
        self.hint.setProperty('muted', True)
        right.addWidget(self.hint)
        self.grid = Grid()
        self.grid.add_requested.connect(self._add)
        right.addWidget(self.grid, 1)
        body.addLayout(right, 1)
        lay.addLayout(body, 1)
        self.items: list[dict] = []
        self.show_kind('transitions')

    def show_kind(self, kind: str, keep_category: str | None = None):
        self.kind = kind
        for k, b in self.tab_buttons.items():
            b.setChecked(k == kind)
            b.setIcon(icon(k, ACCENT if k == kind else TEXT))
            b.setStyleSheet(f'color:{ACCENT if k == kind else TEXT};')
        cats, self.items = catalogue(kind)
        self.categories.blockSignals(True)
        self.categories.clear()
        self.categories.addItems(cats)
        self.categories.setCurrentRow(cats.index(keep_category) if keep_category in cats else 0)
        self.categories.blockSignals(False)
        self.search.setPlaceholderText(f'Search all {kind}')
        self.hint.setText({'transitions': 'Drag onto a sticker: front half = In, back half = Out.',
                           'effects': 'Drag onto a sticker, or click + to add to the selected one.',
                           'stickers': 'Drag onto the timeline, or click + to add at the playhead.'}[kind])
        self._filter()

    def refresh(self):
        self.show_kind(self.kind, self.categories.currentItem().text() if self.categories.currentItem() else None)

    def _filter(self):
        cat = self.categories.currentItem().text() if self.categories.currentItem() else 'All'
        q = self.search.text().strip().lower()
        shown = [it for it in self.items
                 if (q and q in it['name'].lower()) or (not q and (cat == 'All' or it['cat'] == cat))]
        if q:
            shown = [it for it in shown if it['kind'] != 'import']
        self.grid.set_items(shown)

    def _add(self, item: dict):
        if item['kind'] == 'import':
            paths, _ = QFileDialog.getOpenFileNames(
                self, 'Add stickers to Mine', '',
                'Stickers (*.png *.jpg *.jpeg *.webp *.svg *.gif *.bmp *.tif *.tiff)')
            for p in paths:
                try:
                    ObjectSource.from_file(p)
                    import_sticker(p)
                except Exception as exc:
                    QMessageBox.warning(self, 'Import', f'{os.path.basename(p)}: {exc}')
            self.refresh()
            return
        self.activated.emit(item)
