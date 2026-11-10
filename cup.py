"""喝水杯子：卡片右侧的马克杯，用五张素材表示 0 / 25 / 50 / 75 / 100% 水位。

以前是个独立子控件，卡片重绘时它的区域会被背景盖住、又不一定跟着重画，
偶尔出现「杯子下半截空着」的残影。现在改成跟角色一样，直接画在卡片的
paintEvent 里，背景和杯子永远在同一趟绘制中完成。
"""

from __future__ import annotations

import math
import sys
from pathlib import Path

from PySide6.QtCore import QPointF, QRect, QRectF, Qt
from PySide6.QtGui import QColor, QFont, QPainter, QPixmap

FRAMES = ("0", "25", "50", "75", "100")
THRESHOLDS = (0.125, 0.375, 0.625, 0.875)

TEXT = QColor("#F2F5FA")
DOT = QColor("#FF8A4C")

BOB_SPEED = 1.5          # 满水时上下浮动的角速度


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


class DrinkCup:
    """只管状态和画法，不占窗口层级。"""

    def __init__(self) -> None:
        self._ratio = 0.0
        self._cups = 0
        self._left = 60
        self._full = False
        self._phase = 0.0
        self._rect = QRect()

    # ------------------------------------------------------------ 状态

    def set_state(self, ratio: float, cups: int, left: int, full: bool) -> None:
        self._ratio = max(0.0, min(1.0, ratio))
        self._cups = cups
        self._left = left
        self._full = full
        if not full:
            self._phase = 0.0

    def tick(self, dt: float) -> None:
        if self._full:
            self._phase += dt * BOB_SPEED

    def bobbing(self) -> bool:
        return self._full

    def set_rect(self, rect: QRect) -> None:
        self._rect = QRect(rect)

    def rect(self) -> QRect:
        return QRect(self._rect)

    # ------------------------------------------------------------ 绘制

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

    def paint(self, painter: QPainter, rect: QRect | None = None) -> None:
        src = self._frame()
        area = QRect(rect) if rect is not None else self.rect()
        if src.isNull() or area.isEmpty():
            return

        w, h = area.width(), area.height()
        scaled = src.scaled(
            w,
            h,
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
        bob = math.sin(self._phase) * 1.6 if self._full else 0.0
        x = area.x() + (w - scaled.width()) / 2
        y = area.y() + h - scaled.height() + bob

        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
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
