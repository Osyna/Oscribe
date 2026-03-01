import random
import subprocess

from PyQt6.QtCore import QPointF, QRectF, Qt, QTimer, pyqtSignal, pyqtSlot
from PyQt6.QtGui import QColor, QPainter, QPen
from PyQt6.QtWidgets import QApplication, QWidget


class RecordingWindow(QWidget):
    stop_signal = pyqtSignal()

    NUM_BARS = 24
    BAR_WIDTH = 3
    BAR_GAP = 2
    SMOOTHING = 0.32

    def __init__(self):
        super().__init__()
        self.setWindowTitle("LiveTranscriberOverlay")
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setFixedSize(220, 56)

        self.state = "recording"
        self.pulse_phase = 0
        self.energy_level = 0.0

        # Equalizer
        self.bar_heights = [0.0] * self.NUM_BARS
        self.bar_targets = [0.0] * self.NUM_BARS
        self._target_tick = 0

        # Loader
        self.load_angle = 0.0

        # Done
        self.done_progress = 0.0

        # Position
        self._placement = "bottom_center"
        self._padding = 32

        # Animation
        self.timer = QTimer(self)
        self.timer.timeout.connect(self._tick)
        self.timer.start(30)

    def position(self, placement="bottom_center", padding=32):
        self._placement = placement
        self._padding = padding
        self._apply_position()

    def _apply_position(self):
        screen = QApplication.primaryScreen().geometry()
        sw, sh = screen.width(), screen.height()
        ww, wh = self.width(), self.height()
        p = self._padding

        positions = {
            "top_left": (p, p),
            "top_center": ((sw - ww) // 2, p),
            "top_right": (sw - ww - p, p),
            "center": ((sw - ww) // 2, (sh - wh) // 2),
            "bottom_left": (p, sh - wh - p),
            "bottom_center": ((sw - ww) // 2, sh - wh - p),
            "bottom_right": (sw - ww - p, sh - wh - p),
        }

        x, y = positions.get(self._placement, positions["bottom_center"])
        self.move(x, y)

    def showEvent(self, event):
        super().showEvent(event)
        # Reapply position after window is mapped (Wayland ignores move before show)
        QTimer.singleShot(10, self._apply_position)
        # Hyprland fallback: force position via hyprctl after window appears
        QTimer.singleShot(50, self._hyprctl_move)

    def _hyprctl_move(self):
        screen = QApplication.primaryScreen().geometry()
        sw, sh = screen.width(), screen.height()
        ww, wh = self.width(), self.height()
        p = self._padding

        positions = {
            "top_left": (p, p),
            "top_center": ((sw - ww) // 2, p),
            "top_right": (sw - ww - p, p),
            "center": ((sw - ww) // 2, (sh - wh) // 2),
            "bottom_left": (p, sh - wh - p),
            "bottom_center": ((sw - ww) // 2, sh - wh - p),
            "bottom_right": (sw - ww - p, sh - wh - p),
        }

        x, y = positions.get(self._placement, positions["bottom_center"])
        try:
            subprocess.Popen(
                [
                    "hyprctl",
                    "dispatch",
                    "movewindowpixel",
                    f"exact {x} {y},title:LiveTranscriberOverlay",
                ],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        except FileNotFoundError:
            pass

    @pyqtSlot(str)
    def set_state(self, state):
        self.state = state
        self.pulse_phase = 0
        if state == "done":
            self.done_progress = 0.0
        if state in ("recording", "analysing"):
            self.load_angle = 0.0
        if not self.timer.isActive():
            self.timer.start(30)
        self.update()

    def set_energy(self, energy):
        self.energy_level = min(1.0, max(0.0, energy))

    # ── animation ───────────────────────────────────────────────────

    def _tick(self):
        self.pulse_phase += 1
        if self.state == "recording":
            self._update_bars()
        elif self.state == "analysing":
            self.load_angle = (self.load_angle + 5) % 360
        elif self.state == "done":
            self.done_progress = min(1.0, self.done_progress + 0.07)
            if self.done_progress >= 1.0 and self.pulse_phase > 40:
                self.timer.stop()
        self.update()

    def _update_bars(self):
        self._target_tick += 1
        if self._target_tick >= 2:
            self._target_tick = 0
            e = self.energy_level
            center = self.NUM_BARS / 2.0
            for i in range(self.NUM_BARS):
                if e > 0.05:
                    dist = abs(i - center) / center
                    base = e * (1.0 - dist * 0.5)
                    self.bar_targets[i] = min(1.0, base * random.uniform(0.3, 1.0))
                else:
                    self.bar_targets[i] = random.uniform(0.02, 0.08)

        for i in range(self.NUM_BARS):
            diff = self.bar_targets[i] - self.bar_heights[i]
            speed = self.SMOOTHING if diff > 0 else self.SMOOTHING * 0.45
            self.bar_heights[i] += diff * speed

    # ── painting ────────────────────────────────────────────────────

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)

        # Black background, sharp rectangle
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(0, 0, 0, 240))
        p.drawRect(self.rect())

        if self.state == "recording":
            self._draw_eq(p)
        elif self.state == "analysing":
            self._draw_loader(p)
        elif self.state == "done":
            self._draw_done(p)

        p.end()

    # ── recording: equalizer ────────────────────────────────────────

    def _draw_eq(self, p):
        eq_w = self.NUM_BARS * (self.BAR_WIDTH + self.BAR_GAP) - self.BAR_GAP
        sx = (self.width() - eq_w) / 2
        top = 10
        bot = self.height() - 10
        max_h = bot - top

        p.setPen(Qt.PenStyle.NoPen)
        for i in range(self.NUM_BARS):
            h = max(2, self.bar_heights[i] * max_h)
            x = sx + i * (self.BAR_WIDTH + self.BAR_GAP)
            y = bot - h

            intensity = self.bar_heights[i]
            alpha = int(100 + 155 * intensity)

            p.setBrush(QColor(255, 255, 255, alpha))
            p.drawRect(QRectF(x, y, self.BAR_WIDTH, h))

    # ── analysing: spinner ──────────────────────────────────────────

    def _draw_loader(self, p):
        cx = self.width() / 2
        cy = self.height() / 2
        r = 14

        # track
        p.setPen(QPen(QColor(255, 255, 255, 25), 2))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawEllipse(QPointF(cx, cy), r, r)

        arc_rect = QRectF(cx - r, cy - r, r * 2, r * 2)

        # primary arc
        pen1 = QPen(QColor(255, 255, 255, 220), 2)
        pen1.setCapStyle(Qt.PenCapStyle.RoundCap)
        p.setPen(pen1)
        p.drawArc(arc_rect, int(self.load_angle * 16), int(90 * 16))

        # secondary arc
        pen2 = QPen(QColor(255, 255, 255, 60), 2)
        pen2.setCapStyle(Qt.PenCapStyle.RoundCap)
        p.setPen(pen2)
        p.drawArc(arc_rect, int((self.load_angle + 180) * 16), int(55 * 16))

    # ── done: animated checkmark ────────────────────────────────────

    def _draw_done(self, p):
        cx = self.width() / 2
        cy = self.height() / 2
        prog = self.done_progress

        alpha = int(255 * min(1.0, prog * 2.5))
        pen = QPen(QColor(255, 255, 255, alpha), 2.5)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        p.setPen(pen)

        pt1 = QPointF(cx - 9, cy + 1)
        pt2 = QPointF(cx - 3, cy + 8)
        pt3 = QPointF(cx + 10, cy - 6)

        if prog < 0.4:
            t = prog / 0.4
            end = QPointF(
                pt1.x() + (pt2.x() - pt1.x()) * t,
                pt1.y() + (pt2.y() - pt1.y()) * t,
            )
            p.drawLine(pt1, end)
        else:
            p.drawLine(pt1, pt2)
            t = min(1.0, (prog - 0.4) / 0.6)
            end = QPointF(
                pt2.x() + (pt3.x() - pt2.x()) * t,
                pt2.y() + (pt3.y() - pt2.y()) * t,
            )
            p.drawLine(pt2, end)

    # ── input ───────────────────────────────────────────────────────

    def keyPressEvent(self, event):
        if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            self.stop_signal.emit()
