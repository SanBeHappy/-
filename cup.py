"""喝水杯子：卡片右侧的马克杯，用五张素材分别表示 0 / 25 / 50 / 75 / 100% 水位。

素材在 assets/cup/ 下，尺寸由卡片运行时决定，绘制时等比缩放并底部对齐。
满水时整只杯子轻轻上下浮动，杯口右上角有个橙色小点脉冲。
"""

from __future__ import annotations

import math
import sys
from pathlib import Path

from PySide6.QtCore import QPointF, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QFont, QPainter, QPixmap
from PySide6.QtWidgets import QWidget

FRAMES = ("0", "25", "50", "75", "100")
THRESHOLDS = (0.125, 0.375, 0.625, 0.875)

TEXT = QColor("#F2F5FA")
DOT = QColor("#FF8A4C")


def _asset_dir() -> Path:
    base = getattr(sys, "_MEIPASS", None)
    if base:
        return Path(base) / "assets" / "cup"
    return Path(__file__).resolve().parent / "assets" / "cup"


_CACHE: dict[str, QPixmap] = {}


def _pixmap(name: str) -> QPixmap:
    if name not in _CACHE:
        _CACHE[name] = QPixmap(str(_asset_dir() / f"{name}.png"))
    return _CACHE[name]


class DrinkCup(QWidget):
    clicked = Signal()

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self._ratio = 0.0
        self._cups = 0
        self._left = 60
        self._full = False
        self._phase = 0.0

        self._timer = QTimer(self)
        self._timer.setInterval(60)
        self._timer.timeout.connect(self._tick)

    def set_state(self, ratio: float, cups: int, left: int, full: bool) -> None:
        changed = (
            abs(ratio - self._ratio) > 0.001
            or cups != self._cups
            or full != self._full
        )
        self._ratio = max(0.0, min(1.0, ratio))
        self._cups = cups
        self._left = left
        self._full = full

        if full:
            if not self._timer.isActive():
                self._timer.start()
            self.setToolTip("该喝水了")
        else:
            self._timer.stop()
            self._phase = 0.0
            self.setToolTip(f"还有 {left} 分钟该喝水了" if self._ratio >= 0.75 else "")
        if changed:
            self.update()

    def _tick(self) -> None:
        self._phase += 0.09
        self.update()

    def _frame(self) -> QPixmap:
        index = len(THRESHOLDS)
        for i, threshold in enumerate(THRESHOLDS):
            if self._ratio < threshold:
                index = i
                break
        return _pixmap(FRAMES[index])

    def frame_aspect(self) -> float:
        """高 / 宽。外部按这个比例摆位置，画的时候就不会被拉伸或留空。"""
        src = self._frame()
        if src.isNull() or src.width() == 0:
            return 0.887
        return src.height() / src.width()

    def paintEvent(self, event) -> None:  # noqa: N802
        src = self._frame()
        if src.isNull():
            return

        w, h = self.width(), self.height()
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)

        scaled = src.scaled(
            w,
            h,
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
        bob = math.sin(self._phase) * 1.6 if self._full else 0.0
        x = (w - scaled.width()) / 2
        y = h - scaled.height() + bob
        painter.drawPixmap(QPointF(x, y), scaled)

        if self._cups > 0:
            font = QFont()
            font.setPixelSize(max(11, int(h * 0.19)))
            font.setWeight(QFont.Weight.DemiBold)
            painter.setFont(font)
            box = QRectF(x, y, scaled.width() * 0.76, scaled.height())
            flag = int(Qt.AlignmentFlag.AlignCenter)
            painter.setPen(QColor(16, 24, 40, 220))
            for dx, dy in ((-1, 0), (1, 0), (0, -1), (0, 1)):
                painter.drawText(box.translated(dx, dy), flag, str(self._cups))
            painter.setPen(TEXT)
            painter.drawText(box, flag, str(self._cups))

        if self._full:
            alpha = int(150 + 105 * abs(math.sin(self._phase * 0.6)))
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(DOT.red(), DOT.green(), DOT.blue(), alpha))
            radius = max(2.0, w * 0.035)
            painter.drawEllipse(
                QPointF(x + scaled.width() * 0.87, y + scaled.height() * 0.04),
                radius,
                radius,
            )
