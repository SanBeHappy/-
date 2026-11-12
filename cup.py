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

# 缩放过的图缓存起来：杯子每秒要重画好几趟，每趟都重新 scale 一次太浪费，
# 也容易在长时间运行后攒出奇怪的图形资源状态。
_SCALED: dict[tuple[str, int, int], QPixmap] = {}

_logger = None


def set_logger(fn) -> None:
    """让主程序把日志函数挂进来，杯子画出不来时能留下线索。"""
    global _logger
    _logger = fn


def _log(message: str) -> None:
    if _logger is not None:
        try:
            _logger(message)
        except Exception:
            pass


def _load(name: str) -> QPixmap:
    pix = _CACHE.get(name)
    if pix is None or pix.isNull():
        # 加载失败不缓存，下次重画再试一次（临时读不到文件时能自己恢复）
        pix = QPixmap(str(_asset_dir() / f"{name}.png"))
        if not pix.isNull():
            _CACHE[name] = pix
    return pix


def _pixmap(name: str) -> QPixmap:
    pix = _load(name)
    if pix.isNull():
        _log(f"水杯素材读取失败：{_asset_dir() / (name + '.png')}")
        for fallback in ("0", "50", "100", "25", "75"):
            other = _load(fallback)
            if not other.isNull():
                return other
    return pix


def _scaled_pixmap(name: str, src: QPixmap, w: int, h: int) -> QPixmap:
    key = (name, w, h)
    cached = _SCALED.get(key)
    if cached is not None and not cached.isNull():
        return cached
    scaled = src.scaled(
        w,
        h,
        Qt.AspectRatioMode.KeepAspectRatio,
        Qt.TransformationMode.SmoothTransformation,
    )
    if not scaled.isNull():
        if len(_SCALED) > 16:
            _SCALED.clear()
        _SCALED[key] = scaled
    else:
        _log(f"水杯缩放失败：{name} {w}x{h}")
    return scaled


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

    def _frame_name(self) -> str:
        index = len(THRESHOLDS)
        for i, threshold in enumerate(THRESHOLDS):
            if self._ratio < threshold:
                index = i
                break
        return FRAMES[index]

    def _frame(self) -> QPixmap:
        return _pixmap(self._frame_name())

    def frame_aspect(self) -> float:
        """高 / 宽。外部按这个比例摆位置，画的时候就不会被拉伸或留空。"""
        src = self._frame()
        if src.isNull() or src.width() == 0:
            return 0.887
        return src.height() / src.width()

    def paint(self, painter: QPainter, rect: QRect | None = None) -> None:
        name = self._frame_name()
        src = _pixmap(name)
        area = QRect(rect) if rect is not None else self.rect()
        if area.isEmpty():
            _log(f"水杯区域为空：{self._rect}")
            return
        if src.isNull():
            _log(f"水杯画不出来：{name} 素材为空，区域 {area.getRect()}")
            return

        w, h = area.width(), area.height()
        scaled = _scaled_pixmap(name, src, w, h)
        if scaled.isNull():
            return
        bob = math.sin(self._phase) * 1.6 if self._full else 0.0
        x = area.x() + (w - scaled.width()) / 2
        y = area.y() + h - scaled.height() + bob

        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
        painter.drawPixmap(QPointF(x, y), scaled)

        if self._cups > 0:
            try:
                font = QFont()
                font.setPixelSize(max(11, int(h * 0.19)))
                font.setWeight(QFont.Weight.DemiBold)
                painter.setFont(font)
                box = QRectF(x, y, scaled.width() * 0.76, scaled.height())
                flag = int(Qt.AlignmentFlag.AlignCenter)
                text = str(self._cups)
                painter.setPen(QColor(16, 24, 40, 220))
                for dx, dy in ((-1, 0), (1, 0), (0, -1), (0, 1)):
                    painter.drawText(box.translated(dx, dy), flag, text)
                painter.setPen(TEXT)
                painter.drawText(box, flag, text)
            except Exception as exc:  # noqa: BLE001
                # 数字画不出来不能连累杯身
                _log(f"水杯数字绘制失败（{self._cups}）：{exc}")

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
