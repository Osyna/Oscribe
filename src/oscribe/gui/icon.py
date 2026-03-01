"""Procedural tray icon — microphone + AI sparkle motif."""
from __future__ import annotations

from PyQt6.QtCore import QPointF, QRectF, Qt
from PyQt6.QtGui import QColor, QIcon, QPainter, QPainterPath, QPen, QPixmap


def create_tray_icon() -> QIcon:
    sz = 128
    px = QPixmap(sz, sz)
    px.fill(QColor(0, 0, 0, 255))  # fully opaque black fill

    p = QPainter(px)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)

    white = QColor(255, 255, 255)

    # ── microphone (white, scaled to fill) ───────────────────────
    pen = QPen(white, 7.0)
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
    p.setPen(pen)
    p.setBrush(Qt.BrushStyle.NoBrush)

    # Capsule head — centered, large
    cap = QPainterPath()
    cap.addRoundedRect(QRectF(38, 12, 44, 60), 22, 22)
    p.drawPath(cap)

    # Cradle arc
    p.drawArc(QRectF(24, 36, 72, 52), 0, -180 * 16)

    # Stem
    p.drawLine(QPointF(60, 88), QPointF(60, 104))

    # Base
    p.drawLine(QPointF(40, 104), QPointF(80, 104))

    # ── AI sparkles ──────────────────────────────────────────────
    _draw_sparkle(p, 10, 20, 10, white)
    _draw_sparkle(p, 114, 16, 8, white)
    _draw_sparkle(p, 112, 68, 7, white)

    p.end()
    return QIcon(px)


def _draw_sparkle(p: QPainter, cx: float, cy: float, r: float, color: QColor) -> None:
    """Draw a 4-point star (AI sparkle) at (cx, cy) with radius r."""
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(color)

    nr = r * 0.28
    path = QPainterPath()
    path.moveTo(cx, cy - r)
    path.lineTo(cx + nr, cy)
    path.lineTo(cx, cy + r)
    path.lineTo(cx - nr, cy)
    path.closeSubpath()

    path2 = QPainterPath()
    path2.moveTo(cx - r, cy)
    path2.lineTo(cx, cy + nr)
    path2.lineTo(cx + r, cy)
    path2.lineTo(cx, cy - nr)
    path2.closeSubpath()

    p.drawPath(path)
    p.drawPath(path2)
