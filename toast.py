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

    def show(
        self,
        accent: str,
        title: str,
        body: str,
        actions: list[tuple[str, str, str]],
        on_action: Callable[[str], None],
        auto_close_ms: int = 0,
    ) -> Toast:
        if self.current is not None:
            try:
                self.current.close_toast()
            except RuntimeError:
                pass
        toast = Toast(accent, title, body, actions, on_action, auto_close_ms)
        self.current = toast
        toast.dismissed.connect(self._clear)
        x, y = self._slot(toast)
        toast.show_at(x, y)
        return toast

    def _clear(self) -> None:
        self.current = None

    def _slot(self, toast: Toast) -> tuple[int, int]:
        screen = QGuiApplication.screenAt(QCursor.pos()) or QGuiApplication.primaryScreen()
        area = screen.availableGeometry()
        return (
            area.right() - toast.width() - 18,
            area.bottom() - toast.height() - 18,
        )


# ---------------------------------------------------------------- 预设文案


def show_sit(mgr: ToastManager, minutes: int, hard: bool, on_action) -> None:
    title = "坐太久了，起来走走" if hard else "该起来动一下"
    body = random.choice(SIT_HARD_LINES if hard else SIT_LINES)
    mgr.show(
        MINT,
        title,
        f"已经连续坐了 {minutes} 分钟。{body}",
        [("5 分钟后", "ghost", "sit_snooze"), ("起身了", "primary", "sit_stand")],
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
    )


def show_off_work(mgr: ToastManager, on_action) -> None:
    mgr.show(
        ORANGE,
        "到点了，可以下班",
        "今天的事明天再说，关电脑走人。",
        [("再等 10 分钟", "ghost", "off_snooze"), ("收工", "primary", "off_ok")],
        on_action,
        auto_close_ms=90000,
    )


def show_off_again(mgr: ToastManager, on_action) -> None:
    mgr.show(
        ORANGE,
        "又过了 10 分钟",
        "再不走，地铁就要挤了。",
        [("这就走", "primary", "off_ok")],
        on_action,
        auto_close_ms=20000,
    )
