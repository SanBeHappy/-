"""桌面悬浮卡片：常驻右下角，显示下班倒计时与久坐计时。"""

from __future__ import annotations

import time
from datetime import datetime

from PySide6.QtCore import QPoint, QPointF, QRect, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QCursor, QFont, QPainter, QPen
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from config import APP_TITLE
from engine import OFF, PRE, REST, WORK, Snapshot, fmt_hms
import char_theme
from cup import DrinkCup
from fish import IDLE_EXPR, OFF_IDLE_EXPR, FishState
from weather import WeatherBadge, WeatherService
UPDATE_RED = "#FF5A5F"

from theme import (
    BASE_QSS,
    CARD_BG,
    MINT,
    ORANGE,
    TEXT_HI,
    TEXT_LOW,
    TEXT_MID,
    card_border,
    mono_font,
    ui_font,
)

WEEKDAY_CN = "一二三四五六日"

# 窗口 = 上方鱼的活动区 + 下方卡片。鱼先画，卡片后画，自然把鱼的下半身挡住。
CARD_TOP = 156
CARD_HEIGHT = 166
FISH_CX = 152
FISH_CY = 96

SIT_REASON_TEXT = {
    "before": "还没上班 · 不计时",
    "after": "已下班 · 不计时",
    "off": "久坐提醒已关闭",
    "paused": "提醒已暂停",
    "lunch": "午休中 · 暂停计时",
    "rest": "休息日 · 不计时",
}


class Dot(QWidget):
    """状态小圆点，带呼吸光晕。"""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setFixedSize(9, 9)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self._color = QColor(MINT)
        self._pulse = 1.0

    def set_state(self, color: str, pulse: float = 1.0) -> None:
        self._color = QColor(color)
        self._pulse = pulse
        self.update()

    def paintEvent(self, event) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setPen(Qt.PenStyle.NoPen)

        glow = QColor(self._color)
        glow.setAlphaF(0.16 * self._pulse)
        painter.setBrush(glow)
        painter.drawEllipse(QRectF(0, 0, 9, 9))

        core = QColor(self._color)
        core.setAlphaF(min(1.0, 0.55 + 0.45 * self._pulse))
        painter.setBrush(core)
        painter.drawEllipse(QRectF(1.6, 1.6, 5.8, 5.8))


class MiniBar(QWidget):
    """细进度条。"""

    def __init__(self, color: str, height: int = 4, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._height = height
        self._value = 0.0
        self._color = QColor(color)
        self.setFixedHeight(height)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

    def set_value(self, value: float) -> None:
        value = max(0.0, min(1.0, value))
        if abs(value - self._value) > 0.004:
            self._value = value
            self.update()

    def set_color(self, color: str) -> None:
        new = QColor(color)
        if new != self._color:
            self._color = new
            self.update()

    def paintEvent(self, event) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setPen(Qt.PenStyle.NoPen)
        height = self._height
        radius = height / 2

        painter.setBrush(QColor(255, 255, 255, 26))
        painter.drawRoundedRect(QRectF(0, 0, self.width(), height), radius, radius)

        width = self.width() * self._value
        if width > 0.5:
            painter.setBrush(self._color)
            painter.drawRoundedRect(
                QRectF(0, 0, max(width, height), height), radius, radius
            )


class UpdateBadge(QWidget):
    """日期和天气之间的小提示：红色的「更新」+ NEW 标签，点一下去更新。"""

    clicked = Signal()

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setToolTip("发现新版本，点这里查看")
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(3)

        label = QLabel("更新")
        label.setFont(ui_font(11, QFont.Weight.DemiBold))
        label.setStyleSheet(f"color: {UPDATE_RED}; padding: 0;")

        self.tag = QLabel("NEW")
        self.tag.setFont(ui_font(8, QFont.Weight.Bold))
        self.tag.setStyleSheet(
            "color: #FFFFFF; background: %s; border-radius: 5px;"
            " padding: 1px 4px; letter-spacing: 0.5px;" % UPDATE_RED
        )

        layout.addWidget(label, 0, Qt.AlignmentFlag.AlignVCenter)
        layout.addWidget(self.tag, 0, Qt.AlignmentFlag.AlignVCenter)
        self.hide()

    def mousePressEvent(self, event) -> None:  # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit()
            event.accept()
            return
        event.ignore()


class DotsButton(QWidget):
    """右上角「···」按钮，手绘，避免字体缺字。"""

    clicked = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setFixedSize(26, 24)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self._hover = False

    def enterEvent(self, event) -> None:  # noqa: N802
        self._hover = True
        self.update()

    def leaveEvent(self, event) -> None:  # noqa: N802
        self._hover = False
        self.update()

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton and self.rect().contains(
            event.position().toPoint()
        ):
            self.clicked.emit()

    def paintEvent(self, event) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(TEXT_HI if self._hover else TEXT_LOW))
        center_y = self.height() / 2
        for offset in (-5.0, 0.0, 5.0):
            painter.drawEllipse(
                QPointF(self.width() / 2 + offset, center_y), 1.7, 1.7
            )


class MainCard(QWidget):
    request_settings = Signal()
    request_menu = Signal(QPoint)
    request_hide = Signal()
    request_update = Signal()
    request_drink = Signal()
    moved = Signal()

    def __init__(self, cfg, engine) -> None:
        super().__init__(
            None,
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool,
        )
        self.cfg = cfg
        self.engine = engine
        self.setWindowTitle(APP_TITLE)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setFixedSize(304, CARD_TOP + CARD_HEIGHT)
        self.setStyleSheet(BASE_QSS)
        self.setMouseTracking(True)
        self._drag_offset: QPoint | None = None
        self._dragged = False
        self._hover = False
        self.fish = FishState(char_theme.resolve(cfg["char_theme"]))
        self._build()
        self.adjustSize()

        self.cup = DrinkCup(self)
        self.cup.raise_()
        self._place_cup()

        self.weather_service = WeatherService(cfg, self)
        self.weather_service.updated.connect(self.weather.set_weather)

        # 长按 2 秒触发「被拎起来」
        self._press_at = 0.0
        self._long_fired = False
        self._long_timer = QTimer(self)
        self._long_timer.setSingleShot(True)
        self._long_timer.setInterval(2000)
        self._long_timer.timeout.connect(self._on_long_press)

        # 小肥鱼的独立节奏，比卡片刷新快
        self._fish_timer = QTimer(self)
        self._fish_timer.setInterval(33)
        self._fish_timer.timeout.connect(self._on_fish_tick)
        self._fish_timer.start()

    # ------------------------------------------------------------ 构建

    def _build(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(18, CARD_TOP + 13, 14, 15)
        root.setSpacing(0)

        head = QHBoxLayout()
        head.setContentsMargins(0, 0, 0, 0)
        head.setSpacing(7)
        self.dot = Dot(self)
        self.date_label = QLabel("—")
        self.date_label.setFont(ui_font(12))
        self.date_label.setStyleSheet(f"color: {TEXT_MID}; padding: 0;")
        self.more_btn = DotsButton(self)
        self.more_btn.clicked.connect(self._emit_menu)
        head.addWidget(self.dot, 0, Qt.AlignmentFlag.AlignVCenter)
        head.addSpacing(1)
        head.addWidget(self.date_label, 0, Qt.AlignmentFlag.AlignVCenter)
        head.addStretch(1)
        self.update_badge = UpdateBadge(self)
        self.update_badge.clicked.connect(self.request_update.emit)
        head.addWidget(self.update_badge, 0, Qt.AlignmentFlag.AlignVCenter)
        head.addSpacing(6)
        self.weather = WeatherBadge(self)
        head.addWidget(self.weather, 0, Qt.AlignmentFlag.AlignVCenter)
        head.addSpacing(8)
        head.addWidget(self.more_btn, 0, Qt.AlignmentFlag.AlignVCenter)
        root.addLayout(head)

        root.addSpacing(8)

        self.caption = QLabel("距离下班")
        self.caption.setFont(ui_font(12))
        self.caption.setStyleSheet(f"color: {TEXT_LOW}; padding: 0;")
        root.addWidget(self.caption)

        root.addSpacing(2)

        self.big = QLabel("--:--:--")
        self.big.setFont(mono_font(30, QFont.Weight.DemiBold))
        self.big.setStyleSheet(f"color: {TEXT_HI}; padding: 0;")
        self.big.setFixedHeight(38)
        root.addWidget(self.big)

        root.addSpacing(8)

        self.day_bar = MiniBar(ORANGE, 4, self)
        self.day_bar.setFixedWidth(136)
        bar_row = QHBoxLayout()
        bar_row.setContentsMargins(0, 0, 0, 0)
        bar_row.setSpacing(0)
        bar_row.addWidget(self.day_bar)
        bar_row.addStretch(1)
        root.addLayout(bar_row)

        root.addSpacing(7)

        sit_row = QHBoxLayout()
        sit_row.setContentsMargins(0, 0, 0, 0)
        sit_row.setSpacing(10)
        self.sit_label = QLabel("久坐")
        self.sit_label.setFont(ui_font(12))
        self.sit_label.setMinimumWidth(28)
        self.sit_label.setStyleSheet(f"color: {TEXT_MID}; padding: 0;")
        self.sit_bar = MiniBar(MINT, 3, self)
        self.sit_bar.setFixedWidth(96)
        self.sit_bar.setSizePolicy(
            QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed
        )
        sit_row.addWidget(self.sit_label, 0, Qt.AlignmentFlag.AlignVCenter)
        sit_row.addSpacing(8)
        sit_row.addWidget(self.sit_bar, 0, Qt.AlignmentFlag.AlignVCenter)
        sit_row.addStretch(1)
        root.addLayout(sit_row)

    # ------------------------------------------------------------ 刷新

    def _place_cup(self) -> None:
        """杯子放在「距离下班」到久坐进度条之间的右侧，按素材比例竖着居中。"""
        if not hasattr(self, "cup"):
            return
        zone_top = self.caption.mapTo(self, QPoint(0, 0)).y()
        zone_bottom = self.sit_bar.mapTo(self, QPoint(0, 0)).y() + self.sit_bar.height()
        width = 72
        height = max(40, int(round(width * self.cup.frame_aspect())))
        # 区域装不下就缩，别让杯子戳出卡片
        room = max(40, zone_bottom - zone_top)
        if height > room:
            height = room
            width = max(40, int(round(height / self.cup.frame_aspect())))
        top = zone_top + max(0, (room - height) // 2)
        left = self.width() - 16 - width
        self.cup.setGeometry(left, top, width, height)

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        self._place_cup()

    def apply_theme(self, theme_id: str) -> None:
        """运行中换主题：重载帧集 + 立刻按当前时段校正待机/吃饭表情。"""
        self.fish.use_theme(theme_id)
        self.refresh(self.engine.snapshot, 1.0)
        self.update()

    def refresh(self, snap: Snapshot, pulse: float = 1.0) -> None:
        self.fish.set_idle(OFF_IDLE_EXPR if snap.phase == OFF else IDLE_EXPR)
        self.fish.set_meal(self.engine.in_lunch(snap.now))
        now = snap.now
        weekday = WEEKDAY_CN[now.weekday()]
        self.date_label.setText(f"周{weekday} · {now.month}月{now.day}日")

        if snap.phase == REST:
            self.caption.setText("今天不用打卡")
            self.big.setFont(ui_font(26, QFont.Weight.DemiBold))
            self.big.setStyleSheet(f"color: {TEXT_HI}; padding: 0;")
            self.big.setText("休息日")
            self.day_bar.set_value(0.0)
            self.dot.set_state(MINT, 1.0)
        elif snap.phase == OFF:
            overtime = max(0, -snap.seconds_left)
            hours = overtime // 3600
            if hours >= 2:
                caption = "这么晚了 · 该回家了"
            elif overtime >= 30 * 60:
                caption = "还不走吗"
            else:
                caption = "今天已下班"
            self.caption.setText(caption)
            self.big.setFont(mono_font(30, QFont.Weight.DemiBold))
            self.big.setStyleSheet(f"color: {ORANGE}; padding: 0;")
            self.big.setText(fmt_hms(overtime))
            self.day_bar.set_value(1.0)
            self.dot.set_state(ORANGE, 1.0)
        else:
            self.caption.setText("距离下班" if snap.phase == WORK else "快下班了")
            self.big.setFont(mono_font(30, QFont.Weight.DemiBold))
            self.big.setStyleSheet(f"color: {TEXT_HI}; padding: 0;")
            self.big.setText(fmt_hms(snap.seconds_left))
            self.day_bar.set_value(snap.day_progress)
            if snap.phase == PRE:
                self.dot.set_state(ORANGE, pulse)
            else:
                self.dot.set_state(MINT, 0.72 + 0.28 * pulse)

        self.cup.set_state(snap.drink_ratio, snap.drink_cups, snap.drink_left,
                           snap.drink_state == "full")
        self._place_cup()

        # 久坐一行
        if not snap.sit_active:
            self.sit_label.setText(SIT_REASON_TEXT.get(snap.sit_reason, "计时暂停"))
            self.sit_label.setMinimumWidth(28)
            self.sit_label.setStyleSheet(f"color: {TEXT_LOW}; padding: 0;")
            self.sit_bar.set_value(0.0)
            self.sit_bar.setToolTip(SIT_REASON_TEXT.get(snap.sit_reason, "计时暂停"))
        else:
            minutes = int(snap.sit_minutes)
            target = max(5, snap.sit_target)
            ratio = snap.sit_minutes / target
            self.sit_label.setText("久坐")
            self.sit_label.setMinimumWidth(28)
            self.sit_bar.setToolTip(f"已坐 {minutes} 分钟 · 目标 {target} 分钟")
            if ratio >= 0.8:
                self.sit_label.setStyleSheet(f"color: {ORANGE}; padding: 0;")
                self.sit_bar.set_color(ORANGE)
            else:
                self.sit_label.setStyleSheet(f"color: {TEXT_MID}; padding: 0;")
                self.sit_bar.set_color(MINT)
            self.sit_bar.set_value(ratio)

    # ------------------------------------------------------------ 定位

    def ensure_position(self) -> None:
        pos = self.cfg["pos"]
        if isinstance(pos, (list, tuple)) and len(pos) == 2:
            self.move(int(pos[0]), int(pos[1]))
            self._clamp_to_screen()
            return
        screen = self.screen() or self.parent()
        if screen is None:
            return
        area = screen.availableGeometry()
        self.move(
            area.right() - self.width() - 22,
            area.bottom() - self.height() - 14,
        )

    def _clamp_to_screen(self) -> None:
        screen = self.screen()
        if screen is None:
            return
        area = screen.availableGeometry()
        x = min(max(self.x(), area.left() - 60), area.right() - self.width() + 60)
        y = min(max(self.y(), area.top() - CARD_TOP + 30), area.bottom() - self.height() + 40)
        self.move(x, y)

    def remember_position(self) -> None:
        self.cfg["pos"] = [self.x(), self.y()]
        self.cfg.save()

    # ------------------------------------------------------------ 绘制

    def paintEvent(self, event) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)

        # 1. 先画小肥鱼（她会被下面的卡片挡住下半身）
        self.fish.draw(painter, FISH_CX, 0)

        # 2. 再画卡片，盖住鱼的下半身
        rect = QRectF(0.5, CARD_TOP + 0.5, self.width() - 1, CARD_HEIGHT - 1)
        painter.setPen(QPen(card_border(self._hover), 1))
        painter.setBrush(CARD_BG)
        painter.drawRoundedRect(rect, 16, 16)

    def _on_fish_tick(self) -> None:
        self.fish.tick(0.033)
        cursor = self.mapFromGlobal(QCursor.pos())
        self.fish.set_look(
            (cursor.x() - FISH_CX) / 90.0, (cursor.y() - FISH_CY) / 90.0
        )
        hovering = self._in_fish(cursor)
        if hovering and not self.fish.hover:
            self.fish.pat()          # 鼠标碰到形象就摸头
        self.fish.hover = hovering
        if self.fish.hover:
            self.setCursor(Qt.CursorShape.PointingHandCursor)
        else:
            self.unsetCursor()
        self.update(QRect(0, 0, self.width(), CARD_TOP))

    def _in_fish(self, pos: QPoint) -> bool:
        if pos.y() > CARD_TOP - 4:
            return False
        dx = (pos.x() - FISH_CX) / 86.0
        dy = (pos.y() - FISH_CY) / 86.0
        return dx * dx + dy * dy <= 1.0

    def enterEvent(self, event) -> None:  # noqa: N802
        self._hover = True
        self.update()

    def leaveEvent(self, event) -> None:  # noqa: N802
        self._hover = False
        self.update()

    # ------------------------------------------------------------ 交互

    def set_update_available(self, available: bool) -> None:
        """有新版本时在日期和天气之间亮起红色提示。"""
        if not hasattr(self, "update_badge"):
            return
        if available:
            self.update_badge.show()
        else:
            self.update_badge.hide()

    def _emit_menu(self) -> None:
        self.request_menu.emit(self.more_btn.mapToGlobal(QPoint(0, self.more_btn.height())))

    def mousePressEvent(self, event) -> None:  # noqa: N802
        if event.button() != Qt.MouseButton.LeftButton:
            return
        pos = event.position().toPoint()
        if self._in_fish(pos):
            self._press_at = time.monotonic()
            self._long_fired = False
            self._long_timer.start()
            event.accept()
            return
        self._drag_offset = (
            event.globalPosition().toPoint() - self.frameGeometry().topLeft()
        )
        self._dragged = False
        self._last_move_t = time.monotonic()
        event.accept()

    def mouseMoveEvent(self, event) -> None:  # noqa: N802
        if self._drag_offset is not None and event.buttons() & Qt.MouseButton.LeftButton:
            target = event.globalPosition().toPoint() - self._drag_offset
            dx = target.x() - self.x()
            dy = target.y() - self.y()
            if not self._dragged:
                # 抖一下不算拖动，避免「点一下就挪了位置」
                if abs(dx) + abs(dy) <= 3:
                    return
                self._dragged = True
                self.fish.begin_drag()
            self.move(target)
            now = time.monotonic()
            dt = max(0.008, now - getattr(self, "_last_move_t", now))
            self._last_move_t = now
            self.fish.drag_step(dx, dy, dt)
            event.accept()

    def _on_long_press(self) -> None:
        self._long_fired = True
        self.fish.lift()

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802
        if self._long_timer.isActive():
            self._long_timer.stop()
            held = time.monotonic() - self._press_at
            # 短按才算点击；按住超过 0.45 秒松手不触发，避免长按半途松开的误触
            if not self._long_fired and held < 0.45:
                self.fish.trigger()
            self._long_fired = False
        if self._drag_offset is not None:
            was_dragged = self._dragged
            self._drag_offset = None
            self._dragged = False
            if was_dragged:
                self.fish.end_drag()
                self.remember_position()
            event.accept()

    def mouseDoubleClickEvent(self, event) -> None:  # noqa: N802
        # 双击不再打开设置（统一走 ⋯ 菜单 / 托盘菜单），
        # 这里吞掉事件，避免第二次按下再走一遍点击流程
        event.accept()

    def contextMenuEvent(self, event) -> None:  # noqa: N802
        self.request_menu.emit(event.globalPos())

    def moveEvent(self, event) -> None:  # noqa: N802
        super().moveEvent(event)
        self.moved.emit()
