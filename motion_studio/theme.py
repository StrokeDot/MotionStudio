"""Colours, the dark stylesheet and small line icons drawn in code."""
from __future__ import annotations

import math

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QIcon, QPainter, QPainterPath, QPen, QPixmap, QPolygonF

BG = '#141519'
PANEL = '#1c1d22'
PANEL_2 = '#23252b'
LINE = '#2c2e35'
TEXT = '#e6e7ea'
MUTED = '#8b9099'
ACCENT = '#21d4b1'
PLAYHEAD = '#ff4b5c'
CLIP_COLORS = {'svg': '#1f6e5c', 'image': '#1f6e5c', 'animated': '#22608a', 'text': '#5a46a8'}

STYLE = f"""
QWidget {{ background:{PANEL}; color:{TEXT}; font-size:13px; }}
QMainWindow, QSplitter {{ background:{BG}; }}
QSplitter::handle {{ background:{BG}; }}
QSplitter::handle:horizontal {{ width:6px; }}
QSplitter::handle:vertical {{ height:6px; }}
QLabel {{ background:transparent; }}
QLabel[muted="true"] {{ color:{MUTED}; }}
QLabel[heading="true"] {{ color:{ACCENT}; font-size:14px; font-weight:600; }}
QLineEdit, QPlainTextEdit, QSpinBox, QDoubleSpinBox, QComboBox, QFontComboBox {{
    background:{PANEL_2}; border:1px solid {LINE}; border-radius:6px; padding:4px 6px; }}
QLineEdit:focus, QPlainTextEdit:focus, QSpinBox:focus, QDoubleSpinBox:focus {{ border-color:{ACCENT}; }}
QComboBox::drop-down {{ border:none; width:18px; }}
QAbstractSpinBox::up-button, QAbstractSpinBox::down-button {{ subcontrol-origin:border; width:14px; border:none; }}
QAbstractSpinBox[compact="true"]::up-button, QAbstractSpinBox[compact="true"]::down-button {{ width:0px; }}
QComboBox QAbstractItemView {{ background:{PANEL_2}; selection-background-color:#2f3a3a; }}
QPushButton {{ background:{PANEL_2}; border:1px solid {LINE}; border-radius:6px; padding:5px 12px; }}
QPushButton:hover {{ border-color:#454a55; }}
QPushButton:pressed {{ background:#2b2e36; }}
QPushButton[accent="true"] {{ background:{ACCENT}; color:#05231c; border:none; font-weight:600; }}
QPushButton[accent="true"]:hover {{ background:#3fe3c3; }}
QToolButton {{ background:transparent; border:none; border-radius:6px; padding:4px; }}
QToolButton:hover {{ background:#2a2c33; }}
QToolButton:checked {{ background:#25383a; }}
QListWidget {{ background:{PANEL}; border:none; outline:none; }}
QListWidget#categories::item {{ padding:9px 12px; border-radius:6px; color:#c9ccd2; }}
QListWidget#categories::item:selected {{ background:transparent; color:{ACCENT}; }}
QListWidget#categories::item:hover {{ background:#24262c; }}
QListWidget#grid::item {{ color:#c9ccd2; border-radius:8px; padding:4px; }}
QListWidget#grid::item:selected {{ background:#25383a; color:{ACCENT}; }}
QListWidget#grid::item:hover {{ background:#24262c; }}
QSlider::groove:horizontal {{ height:4px; background:#3a3d45; border-radius:2px; }}
QSlider::sub-page:horizontal {{ background:{TEXT}; border-radius:2px; }}
QSlider::handle:horizontal {{ background:{BG}; border:2px solid {TEXT}; width:12px; height:12px;
    margin:-6px 0; border-radius:8px; }}
QSlider#scrub::sub-page:horizontal {{ background:{ACCENT}; }}
QSlider#scrub::handle:horizontal {{ border-color:{TEXT}; }}
QScrollArea {{ border:none; }}
QScrollBar:vertical {{ background:transparent; width:8px; }}
QScrollBar::handle:vertical {{ background:#3a3d45; border-radius:4px; min-height:30px; }}
QScrollBar:horizontal {{ background:transparent; height:8px; }}
QScrollBar::handle:horizontal {{ background:#3a3d45; border-radius:4px; min-width:30px; }}
QScrollBar::add-line, QScrollBar::sub-line {{ width:0; height:0; }}
QTabWidget::pane {{ border:none; }}
QTabBar::tab {{ background:{PANEL_2}; color:#c9ccd2; padding:6px 16px; margin-right:4px; border-radius:6px; }}
QTabBar::tab:selected {{ background:#2e3138; color:{TEXT}; font-weight:600; }}
QCheckBox::indicator {{ width:16px; height:16px; }}
QMenuBar {{ background:{BG}; }}
QMenuBar::item:selected {{ background:#2a2c33; }}
QMenu {{ background:{PANEL_2}; border:1px solid {LINE}; }}
QMenu::item:selected {{ background:#2f3a3a; }}
QToolTip {{ background:{PANEL_2}; color:{TEXT}; border:1px solid {LINE}; }}
QProgressDialog, QDialog, QMessageBox {{ background:{PANEL}; }}
"""


def _pen(color, w=1.8):
    p = QPen(QColor(color), w)
    p.setCapStyle(Qt.PenCapStyle.RoundCap)
    p.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
    return p


def icon(name: str, color: str = TEXT, size: int = 24) -> QIcon:
    """Simple line icons, drawn on a 24-unit grid."""
    pm = QPixmap(size * 2, size * 2)
    pm.fill(Qt.GlobalColor.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.scale(size * 2 / 24, size * 2 / 24)
    p.setPen(_pen(color))
    p.setBrush(Qt.BrushStyle.NoBrush)
    c = QColor(color)
    if name == 'transitions':
        p.drawRoundedRect(QRectF(3, 5, 18, 14), 3, 3)
        p.drawLine(QPointF(12, 5), QPointF(12, 19))
        p.setBrush(c)
        p.drawPolygon(QPolygonF([QPointF(7, 9), QPointF(10.5, 12), QPointF(7, 15)]))
        p.drawPolygon(QPolygonF([QPointF(17, 9), QPointF(13.5, 12), QPointF(17, 15)]))
    elif name == 'effects':
        path = QPainterPath()
        for i in range(8):
            r = 9 if i % 2 == 0 else 3.5
            a = math.pi / 4 * i - math.pi / 2
            pt = QPointF(11 + r * math.cos(a), 12 + r * math.sin(a))
            path.moveTo(pt) if i == 0 else path.lineTo(pt)
        path.closeSubpath()
        p.drawPath(path)
        p.drawLine(QPointF(19, 3), QPointF(19, 7))
        p.drawLine(QPointF(17, 5), QPointF(21, 5))
    elif name == 'stickers':
        path = QPainterPath()
        path.moveTo(4, 7)
        path.quadTo(4, 4, 7, 4)
        path.lineTo(17, 4)
        path.quadTo(20, 4, 20, 7)
        path.lineTo(20, 13)
        path.lineTo(13, 20)
        path.lineTo(7, 20)
        path.quadTo(4, 20, 4, 17)
        path.closeSubpath()
        p.drawPath(path)
        p.drawLine(QPointF(13, 20), QPointF(13, 15))
        p.drawLine(QPointF(13, 15), QPointF(20, 13))
        p.setBrush(c)
        p.drawEllipse(QPointF(9.5, 10), 1.1, 1.1)
        p.drawEllipse(QPointF(14.5, 10), 1.1, 1.1)
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawArc(QRectF(8, 10, 8, 6), 200 * 16, 140 * 16)
    elif name == 'play':
        p.setBrush(c)
        p.drawPolygon(QPolygonF([QPointF(8, 5), QPointF(19, 12), QPointF(8, 19)]))
    elif name == 'pause':
        p.setBrush(c)
        p.drawRoundedRect(QRectF(7, 5, 3.5, 14), 1, 1)
        p.drawRoundedRect(QRectF(13.5, 5, 3.5, 14), 1, 1)
    elif name == 'stop':
        p.drawRect(QRectF(6, 6, 12, 12))
    elif name in ('prev', 'next'):
        if name == 'next':
            p.translate(24, 0)
            p.scale(-1, 1)
        p.drawLine(QPointF(7, 6), QPointF(7, 18))
        p.drawPolygon(QPolygonF([QPointF(18, 6), QPointF(10, 12), QPointF(18, 18)]))
    elif name in ('undo', 'redo'):
        if name == 'redo':
            p.translate(24, 0)
            p.scale(-1, 1)
        path = QPainterPath()
        path.moveTo(8, 9)
        path.lineTo(15, 9)
        path.cubicTo(22, 9, 22, 19, 15, 19)
        path.lineTo(10, 19)
        p.drawPath(path)
        p.drawPolyline(QPolygonF([QPointF(11, 5), QPointF(7, 9), QPointF(11, 13)]))
    elif name == 'delete':
        p.drawLine(QPointF(5, 7), QPointF(19, 7))
        p.drawPolyline(QPolygonF([QPointF(9, 7), QPointF(9.5, 4.5), QPointF(14.5, 4.5), QPointF(15, 7)]))
        p.drawPolyline(QPolygonF([QPointF(7, 7), QPointF(8, 20), QPointF(16, 20), QPointF(17, 7)]))
        p.drawLine(QPointF(10.5, 10), QPointF(10.5, 17))
        p.drawLine(QPointF(13.5, 10), QPointF(13.5, 17))
    elif name == 'split':
        p.drawEllipse(QPointF(7, 17), 2.8, 2.8)
        p.drawEllipse(QPointF(17, 17), 2.8, 2.8)
        p.drawLine(QPointF(9, 15), QPointF(17, 4))
        p.drawLine(QPointF(15, 15), QPointF(7, 4))
    elif name == 'plus':
        p.drawLine(QPointF(12, 5), QPointF(12, 19))
        p.drawLine(QPointF(5, 12), QPointF(19, 12))
    elif name == 'minus':
        p.drawLine(QPointF(5, 12), QPointF(19, 12))
    elif name == 'zoom_in' or name == 'zoom_out':
        p.drawEllipse(QPointF(12, 12), 8, 8)
        p.drawLine(QPointF(8.5, 12), QPointF(15.5, 12))
        if name == 'zoom_in':
            p.drawLine(QPointF(12, 8.5), QPointF(12, 15.5))
    elif name in ('eye', 'eye_off'):
        path = QPainterPath()
        path.moveTo(3, 12)
        path.quadTo(12, 3, 21, 12)
        path.quadTo(12, 21, 3, 12)
        p.drawPath(path)
        p.drawEllipse(QPointF(12, 12), 2.8, 2.8)
        if name == 'eye_off':
            p.drawLine(QPointF(5, 19), QPointF(19, 5))
    elif name in ('lock', 'unlock'):
        p.drawRoundedRect(QRectF(6, 11, 12, 9), 2, 2)
        if name == 'lock':
            p.drawArc(QRectF(8, 5, 8, 10), 0, 180 * 16)
            p.drawLine(QPointF(8, 10), QPointF(8, 11))
            p.drawLine(QPointF(16, 10), QPointF(16, 11))
        else:
            p.drawArc(QRectF(8, 4, 8, 10), 20 * 16, 160 * 16)
    elif name == 'camera':
        p.drawRoundedRect(QRectF(3, 7, 18, 13), 2.5, 2.5)
        p.drawPolyline(QPolygonF([QPointF(8, 7), QPointF(9.5, 4.5), QPointF(14.5, 4.5), QPointF(16, 7)]))
        p.drawEllipse(QPointF(12, 13.5), 3.6, 3.6)
    elif name == 'fullscreen':
        for sx, sy in ((1, 1), (-1, 1), (1, -1), (-1, -1)):
            p.save()
            p.translate(12, 12)
            p.scale(sx, sy)
            p.drawPolyline(QPolygonF([QPointF(-8, -3), QPointF(-8, -8), QPointF(-3, -8)]))
            p.restore()
    elif name == 'reset':
        p.drawArc(QRectF(5, 5, 14, 14), 60 * 16, 300 * 16)
        p.drawPolyline(QPolygonF([QPointF(15.5, 3.5), QPointF(16.5, 6.5), QPointF(13.5, 7.5)]))
    elif name == 'import':
        p.drawLine(QPointF(12, 4), QPointF(12, 15))
        p.drawPolyline(QPolygonF([QPointF(7.5, 10.5), QPointF(12, 15), QPointF(16.5, 10.5)]))
        p.drawPolyline(QPolygonF([QPointF(4, 15), QPointF(4, 20), QPointF(20, 20), QPointF(20, 15)]))
    elif name == 'track_add':
        p.drawRoundedRect(QRectF(3, 6, 12, 12), 2, 2)
        p.drawLine(QPointF(19, 9), QPointF(19, 17))
        p.drawLine(QPointF(15, 13), QPointF(23, 13))
    elif name == 'save':
        p.drawRoundedRect(QRectF(4, 4, 16, 16), 2, 2)
        p.drawRect(QRectF(8, 4, 8, 5))
        p.drawRect(QRectF(7, 13, 10, 7))
    p.end()
    return QIcon(pm)
