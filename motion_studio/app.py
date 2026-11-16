"""Main window, laid out like Filmora: library (top-left), player (top-centre),
properties (top-right) and the timeline across the bottom."""
from __future__ import annotations

import os
import sys

from PySide6.QtCore import QObject, Qt, QThread, Signal
from PySide6.QtGui import QAction, QKeySequence
from PySide6.QtWidgets import (QApplication, QButtonGroup, QDialog, QDialogButtonBox, QFileDialog, QLabel,
                               QMainWindow, QMessageBox, QProgressDialog, QPushButton, QRadioButton,
                               QSplitter, QVBoxLayout, QWidget)

from . import __version__
from .document import Document
from .effects import Phase
from .export import FORMATS, Cancelled, export
from .library import LibraryPanel, sticker_source
from .player import PlayerPanel, timecode
from .properties import PropertiesPanel
from .scene import ObjectSource
from .theme import STYLE
from .timeline import Timeline
from .timeline_view import TimelinePanel

APP_NAME = 'Motion Studio'
EXT = '.msproj'


class ExportWorker(QObject):
    progress = Signal(int, int)
    finished = Signal(str, str)

    def __init__(self, data: dict, path: str, fmt: str):
        super().__init__()
        self.data, self.path, self.fmt = data, path, fmt
        self.cancel = False

    def run(self):
        try:
            tl = Timeline.from_dict(self.data)

            def cb(done, total):
                self.progress.emit(done, total)
                return not self.cancel
            export(tl, self.path, self.fmt, cb)
            self.finished.emit(self.path, '')
        except Cancelled:
            self.finished.emit(self.path, 'cancelled')
        except Exception as exc:
            self.finished.emit(self.path, str(exc))


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.doc = Document()
        self._thread = None

        self.library = LibraryPanel()
        self.player = PlayerPanel(self.doc)
        self.props = PropertiesPanel(self.doc)
        self.timeline = TimelinePanel(self.doc)

        top = QSplitter(Qt.Orientation.Horizontal)
        top.addWidget(self.library)
        top.addWidget(self.player)
        top.addWidget(self.props)
        top.setStretchFactor(0, 4)
        top.setStretchFactor(1, 5)
        top.setStretchFactor(2, 3)
        top.setSizes([600, 700, 400])
        main = QSplitter(Qt.Orientation.Vertical)
        main.addWidget(top)
        main.addWidget(self.timeline)
        main.setSizes([560, 300])
        self.setCentralWidget(main)

        self.library.activated.connect(self._library_item)
        self.props.message.connect(self._msg)
        self.props.library_changed.connect(self.library.refresh)
        self.timeline.message.connect(self._msg)
        self.doc.changed.connect(self._title)

        self._menus()
        self._starter()
        self._title()
        self.resize(1600, 940)

    # ---- setup

    def _menus(self):
        mb = self.menuBar()
        file_m = mb.addMenu('&File')
        edit_m = mb.addMenu('&Edit')
        play_m = mb.addMenu('&Play')

        def act(menu, text, key, fn):
            a = QAction(text, self)
            if key:
                a.setShortcut(key)
                a.setShortcutContext(Qt.ShortcutContext.WindowShortcut)
            a.triggered.connect(fn)
            menu.addAction(a)
            return a

        act(file_m, 'New project', QKeySequence.StandardKey.New, self.new_project)
        act(file_m, 'Open project…', QKeySequence.StandardKey.Open, self.open_project)
        act(file_m, 'Save project', QKeySequence.StandardKey.Save, self.save_project)
        act(file_m, 'Save project as…', QKeySequence.StandardKey.SaveAs, lambda: self.save_project(True))
        file_m.addSeparator()
        act(file_m, 'Export…', 'Ctrl+E', self.export_dialog)
        file_m.addSeparator()
        act(file_m, 'Quit', QKeySequence.StandardKey.Quit, self.close)
        act(edit_m, 'Undo', QKeySequence.StandardKey.Undo, self.doc.undo)
        act(edit_m, 'Redo', 'Ctrl+Y', self.doc.redo)
        edit_m.addSeparator()
        act(edit_m, 'Delete', QKeySequence.StandardKey.Delete, self.doc.delete_selected)
        act(edit_m, 'Duplicate', 'Ctrl+D', self.doc.duplicate_selected)
        act(edit_m, 'Split at playhead', 'Ctrl+B', self.timeline._split)
        act(edit_m, 'Add track', None, self.doc.add_track)
        act(play_m, 'Play / pause', 'Space', self.player.toggle)
        act(play_m, 'Previous frame', 'Left', lambda: self.player.step(-1))
        act(play_m, 'Next frame', 'Right', lambda: self.player.step(1))
        act(play_m, 'Go to start', 'Home', self.player.stop_to_start)

        export_btn = QPushButton('Export')
        export_btn.setProperty('accent', True)
        export_btn.setMinimumWidth(110)
        export_btn.clicked.connect(self.export_dialog)
        holder = QWidget()
        hl = QVBoxLayout(holder)
        hl.setContentsMargins(0, 2, 10, 2)
        hl.addWidget(export_btn)
        mb.setCornerWidget(holder, Qt.Corner.TopRightCorner)

    def _starter(self):
        """Open with one example sticker so there is something to play."""
        src = ObjectSource(kind='svg', path='builtin:star')
        src.load()
        clip = self.doc.add_sticker(src, start=0.0, track=0, duration=4.0)
        clip.trans_in = Phase(effect='Slow bounce', direction='up', duration=1.2, bounces=2)
        self.doc._undo.clear()
        self.doc.dirty = False
        self.doc.changed.emit()

    def _title(self):
        name = os.path.basename(self.doc.path) if self.doc.path else 'Untitled'
        self.setWindowTitle(f'{name}{" •" if self.doc.dirty else ""} — {APP_NAME} {__version__}')

    def _msg(self, text):
        self.statusBar().showMessage(text, 5000)

    # ---- library

    def _library_item(self, item: dict):
        clip = self.doc.selected()
        if item['kind'] == 'sticker':
            try:
                self.doc.add_sticker(sticker_source(item))
                self._msg(f'Added {item["name"]} at {timecode(self.doc.time, self.doc.timeline.fps)}.')
            except Exception as exc:
                QMessageBox.warning(self, APP_NAME, f'Could not add that sticker:\n{exc}')
            return
        if clip is None:
            self._msg('Select a sticker on the timeline first (or drag this onto it).')
            return
        if item['kind'] == 'transition':
            which = 'in' if clip.trans_in.effect == 'None' or clip.trans_out.effect != 'None' else 'out'
            self.doc.set_transition(clip, item['effect'], which, item.get('settings'))
            self._msg(f'{item["name"]} set as the {"In" if which == "in" else "Out"} transition of {clip.name()}.')
            self.props.show_page('Transitions')
        elif item['kind'] == 'effect':
            self.doc.add_effect(clip, item['type'], item.get('params'))
            self._msg(f'{item["name"]} added to {clip.name()}.')
            self.props.show_page('Effects')

    # ---- files

    def _confirm_discard(self) -> bool:
        if not self.doc.dirty:
            return True
        r = QMessageBox.question(self, APP_NAME, 'Save changes to this project first?',
                                 QMessageBox.StandardButton.Save | QMessageBox.StandardButton.Discard |
                                 QMessageBox.StandardButton.Cancel)
        if r == QMessageBox.StandardButton.Save:
            return self.save_project()
        return r == QMessageBox.StandardButton.Discard

    def new_project(self):
        if self._confirm_discard():
            self.player.pause()
            self.doc.new()
            self._title()

    def open_project(self, path: str | None = None):
        if not self._confirm_discard():
            return
        if not path:
            path, _ = QFileDialog.getOpenFileName(self, 'Open project', '', f'{APP_NAME} project (*{EXT})')
        if not path:
            return
        try:
            self.player.pause()
            self.doc.open(path)
        except Exception as exc:
            QMessageBox.warning(self, APP_NAME, f'Could not open the project:\n{exc}')
        self._title()

    def save_project(self, save_as=False) -> bool:
        path = self.doc.path
        if save_as or not path:
            path, _ = QFileDialog.getSaveFileName(self, 'Save project', 'animation' + EXT,
                                                  f'{APP_NAME} project (*{EXT})')
            if not path:
                return False
        try:
            self.doc.save(path)
        except OSError as exc:
            QMessageBox.warning(self, APP_NAME, f'Could not save:\n{exc}')
            return False
        self._title()
        self._msg(f'Saved {path}')
        return True

    def closeEvent(self, e):
        if self._confirm_discard():
            e.accept()
        else:
            e.ignore()

    # ---- export

    def export_dialog(self):
        self.player.pause()
        tl = self.doc.timeline
        if not tl.clips:
            QMessageBox.information(self, APP_NAME, 'Add a sticker first.')
            return
        dlg = QDialog(self)
        dlg.setWindowTitle('Export')
        lay = QVBoxLayout(dlg)
        group = QButtonGroup(dlg)
        radios = {}
        for key, label in FORMATS.items():
            r = QRadioButton(label)
            radios[key] = r
            group.addButton(r)
            lay.addWidget(r)
        radios['prores'].setChecked(True)
        info = QLabel(f'{tl.width} × {tl.height}  ·  {tl.fps:g} fps  ·  {tl.duration():.2f} s  '
                      f'({tl.frame_count()} frames)  ·  transparent background')
        info.setProperty('muted', True)
        lay.addWidget(info)
        bb = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        bb.accepted.connect(dlg.accept)
        bb.rejected.connect(dlg.reject)
        lay.addWidget(bb)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        fmt = 'prores' if radios['prores'].isChecked() else 'png'
        base = os.path.splitext(os.path.basename(self.doc.path))[0] if self.doc.path else 'animation'
        if fmt == 'prores':
            path, _ = QFileDialog.getSaveFileName(self, 'Export video', base + '.mov', 'ProRes 4444 (*.mov)')
        else:
            path = QFileDialog.getExistingDirectory(self, 'Folder for the PNG frames')
        if path:
            self._run_export(path, fmt)

    def _run_export(self, path, fmt):
        tl = self.doc.timeline
        prog = QProgressDialog('Exporting…', 'Cancel', 0, tl.frame_count(), self)
        prog.setWindowModality(Qt.WindowModality.WindowModal)
        prog.setMinimumDuration(0)
        self._thread = QThread(self)
        self._worker = ExportWorker(tl.to_dict(), path, fmt)
        self._worker.moveToThread(self._thread)
        self._thread.started.connect(self._worker.run)
        self._worker.progress.connect(lambda d, t: prog.setValue(d))
        prog.canceled.connect(lambda: setattr(self._worker, 'cancel', True))

        def done(p, err):
            prog.close()
            self._thread.quit()
            self._thread.wait()
            if err == 'cancelled':
                self._msg('Export cancelled.')
            elif err:
                QMessageBox.warning(self, APP_NAME, f'Export failed:\n{err}')
            else:
                self._msg(f'Exported {p}')
                QMessageBox.information(self, APP_NAME, f'Exported:\n{p}')
        self._worker.finished.connect(done)
        self._thread.start()


def main():
    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setOrganizationName('StrokeDot')
    app.setStyle('Fusion')
    app.setStyleSheet(STYLE)
    w = MainWindow()
    w.show()
    if len(sys.argv) > 1 and sys.argv[1].endswith(EXT):
        w.doc.dirty = False
        w.open_project(sys.argv[1])
    sys.exit(app.exec())
