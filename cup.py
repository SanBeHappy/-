"""喝水杯子：卡片右下角的一个小马克杯，杯身中间显示今天第几杯。

三种状态由引擎给：empty / half / full。
满水时水面轻轻浮动、两颗气泡往上冒，杯口右侧有橙色小点脉冲。
"""

from __future__ import annotations

import math

from PySide6.QtCore import QPointF, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QFont, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QWidget

CUP_W, CUP_H = 72, 50

BODY_L, BODY_R = 2.0, 51.0     # 杯身左右
BODY_T, BODY_B = 5.0, 45.0     # 杯身上下
RADIUS = 9.0

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
        self.setFixedSize(CUP_W, CUP_H)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
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
            self.setToolTip("该喝水了，点我记一杯")
        else:
            self._timer.stop()
            self._phase = 0.0
            if state == "half":
                self.setToolTip(f"还有 {left} 分钟该喝水了")
            else:
                self.setToolTip(f"距下次喝水还有 {left} 分钟")
        if changed:
            self.update()

    def _tick(self) -> None:
        self._phase += 0.09
        self.update()

    def mousePressEvent(self, event) -> None:  # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit()
            event.accept()
            return
        super().mousePressEvent(event)

    def paintEvent(self, event) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)

        full = self._state == "full"
        line = LINE_READY if self._state != "empty" else LINE_IDLE
        sway = math.sin(self._phase) * 1.2 if full else 0.0

        handle = QPainterPath()
        handle.moveTo(BODY_R - 2, BODY_T + 7)
        handle.cubicTo(BODY_R + 14, BODY_T + 7, BODY_R + 14, BODY_B - 10, BODY_R - 2, BODY_B - 12)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.setPen(QPen(line, 2.6, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        painter.drawPath(handle)

        body = QPainterPath()
        body.addRoundedRect(QRectF(BODY_L, BODY_T, BODY_R - BODY_L, BODY_B - BODY_T), RADIUS, RADIUS)
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
            top = BODY_B - (BODY_B - BODY_T) * level + sway
            water = QRectF(BODY_L - 1, top, BODY_R - BODY_L + 2, BODY_B - top + 1)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(WATER)
            painter.drawRect(water)
            painter.setBrush(WATER_TOP)
            painter.drawEllipse(QPointF((BODY_L + BODY_R) / 2, top), (BODY_R - BODY_L) / 2, 1.6)

            if full:
                for i in range(2):
                    prog = (self._phase * 0.55 + i * 0.5) % 1.0
                    cy = BODY_B - 6 - prog * (BODY_B - top - 8)
                    radius = 1.6 - prog * 0.8
                    painter.setBrush(QColor(181, 212, 244, int(200 * (1 - prog))))
                    painter.drawEllipse(
                        QPointF(BODY_L + 14 + i * 14, cy), radius, radius
                    )
            painter.restore()

        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.setPen(QPen(line, 1.6))
        painter.drawPath(body)

        if self._cups > 0:
            font = QFont()
            font.setPixelSize(18)
            font.setWeight(QFont.Weight.DemiBold)
            painter.setFont(font)
            box = QRectF(BODY_L, BODY_T, BODY_R - BODY_L, BODY_B - BODY_T)
            flag = int(Qt.AlignmentFlag.AlignCenter)
            painter.setPen(QColor(16, 24, 40, 210))
            for dx, dy in ((-1, 0), (1, 0), (0, -1), (0, 1)):
                painter.drawText(box.translated(dx, dy), flag, str(self._cups))
            painter.setPen(TEXT)
            painter.drawText(box, flag, str(self._cups))

        if full:
            alpha = int(150 + 105 * abs(math.sin(self._phase * 0.6)))
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(DOT.red(), DOT.green(), DOT.blue(), alpha))
            painter.drawEllipse(QPointF(BODY_R + 6, BODY_T - 1), 2.4, 2.4)
