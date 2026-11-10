"""提醒弹窗：右下角滑入的小卡片，替代系统气泡通知。"""

from __future__ import annotations

import random
from typing import Callable

from PySide6.QtCore import (
    QEasingCurve,
    QPoint,
    QPropertyAnimation,
    QRectF,
    Qt,
    QTimer,
    Signal,
)
from PySide6.QtGui import QColor, QCursor, QFont, QGuiApplication, QPainter, QPen
from PySide6.QtWidgets import QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget

from theme import (
    BASE_QSS,
    BG,
    BLUE,
    CARD_BG,
    MINT,
    ORANGE,
    TEXT_HI,
    TEXT_LOW,
    TEXT_MID,
    card_border,
    ui_font,
)

SIT_LINES = [
    "站起来走两步，腰会谢谢你。",
    "接杯水，顺便看看窗外。",
    "肩颈放松一下，三十秒就够。",
    "远眺二十秒，眼睛也算休息。",
    "站一会儿再坐，比一直坐着强。",
]

SIT_HARD_LINES = [
    "两个多小时没起身了，起来走一圈吧。",
    "坐太久了，站起来伸个懒腰。",
]


class Toast(QWidget):
    """单条提醒卡片。"""

    dismissed = Signal()

    def __init__(
        self,
        accent: str,
        title: str,
        body: str,
        actions: list[tuple[str, str, str]],
        on_action: Callable[[str], None],
        auto_close_ms: int = 0,
        pinned: bool = False,
    ) -> None:
        super().__init__(
            None,
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool,
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)
        self.setStyleSheet(BASE_QSS)
        self.setFixedWidth(348)

        self._accent = accent
        self._on_action = on_action
        self.pinned = pinned          # True = 不自动关，也不许被别的提醒顶掉
        self._closing = False
        self._anim: QPropertyAnimation | None = None

        root = QVBoxLayout(self)
        root.setContentsMargins(20, 15, 18, 14)
        root.setSpacing(0)

        self.title_label = QLabel(title)
        self.title_label.setFont(ui_font(14, QFont.Weight.DemiBold))
        self.title_label.setStyleSheet(f"color: {TEXT_HI}; padding: 0;")
        root.addWidget(self.title_label)
        root.addSpacing(5)

        self.body_label = QLabel(body)
        self.body_label.setFont(ui_font(12))
        self.body_label.setStyleSheet(f"color: {TEXT_MID}; padding: 0;")
        self.body_label.setWordWrap(True)
        root.addWidget(self.body_label)
        root.addSpacing(13)

        row = QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(8)
        row.addStretch(1)
        for text, style, key in actions:
            button = QPushButton(text)
            button.setObjectName("primary" if style == "primary" else "ghost")
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            button.setFont(ui_font(12, QFont.Weight.Medium))
            if style == "primary":
                button.setStyleSheet(
                    f"QPushButton {{ background: {accent}; color: {BG}; border: none;"
                    f" border-radius: 8px; padding: 7px 16px; font-weight: 600; }}"
                    f"QPushButton:hover {{ background: {accent}; }}"
                )
            else:
                button.setStyleSheet(
                    "QPushButton { background: transparent; border: 1px solid"
                    " rgba(255,255,255,26); border-radius: 8px; padding: 7px 14px;"
                    f" color: {TEXT_MID}; }}"
                    "QPushButton:hover { color: #F2F3F5; border-color:"
                    " rgba(255,255,255,70); }"
                )
            button.clicked.connect(lambda _=False, k=key: self._pick(k))
            row.addWidget(button)
        root.addLayout(row)

        if auto_close_ms > 0:
            QTimer.singleShot(auto_close_ms, self._auto_close)

        self.adjustSize()

    # ------------------------------------------------------------ 行为

    def _pick(self, key: str) -> None:
        self._on_action(key)
        self.close_toast()

    def _auto_close(self) -> None:
        if not self._closing:
            self._on_action("timeout")
            self.close_toast()

    def show_at(self, x: int, y: int) -> None:
        self._target = QPoint(x, y)
        self.move(x + 34, y)
        self.setWindowOpacity(0.0)
        self.show()
        self.raise_()

        self._anim = QPropertyAnimation(self, b"pos", self)
        self._anim.setDuration(260)
        self._anim.setStartValue(QPoint(x + 34, y))
        self._anim.setEndValue(QPoint(x, y))
        self._anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._anim.start()

        fade = QPropertyAnimation(self, b"windowOpacity", self)
        fade.setDuration(200)
        fade.setStartValue(0.0)
        fade.setEndValue(1.0)
        fade.start()
        self._fade = fade

    def close_toast(self) -> None:
        if self._closing:
            return
        self._closing = True
        start = self.pos()
        self._anim = QPropertyAnimation(self, b"pos", self)
        self._anim.setDuration(180)
        self._anim.setStartValue(start)
        self._anim.setEndValue(QPoint(start.x() + 26, start.y()))
        self._anim.setEasingCurve(QEasingCurve.Type.InCubic)
        self._anim.finished.connect(self._really_close)
        self._anim.start()

        fade = QPropertyAnimation(self, b"windowOpacity", self)
        fade.setDuration(180)
        fade.setStartValue(self.windowOpacity())
        fade.setEndValue(0.0)
        fade.start()
        self._fade = fade

    def _really_close(self) -> None:
        self.dismissed.emit()
        self.hide()
        self.deleteLater()

    def paintEvent(self, event) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)

        rect = QRectF(0.5, 0.5, self.width() - 1, self.height() - 1)
        painter.setPen(QPen(card_border(False), 1))
        painter.setBrush(CARD_BG)
        painter.drawRoundedRect(rect, 16, 16)

        # 左侧强调条
        accent = QColor(self._accent)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(accent)
        painter.drawRoundedRect(QRectF(0.5, 14, 3, self.height() - 28), 1.5, 1.5)


class ToastManager:
    """同一时刻只保留一条提醒，新提醒顶掉旧的。"""

    def __init__(self, cfg) -> None:
        self.cfg = cfg
        self.current: Toast | None = None
        self._pending: tuple | None = None
        # 由外部挂一个「卡片在哪」的回调，提醒窗要躲开它，别压住倒计时
        self.anchor = None

    def show(
        self,
        accent: str,
        title: str,
        body: str,
        actions: list[tuple[str, str, str]],
        on_action: Callable[[str], None],
        auto_close_ms: int = 0,
        pinned: bool = False,
        urgent: bool = False,
    ) -> Toast | None:
        """pinned=True 的提醒不会自动消失，也不会被后来的提醒顶掉。

        urgent=True 的是下班、周报这类错过就麻烦的提醒，允许盖掉常驻窗。
        """
        if self.current is not None:
            try:
                if self.current.pinned and not urgent:
                    # 常驻的还在，后来的先排队，等它被点掉再显示
                    self._pending = (
                        accent, title, body, actions, on_action, auto_close_ms, pinned
                    )
                    return None
                self.current.close_toast()
            except RuntimeError:
                pass
        return self._create(
            accent, title, body, actions, on_action, auto_close_ms, pinned
        )

    def _create(
        self,
        accent: str,
        title: str,
        body: str,
        actions: list[tuple[str, str, str]],
        on_action: Callable[[str], None],
        auto_close_ms: int,
        pinned: bool,
    ) -> Toast:
        toast = Toast(accent, title, body, actions, on_action, auto_close_ms, pinned)
        self.current = toast
        toast.dismissed.connect(lambda t=toast: self._clear(t))
        x, y = self._slot(toast)
        toast.show_at(x, y)
        return toast

    def _clear(self, toast: Toast | None = None) -> None:
        # 被顶掉的旧提醒也会走到这里，别把刚显示的那条误清掉
        if toast is None or self.current is toast:
            self.current = None
        if self.current is None and self._pending is not None:
            args = self._pending
            self._pending = None
            self._create(*args)

    def _slot(self, toast: Toast) -> tuple[int, int]:
        screen = QGuiApplication.screenAt(QCursor.pos()) or QGuiApplication.primaryScreen()
        area = screen.availableGeometry()
        fallback = (
            area.right() - toast.width() - 18,
            area.bottom() - toast.height() - 18,
        )

        card = None
        if callable(self.anchor):
            try:
                card = self.anchor()
            except Exception:
                card = None
        if card is None or not card.isValid():
            return fallback

        # 优先放卡片左边，底边对齐；放不下就放卡片上方
        x = card.left() - toast.width() - 12
        if x >= area.left():
            return x, max(area.top(), card.bottom() - toast.height())
        y = card.top() - toast.height() - 12
        if y >= area.top():
            return max(area.left(), card.right() - toast.width()), y
        return fallback


# ---------------------------------------------------------------- 预设文案


def show_sit(mgr: ToastManager, minutes: int, hard: bool, on_action) -> None:
    title = "坐太久了，起来走走" if hard else "该起来动一下"
    body = random.choice(SIT_HARD_LINES if hard else SIT_LINES)
    mgr.show(
        MINT,
        title,
        f"已经连续坐了 {minutes} 分钟。{body}",
        [("知道了", "ghost", "sit_ok"), ("起来了", "primary", "sit_stand")],
        on_action,
        auto_close_ms=20000,
    )


def show_pre_off(mgr: ToastManager, minutes: int, on_action) -> None:
    mgr.show(
        ORANGE,
        f"还有 {minutes} 分钟下班",
        "把手头这点事收个尾，别开新的了。",
        [("知道了", "primary", "off_ok")],
        on_action,
        auto_close_ms=15000,
    )


REPORT_LINES = (
    "这周做成了什么、卡在哪、下周打算干什么，三句话就能说清。",
    "趁还记得，把能拿得出手的事先写上。",
    "别攒到周一，那时候细节就忘了。",
)


DRINK_LINES = (
    "起身接杯水，顺便把脖子转两圈。",
    "喝两口，别让嗓子一直干着。",
    "水杯该续了，趁现在脑子里的事正好告一段落。",
)


def show_drink(mgr: ToastManager, cups: int, on_action) -> None:
    current = mgr.current
    if current is not None and getattr(current, "pinned", False):
        return                      # 已经挂着一条了，别叠第二条一样的
    title = "该喝水了"
    body = random.choice(DRINK_LINES)
    if cups > 0:
        body = f"今天第 {cups + 1} 杯。{body}"
    mgr.show(
        BLUE,
        title,
        body,
        [("10 分钟后", "ghost", "drink_snooze"), ("喝了", "primary", "drink_ok")],
        on_action,
        auto_close_ms=0,
        pinned=True,
    )


MONTHLY_LINES = (
    "这个月做成了什么、数据怎么样、下个月重点在哪，一起写上。",
    "月报看的是结果，挑有数字、能说清价值的写。",
)


def show_report(mgr: ToastManager, monthly: bool, on_action) -> None:
    if monthly:
        title = "该写月报了"
        body = random.choice(MONTHLY_LINES)
    else:
        title = "该写周报了"
        body = random.choice(REPORT_LINES)
    mgr.show(
        MINT,
        title,
        body,
        [("10 分钟后", "ghost", "report_snooze"), ("写过了", "primary", "report_ok")],
        on_action,
        auto_close_ms=30000,
        urgent=True,
    )


def show_off_work(mgr: ToastManager, on_action) -> None:
    mgr.show(
        ORANGE,
        "到点了，可以下班",
        "今天的事明天再说，关电脑走人。",
        [("再等 10 分钟", "ghost", "off_snooze"), ("收工", "primary", "off_ok")],
        on_action,
        auto_close_ms=90000,
        urgent=True,
    )


def show_off_again(mgr: ToastManager, on_action) -> None:
    mgr.show(
        ORANGE,
        "又过了 10 分钟",
        "再不走，地铁就要挤了。",
        [("这就走", "primary", "off_ok")],
        on_action,
        auto_close_ms=20000,
        urgent=True,
    )


def show_shutdown(mgr: ToastManager, minutes: int, on_action) -> None:
    mgr.show(
        ORANGE,
        f"{minutes} 分钟后自动关机",
        "还在跑的东西记得先保存。今晚不想关，就点左边。",
        [("今晚不关", "ghost", "shutdown_skip"), ("知道了", "primary", "shutdown_ok")],
        on_action,
        auto_close_ms=0,
        pinned=True,
        urgent=True,
    )
