"""喝水杯子：卡片右侧一个竖高的马克杯，跨越「距离下班」到久坐进度条这一段。

尺寸由卡片在运行时决定，所以绘制全部按控件宽高的比例来算。
三种状态：empty / half / full；满水时水面浮动、气泡上浮、杯口橙点脉冲。
"""

from __future__ import annotations

import math

from PySide6.QtCore import QPointF, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QFont, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QWidget

WATER = QColor("#378ADD")
WATER_TOP = QColor("#85B7EB")
LINE_IDLE = QColor("#5C6C8A")
LINE_READY = QColor("#85B7EB")
CARD_BG = QColor("#28334D")
TEXT = QColor("#F2F5FA")
DOT = QColor("#FF8A4C")


class DrinkCup(QWidget):
    clicked = Signal()

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self._state = "empty"
        self._cups = 0
        self._left = 60
        self._phase = 0.0

        self._timer = QTimer(self)
        self._timer.setInterval(60)
        self._timer.timeout.connect(self._tick)

    def set_state(self, state: str, cups: int, left: int) -> None:
        changed = (state != self._state) or (cups != self._cups)
        self._state = state
        self._cups = cups
        self._left = left
        if state == "full":
            if not self._timer.isActive():
                self._timer.start()
            self.setToolTip("该喝水了")
        else:
            self._timer.stop()
            self._phase = 0.0
            self.setToolTip(f"还有 {left} 分钟该喝水了" if state == "half" else "")
        if changed:
            self.update()

    def _tick(self) -> None:
        self._phase += 0.09
        self.update()

    def paintEvent(self, event) -> None:  # noqa: N802
        w, h = float(self.width()), float(self.height())
        if w < 12 or h < 12:
            return

        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)

        body_l = w * 0.04
        body_r = w * 0.78
        body_t = h * 0.05
        body_b = h * 0.97
        radius = min(body_r - body_l, body_b - body_t) * 0.26

        full = self._state == "full"
        line = LINE_READY if self._state != "empty" else LINE_IDLE
        sway = math.sin(self._phase) * 1.4 if full else 0.0

        handle = QPainterPath()
        hx = body_r - 2
        handle.moveTo(hx, body_t + (body_b - body_t) * 0.18)
        handle.cubicTo(
            w * 0.99, body_t + (body_b - body_t) * 0.20,
            w * 0.99, body_b - (body_b - body_t) * 0.24,
            hx, body_b - (body_b - body_t) * 0.26,
        )
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.setPen(
            QPen(line, max(1.8, w * 0.035), Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap)
        )
        painter.drawPath(handle)

        body = QPainterPath()
        body.addRoundedRect(
            QRectF(body_l, body_t, body_r - body_l, body_b - body_t), radius, radius
        )
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(CARD_BG)
        painter.drawPath(body)

        level = 0.0
        if self._state == "half":
            level = 0.46
        elif full:
            level = 0.86

        if level > 0:
            painter.save()
            painter.setClipPath(body)
            top = body_b - (body_b - body_t) * level + sway
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(WATER)
            painter.drawRect(QRectF(body_l - 1, top, body_r - body_l + 2, body_b - top + 1))
            painter.setBrush(WATER_TOP)
            painter.drawEllipse(
                QPointF((body_l + body_r) / 2, top),
                (body_r - body_l) / 2,
                max(1.5, h * 0.008),
            )
            if full:
                for i in range(2):
                    prog = (self._phase * 0.55 + i * 0.5) % 1.0
                    cy = body_b - h * 0.10 - prog * (body_b - top - h * 0.12)
                    rad = max(1.4, w * 0.035) * (1 - prog * 0.6)
                    painter.setBrush(QColor(181, 212, 244, int(200 * (1 - prog))))
                    painter.drawEllipse(
                        QPointF(body_l + (body_r - body_l) * (0.3 + i * 0.34), cy), rad, rad
                    )
            painter.restore()

        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.setPen(QPen(line, max(1.4, w * 0.025)))
        painter.drawPath(body)

        if self._cups > 0:
            font = QFont()
            font.setPixelSize(max(11, int(h * 0.20)))
            font.setWeight(QFont.Weight.DemiBold)
            painter.setFont(font)
            box = QRectF(body_l, body_t, body_r - body_l, body_b - body_t)
            flag = int(Qt.AlignmentFlag.AlignCenter)
            painter.setPen(QColor(16, 24, 40, 215))
            for dx, dy in ((-1, 0), (1, 0), (0, -1), (0, 1)):
                painter.drawText(box.translated(dx, dy), flag, str(self._cups))
            painter.setPen(TEXT)
            painter.drawText(box, flag, str(self._cups))

        if full:
            alpha = int(150 + 105 * abs(math.sin(self._phase * 0.6)))
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(DOT.red(), DOT.green(), DOT.blue(), alpha))
            painter.drawEllipse(
                QPointF(body_r + w * 0.07, body_t - h * 0.015), w * 0.032, w * 0.032
            )
