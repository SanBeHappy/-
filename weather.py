"""天气：从 wttr.in 取当前温度与天气代码，并画成和界面同风格的矢量小图标。"""

from __future__ import annotations

import json
import math
import urllib.parse

from PySide6.QtCore import QObject, QPointF, QRectF, QSize, Qt, QTimer, QUrl, Signal
from PySide6.QtGui import QColor, QFontMetrics, QPainter, QPainterPath, QPen
from PySide6.QtNetwork import QNetworkAccessManager, QNetworkReply, QNetworkRequest
from PySide6.QtWidgets import QWidget

from theme import TEXT_MID, TEXT_LOW, ui_font

# ---------------------------------------------------------------- 天气代码

SUN = "sun"
SUN_CLOUD = "sun_cloud"
CLOUD = "cloud"
RAIN = "rain"
SNOW = "snow"
THUNDER = "thunder"
FOG = "fog"


def kind_of(code: int) -> str:
    """WWQ 天气代码 → 图标类型。"""
    if code == 113:
        return SUN
    if code == 116:
        return SUN_CLOUD
    if code in (119, 122):
        return CLOUD
    if code in (143, 145, 146, 248, 260):
        return FOG
    if code in (200, 386, 389, 392, 395):
        return THUNDER
    if code in (
        179, 182, 185, 227, 230, 317, 320, 323, 326, 329, 332, 335, 338,
        350, 368, 371, 374, 377,
    ):
        return SNOW
    return RAIN


SUN_COLOR = QColor("#FFC24D")
CLOUD_COLOR = QColor("#B7C6DD")
RAIN_COLOR = QColor("#6FA8FF")
SNOW_COLOR = QColor("#DCE8FA")
BOLT_COLOR = QColor("#FFD24D")


def draw_icon(painter: QPainter, rect: QRectF, kind: str) -> None:
    """把天气图标画进 rect（正方形）。"""
    painter.save()
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    painter.setPen(Qt.PenStyle.NoPen)

    s = min(rect.width(), rect.height())
    cx = rect.center().x()
    cy = rect.center().y()

    def sun(dx: float = 0.0, dy: float = 0.0, r: float = 0.20) -> None:
        painter.setBrush(SUN_COLOR)
        painter.drawEllipse(QPointF(cx + dx, cy + dy), s * r, s * r)
        painter.setPen(
            QPen(SUN_COLOR, max(1.0, s * 0.075), Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap)
        )
        for i in range(8):
            a = i * math.pi / 4
            r1 = s * (r + 0.10)
            r2 = s * (r + 0.19)
            painter.drawLine(
                QPointF(cx + dx + math.cos(a) * r1, cy + dy + math.sin(a) * r1),
                QPointF(cx + dx + math.cos(a) * r2, cy + dy + math.sin(a) * r2),
            )
        painter.setPen(Qt.PenStyle.NoPen)

    def cloud(dy: float = 0.0, scale: float = 1.0, color: QColor = CLOUD_COLOR) -> None:
        painter.setBrush(color)
        w = s * 0.62 * scale
        h = s * 0.34 * scale
        left = cx - w / 2
        top = cy - h / 2 + dy
        path = QPainterPath()
        path.addEllipse(QRectF(left, top + h * 0.30, w * 0.46, h * 0.70))
        path.addEllipse(QRectF(left + w * 0.26, top, w * 0.50, h * 0.86))
        path.addEllipse(QRectF(left + w * 0.56, top + h * 0.26, w * 0.44, h * 0.72))
        path.addRect(QRectF(left + w * 0.20, top + h * 0.55, w * 0.62, h * 0.42))
        painter.drawPath(path.simplified())

    if kind == SUN:
        sun()
    elif kind == SUN_CLOUD:
        sun(-s * 0.16, -s * 0.16, 0.15)
        cloud(s * 0.12, 0.86)
    elif kind == CLOUD:
        cloud()
        painter.setBrush(CLOUD_COLOR.lighter(115))
        painter.drawEllipse(QPointF(cx - s * 0.10, cy - s * 0.10), s * 0.17, s * 0.14)
    elif kind in (RAIN, SNOW, THUNDER):
        cloud(-s * 0.11, 0.92)
        if kind == RAIN:
            painter.setPen(
                QPen(RAIN_COLOR, max(1.2, s * 0.085), Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap)
            )
            for i in (-1, 0, 1):
                x = cx + i * s * 0.17
                painter.drawLine(
                    QPointF(x, cy + s * 0.20), QPointF(x - s * 0.03, cy + s * 0.36)
                )
        elif kind == SNOW:
            painter.setBrush(SNOW_COLOR)
            for i in (-1, 0, 1):
                painter.drawEllipse(
                    QPointF(cx + i * s * 0.17, cy + s * 0.27), s * 0.055, s * 0.055
                )
        else:
            bolt = QPainterPath()
            bolt.moveTo(cx + s * 0.06, cy + s * 0.12)
            bolt.lineTo(cx - s * 0.10, cy + s * 0.12)
            bolt.lineTo(cx + s * 0.02, cy + s * 0.30)
            bolt.lineTo(cx - s * 0.06, cy + s * 0.30)
            bolt.lineTo(cx + s * 0.10, cy + s * 0.46)
            bolt.lineTo(cx + s * 0.02, cy + s * 0.26)
            bolt.lineTo(cx + s * 0.12, cy + s * 0.26)
            bolt.closeSubpath()
            painter.setBrush(BOLT_COLOR)
            painter.drawPath(bolt)
    else:  # FOG
        painter.setPen(
            QPen(CLOUD_COLOR, max(1.2, s * 0.085), Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap)
        )
        for i, dy in enumerate((-0.20, 0.0, 0.20)):
            inset = s * (0.10 if i != 1 else 0.0)
            y = cy + s * dy
            painter.drawLine(
                QPointF(cx - s * 0.30 + inset, y), QPointF(cx + s * 0.30 - inset, y)
            )

    painter.restore()


# ---------------------------------------------------------------- 网络


class WeatherService(QObject):
    """异步取天气，失败就安静地不显示。"""

    updated = Signal(int, str, str)   # 温度, 图标类型, 地区名

    REFRESH_MS = 30 * 60 * 1000

    def __init__(self, cfg, parent=None) -> None:
        super().__init__(parent)
        self.cfg = cfg
        self._nam = QNetworkAccessManager(self)
        self._busy = False
        self._timer = QTimer(self)
        self._timer.setInterval(self.REFRESH_MS)
        self._timer.timeout.connect(self.refresh)
        self._timer.start()
        QTimer.singleShot(1200, self.refresh)

    def refresh(self) -> None:
        if self._busy:
            return
        self._busy = True
        city = (self.cfg["weather_city"] or "").strip()
        path = urllib.parse.quote(city) if city else ""
        url = QUrl(f"https://wttr.in/{path}?format=j1")
        req = QNetworkRequest(url)
        req.setHeader(
            QNetworkRequest.KnownHeaders.UserAgentHeader,
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) DeskMate/1.0",
        )
        req.setTransferTimeout(9000)
        reply = self._nam.get(req)
        reply.finished.connect(lambda r=reply: self._on_done(r))

    def _on_done(self, reply: QNetworkReply) -> None:
        self._busy = False
        try:
            if reply.error() == QNetworkReply.NetworkError.NoError:
                raw = bytes(reply.readAll()).decode("utf-8", "ignore")
                data = json.loads(raw)
                cur = data["current_condition"][0]
                temp = int(round(float(cur["temp_C"])))
                code = int(cur["weatherCode"])
                area = ""
                try:
                    area = data["nearest_area"][0]["areaName"][0]["value"]
                except Exception:
                    pass
                self.updated.emit(temp, kind_of(code), area)
        except Exception:
            pass
        finally:
            reply.deleteLater()


# ---------------------------------------------------------------- 控件


class WeatherBadge(QWidget):
    """图标 + 温度的小挂件。没数据时自动让出位置。"""

    ICON = 15

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._temp: int | None = None
        self._kind = SUN
        self._area = ""
        self._font = ui_font(11)
        self.setFixedHeight(18)
        self.setVisible(False)

    def set_weather(self, temp: int, kind: str, area: str) -> None:
        self._temp = temp
        self._kind = kind
        self._area = area
        self.setToolTip(f"{area} · {temp}°C" if area else f"{temp}°C")
        self.setVisible(True)
        self.updateGeometry()
        self.update()

    def sizeHint(self) -> QSize:  # noqa: N802
        if self._temp is None:
            return QSize(0, 18)
        fm = QFontMetrics(self._font)
        return QSize(self.ICON + 4 + fm.horizontalAdvance(f"{self._temp}°") + 2, 18)

    def paintEvent(self, event) -> None:  # noqa: N802
        if self._temp is None:
            return
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        draw_icon(
            painter,
            QRectF(0, (self.height() - self.ICON) / 2, self.ICON, self.ICON),
            self._kind,
        )
        painter.setFont(self._font)
        painter.setPen(QColor(TEXT_MID))
        painter.drawText(
            QRectF(self.ICON + 4, 0, self.width() - self.ICON - 4, self.height()),
            int(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft),
            f"{self._temp}°",
        )
