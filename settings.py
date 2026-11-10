"""设置面板：无边框深色卡片，跟主界面同一套语言。

注：PySide6 6.12 下 QAbstractSpinBox 一旦套用 border-radius 样式，
内部编辑区就不再绘制文本，所以时间 / 数字输入均改用自绘的 QLineEdit。
"""

from __future__ import annotations

import re

from PySide6.QtCore import QPoint, QRectF, Qt, QTime, Signal
from PySide6.QtGui import (
    QColor,
    QFont,
    QFontMetrics,
    QPainter,
    QPainterPath,
    QPen,
    QRegularExpressionValidator,
)
from PySide6.QtCore import QRegularExpression
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import (
    QDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

import config as config_module
from config import APP_TITLE, APP_VERSION
from engine import parse_time
from theme import (
    BASE_QSS,
    BG,
    BG_INPUT,
    ORANGE,
    SETTINGS_QSS,
    TEXT_HI,
    TEXT_LOW,
    TEXT_MID,
    ui_font,
)

WEEK_CHIPS = ("一", "二", "三", "四", "五", "六", "日")

FIELD_QSS = (
    "QLineEdit { background: %s; border: 1px solid rgba(255,255,255,22);"
    " border-radius: 8px; padding: 5px 8px; color: %s; font-size: 13px;"
    " selection-background-color: %s; selection-color: %s; }"
    "QLineEdit:focus { border: 1px solid %s; background: #2C3855; }"
) % (BG_INPUT, TEXT_HI, ORANGE, BG, ORANGE)


class TimeField(QLineEdit):
    """HH:mm 输入框，支持 1850 / 18:50 / 18 等写法，失焦自动规范化。"""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setFixedWidth(82)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setFont(ui_font(13))
        self.setMaxLength(5)
        self.setStyleSheet(FIELD_QSS)
        self.setValidator(
            QRegularExpressionValidator(QRegularExpression(r"[\d:：]{0,5}"), self)
        )

    def _parse(self) -> QTime:
        raw = self.text().replace("：", ":").strip()
        if ":" in raw:
            left, _, right = raw.partition(":")
            try:
                hour = int(left) if left else 0
                minute = int(right) if right else 0
            except ValueError:
                hour, minute = 0, 0
        else:
            digits = re.sub(r"\D", "", raw)
            if len(digits) <= 2:
                hour, minute = int(digits or 0), 0
            elif len(digits) == 3:
                hour, minute = int(digits[0]), int(digits[1:])
            else:
                hour, minute = int(digits[:2]), int(digits[2:4])
        return QTime(max(0, min(23, hour)), max(0, min(59, minute)))

    def time(self) -> QTime:  # noqa: A003
        return self._parse()

    def setTime(self, value: QTime) -> None:  # noqa: N802
        self.setText(value.toString("HH:mm"))

    def focusOutEvent(self, event) -> None:  # noqa: N802
        self.setText(self._parse().toString("HH:mm"))
        super().focusOutEvent(event)

    def wheelEvent(self, event) -> None:  # noqa: N802
        step = 5 if event.angleDelta().y() > 0 else -5
        self.setTime(self.time().addSecs(step * 60))
        event.accept()


class NumField(QLineEdit):
    """整数输入框，支持滚轮调节。"""

    def __init__(self, low: int, high: int, step: int = 1, parent=None) -> None:
        super().__init__(parent)
        self.low, self.high, self.step = low, high, step
        self.setFixedWidth(64)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setFont(ui_font(13))
        self.setStyleSheet(FIELD_QSS)
        self.setValidator(
            QRegularExpressionValidator(
                QRegularExpression(r"\d{0,3}"), self
            )
        )

    def value(self) -> int:
        try:
            number = int(self.text())
        except ValueError:
            return self.low
        return max(self.low, min(self.high, number))

    def setValue(self, value: int) -> None:  # noqa: N802
        self.setText(str(max(self.low, min(self.high, int(value)))))

    def focusOutEvent(self, event) -> None:  # noqa: N802
        self.setText(str(self.value()))
        super().focusOutEvent(event)

    def wheelEvent(self, event) -> None:  # noqa: N802
        delta = self.step if event.angleDelta().y() > 0 else -self.step
        self.setValue(self.value() + delta)
        event.accept()


class Check(QWidget):
    """自绘复选框（带对勾），避开 QSS indicator 无图标的问题。"""

    toggled = Signal(bool)

    def __init__(self, text: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._text = text
        self._checked = False
        self._hover = False
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFixedHeight(24)
        metrics = QFontMetrics(ui_font(13))
        self.setFixedWidth(26 + metrics.horizontalAdvance(text) + 4)

    def isChecked(self) -> bool:  # noqa: N802
        return self._checked

    def setChecked(self, value: bool) -> None:  # noqa: N802
        if self._checked != bool(value):
            self._checked = bool(value)
            self.update()

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton and self.rect().contains(
            event.position().toPoint()
        ):
            self.setChecked(not self._checked)
            self.toggled.emit(self._checked)

    def enterEvent(self, event) -> None:  # noqa: N802
        self._hover = True
        self.update()

    def leaveEvent(self, event) -> None:  # noqa: N802
        self._hover = False
        self.update()

    def paintEvent(self, event) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)

        box = QRectF(1, (self.height() - 17) / 2, 17, 17)
        if self._checked:
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(ORANGE))
            painter.drawRoundedRect(box, 5, 5)
            pen = QPen(
                QColor(BG),
                2.0,
                Qt.PenStyle.SolidLine,
                Qt.PenCapStyle.RoundCap,
                Qt.PenJoinStyle.RoundJoin,
            )
            painter.setPen(pen)
            path = QPainterPath()
            path.moveTo(box.left() + 4.6, box.center().y() + 0.4)
            path.lineTo(box.left() + 7.4, box.center().y() + 3.2)
            path.lineTo(box.left() + 12.6, box.center().y() - 3.4)
            painter.drawPath(path)
        else:
            painter.setBrush(QColor(BG_INPUT))
            painter.setPen(QPen(QColor(255, 255, 255, 60 if self._hover else 38), 1))
            painter.drawRoundedRect(box, 5, 5)

        painter.setPen(QColor(TEXT_MID))
        painter.setFont(ui_font(13))
        painter.drawText(
            QRectF(26, 0, self.width() - 26, self.height()),
            int(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft),
            self._text,
        )


class SettingsWindow(QDialog):
    saved = Signal()
    request_themes = Signal()
    weather_changed = Signal()

    def __init__(self, cfg, parent: QWidget | None = None) -> None:
        super().__init__(
            parent,
            Qt.WindowType.FramelessWindowHint | Qt.WindowType.Dialog,
        )
        self.cfg = cfg
        self.setWindowTitle(f"{APP_TITLE} 设置")
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setStyleSheet(BASE_QSS + SETTINGS_QSS)
        self.setFixedWidth(452)
        self._drag: QPoint | None = None
        self._build()
        self._load()

    # ------------------------------------------------------------ 构建

    def _build(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(26, 17, 26, 20)
        root.setSpacing(0)

        header = QHBoxLayout()
        header.setContentsMargins(0, 0, 0, 0)
        title = QLabel("设置")
        title.setFont(ui_font(15, QFont.Weight.DemiBold))
        title.setStyleSheet(f"color: {TEXT_HI}; padding: 0;")
        close_btn = QPushButton("×")
        close_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        close_btn.setFixedSize(26, 26)
        close_btn.setFont(ui_font(19))
        close_btn.setStyleSheet(
            "QPushButton { background: transparent; border: none; color: #6B717C;"
            " border-radius: 13px; padding-bottom: 4px; }"
            "QPushButton:hover { background: rgba(255,255,255,22); color: #F2F3F5; }"
        )
        close_btn.clicked.connect(self.reject)
        header.addWidget(title)
        header.addStretch(1)
        header.addWidget(close_btn)
        root.addLayout(header)
        root.addSpacing(12)
        root.addWidget(self._divider())
        root.addSpacing(10)

        scroll = QScrollArea(self)
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        inner = QWidget()
        body = QVBoxLayout(inner)
        body.setContentsMargins(0, 0, 6, 0)
        body.setSpacing(0)

        # ---- 作息 ----
        body.addWidget(self._section("作息"))
        body.addSpacing(9)

        self.start_edit = TimeField()
        self.off_edit = TimeField()
        grid = QGridLayout()
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setHorizontalSpacing(8)
        grid.setVerticalSpacing(0)
        grid.addWidget(self._field("上班时间", 58), 0, 0)
        grid.addWidget(self.start_edit, 0, 1)
        grid.addItem(_spacer(1), 0, 2)
        grid.addWidget(self._field("下班时间", 58), 0, 3)
        grid.addWidget(self.off_edit, 0, 4)
        grid.setColumnStretch(2, 5)
        grid.setColumnStretch(5, 4)
        body.addLayout(grid)

        body.addSpacing(11)

        self.pre_spin = NumField(0, 60)
        body.addLayout(self._value_row("提前提醒", self.pre_spin, "分钟前"))
        body.addSpacing(7)
        body.addWidget(self._hint("设为 0 则只在到点时提醒一次"))

        body.addSpacing(13)
        body.addWidget(self._section("工作日"))
        body.addSpacing(9)

        chips = QHBoxLayout()
        chips.setSpacing(5)
        self.week_buttons: list[QPushButton] = []
        for name in WEEK_CHIPS:
            chip = QPushButton(name)
            chip.setObjectName("chip")
            chip.setCheckable(True)
            chip.setFixedSize(50, 32)
            chip.setCursor(Qt.CursorShape.PointingHandCursor)
            chip.setFont(ui_font(13))
            self.week_buttons.append(chip)
            chips.addWidget(chip)
        chips.addStretch(1)
        body.addLayout(chips)

        body.addSpacing(14)
        body.addWidget(self._divider())
        body.addSpacing(10)

        # ---- 久坐 ----
        body.addWidget(self._section("久坐提醒"))
        body.addSpacing(9)

        self.sit_check = Check("久坐后提醒我起身活动")
        body.addWidget(self.sit_check)
        body.addSpacing(9)

        self.sit_spin = NumField(5, 180, step=5)
        body.addLayout(self._value_row("间隔", self.sit_spin, "分钟"))
        body.addSpacing(10)

        self.lunch_check = Check("午休时间不打扰")
        body.addWidget(self.lunch_check)
        body.addSpacing(7)

        self.lunch_start = TimeField()
        self.lunch_end = TimeField()
        lunch_row = QHBoxLayout()
        lunch_row.setContentsMargins(0, 0, 0, 0)
        lunch_row.setSpacing(8)
        lunch_row.addSpacing(28)
        lunch_row.addWidget(self.lunch_start)
        dash = QLabel("—")
        dash.setStyleSheet(f"color: {TEXT_LOW}; padding: 0;")
        lunch_row.addWidget(dash)
        lunch_row.addWidget(self.lunch_end)
        lunch_row.addStretch(1)
        body.addLayout(lunch_row)

        body.addSpacing(14)
        body.addWidget(self._divider())
        body.addSpacing(10)

        # ---- 喝水 ----
        body.addWidget(self._section("喝水提醒"))
        body.addSpacing(9)
        self.drink_check = Check("该喝水时提醒我")
        body.addWidget(self.drink_check)
        body.addSpacing(7)
        self.drink_spin = NumField(5, 180, step=5)
        body.addLayout(self._value_row("间隔", self.drink_spin, "分钟"))
        body.addSpacing(14)
        body.addWidget(self._divider())
        body.addSpacing(10)

        # ---- 周报 ----
        body.addWidget(self._section("周报提醒"))
        body.addSpacing(9)
        self.report_check = Check("本周最后一个工作日提醒写周报")
        body.addWidget(self.report_check)
        body.addSpacing(7)
        self.report_time = TimeField()
        body.addLayout(self._value_row("提醒时间", self.report_time, ""))
        body.addSpacing(14)
        body.addWidget(self._divider())
        body.addSpacing(10)

        # ---- 自动关机 ----
        body.addWidget(self._section("自动关机"))
        body.addSpacing(9)
        self.shutdown_check = Check("到点自动关机")
        body.addWidget(self.shutdown_check)
        body.addSpacing(11)

        body.addWidget(self._field("生效星期"))
        body.addSpacing(7)
        shut_chips = QHBoxLayout()
        shut_chips.setSpacing(5)
        self.shutdown_week: list[QPushButton] = []
        for name in WEEK_CHIPS:
            chip = QPushButton(name)
            chip.setObjectName("chip")
            chip.setCheckable(True)
            chip.setFixedSize(50, 32)
            chip.setCursor(Qt.CursorShape.PointingHandCursor)
            chip.setFont(ui_font(13))
            self.shutdown_week.append(chip)
            shut_chips.addWidget(chip)
        shut_chips.addStretch(1)
        body.addLayout(shut_chips)
        body.addSpacing(9)

        self.shutdown_time = TimeField()
        body.addLayout(self._value_row("关机时间", self.shutdown_time, ""))
        body.addSpacing(7)
        body.addWidget(
            self._hint("关机前 5 分钟会提醒一次，那时可以选「今晚不关」")
        )
        body.addSpacing(14)
        body.addWidget(self._divider())
        body.addSpacing(10)

        # ---- 角色主题 ----
        body.addWidget(self._section("角色主题"))
        body.addSpacing(9)
        theme_row = QHBoxLayout()
        theme_row.setContentsMargins(0, 0, 0, 0)
        theme_row.setSpacing(8)
        self.theme_value = QLabel("大肥鱼")
        self.theme_value.setFont(ui_font(13))
        self.theme_value.setStyleSheet(f"color: {TEXT_HI}; padding: 0;")
        manage_theme = QPushButton("管理主题…")
        manage_theme.setObjectName("mini")
        manage_theme.setCursor(Qt.CursorShape.PointingHandCursor)
        manage_theme.setFixedHeight(28)
        manage_theme.setFixedWidth(88)
        manage_theme.clicked.connect(self.request_themes)
        theme_row.addWidget(self._field("当前主题"))
        theme_row.addWidget(self.theme_value, 1)
        theme_row.addWidget(manage_theme, 0)
        body.addLayout(theme_row)
        body.addSpacing(6)
        body.addWidget(self._hint("切换立即生效，不用点保存"))

        body.addSpacing(14)
        body.addWidget(self._divider())
        body.addSpacing(10)

        # ---- 其它 ----
        city_row = QHBoxLayout()
        city_row.setContentsMargins(0, 0, 0, 0)
        city_row.setSpacing(8)
        city_label = QLabel("天气城市")
        city_label.setFont(ui_font(12))
        city_label.setStyleSheet(f"color: {TEXT_MID}; padding: 0;")
        self.city_edit = QLineEdit()
        self.city_edit.setStyleSheet(FIELD_QSS)
        self.city_edit.setFixedHeight(28)
        self.city_edit.setPlaceholderText("留空按网络定位，可填 Beijing / 上海")
        city_row.addWidget(city_label)
        city_row.addWidget(self.city_edit, 1)
        body.addLayout(city_row)
        body.addSpacing(10)

        self.sound_check = Check("提醒时播放提示音")
        body.addWidget(self.sound_check)
        body.addSpacing(6)

        self.startup_check = Check("开机自动启动")
        body.addWidget(self.startup_check)

        body.addStretch(1)
        inner.setObjectName("settingsInner")
        inner.setStyleSheet("QWidget#settingsInner { background: transparent; }")
        scroll.setStyleSheet(
            "QScrollArea { background: transparent; border: none; }"
            "QScrollBar:vertical { width: 8px; background: transparent; margin: 2px 0; }"
            "QScrollBar::handle:vertical {"
            " background: rgba(255,255,255,46); border-radius: 4px; min-height: 32px; }"
            "QScrollBar::handle:vertical:hover { background: rgba(255,255,255,78); }"
            "QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }"
            "QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical { background: transparent; }"
        )
        scroll.setWidget(inner)
        root.addWidget(scroll, 1)
        root.addSpacing(14)

        footer = QHBoxLayout()
        footer.setSpacing(10)
        version = QLabel(f"v{APP_VERSION}")
        version.setFont(ui_font(11))
        version.setStyleSheet(f"color: {TEXT_LOW}; padding: 0;")
        version.setToolTip(f"{APP_TITLE} {APP_VERSION}")
        footer.addWidget(version, 0, Qt.AlignmentFlag.AlignVCenter)
        footer.addStretch(1)
        cancel = QPushButton("取消")
        cancel.setObjectName("ghost")
        cancel.setCursor(Qt.CursorShape.PointingHandCursor)
        cancel.clicked.connect(self.reject)
        save = QPushButton("保存")
        save.setObjectName("primary")
        save.setCursor(Qt.CursorShape.PointingHandCursor)
        save.clicked.connect(self._save)
        footer.addWidget(cancel)
        footer.addWidget(save)
        root.addLayout(footer)

        inner.adjustSize()
        chrome = 150          # 标题栏 + 两条分隔 + 底部按钮区
        wanted = inner.sizeHint().height() + chrome
        area = QGuiApplication.primaryScreen().availableGeometry()
        self.setFixedHeight(min(wanted, int(area.height() * 0.86)))

    # ------------------------------------------------------------ 小零件

    def _section(self, text: str) -> QLabel:
        label = QLabel(text)
        label.setObjectName("section")
        label.setFont(ui_font(11))
        return label

    def _field(self, text: str, width: int = 0) -> QLabel:
        label = QLabel(text)
        label.setObjectName("field")
        label.setFont(ui_font(13))
        if width:
            label.setFixedWidth(width)
        return label

    def _hint(self, text: str) -> QLabel:
        label = QLabel(text)
        label.setObjectName("hint")
        label.setFont(ui_font(12))
        return label

    def _value_row(self, text: str, widget: QWidget, unit: str) -> QGridLayout:
        grid = QGridLayout()
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setHorizontalSpacing(8)
        grid.setVerticalSpacing(0)
        grid.addWidget(self._field(text), 0, 0)
        grid.setColumnStretch(1, 1)
        grid.addWidget(widget, 0, 2)
        unit_label = self._hint(unit)
        unit_label.setFixedWidth(46)
        unit_label.setAlignment(
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter
        )
        grid.addWidget(unit_label, 0, 3)
        return grid

    def _divider(self) -> QWidget:
        line = QWidget()
        line.setFixedHeight(1)
        line.setStyleSheet("background: rgba(255,255,255,18);")
        return line

    # ------------------------------------------------------------ 数据

    def _load(self) -> None:
        self.start_edit.setTime(_to_qtime(self.cfg["start_work"], "09:30"))
        self.off_edit.setTime(_to_qtime(self.cfg["off_work"], "18:00"))
        self.pre_spin.setValue(int(self.cfg["pre_alert_min"] or 0))
        days = self.cfg["work_days"] or []
        for index, chip in enumerate(self.week_buttons):
            chip.setChecked(index in days)
        self.sit_check.setChecked(bool(self.cfg["sit_enabled"]))
        self.sit_spin.setValue(int(self.cfg["sit_interval"] or 45))
        self.lunch_check.setChecked(bool(self.cfg["lunch_enabled"]))
        self.lunch_start.setTime(_to_qtime(self.cfg["lunch_start"], "12:00"))
        self.lunch_end.setTime(_to_qtime(self.cfg["lunch_end"], "13:30"))
        self.drink_check.setChecked(bool(self.cfg["drink_enabled"]))
        self.drink_spin.setValue(int(self.cfg["drink_interval"] or 60))
        self.report_check.setChecked(bool(self.cfg["weekly_report_enabled"]))
        self.report_time.setTime(_to_qtime(self.cfg["weekly_report_time"], "17:40"))
        self.shutdown_check.setChecked(bool(self.cfg["shutdown_enabled"]))
        shut_days = self.cfg["shutdown_days"] or []
        for index, chip in enumerate(self.shutdown_week):
            chip.setChecked(index in shut_days)
        self.shutdown_time.setTime(_to_qtime(self.cfg["shutdown_time"], "21:30"))
        self.refresh_theme()
        self.city_edit.setText(self.cfg["weather_city"] or "")
        self.sound_check.setChecked(bool(self.cfg["sound"]))
        self.startup_check.setChecked(config_module.is_autostart())

    def refresh_theme(self) -> None:
        import char_theme

        self.theme_value.setText(char_theme.display_name(self.cfg["char_theme"]))

    def _save(self) -> None:
        days = [i for i, chip in enumerate(self.week_buttons) if chip.isChecked()]
        shut_days = [i for i, chip in enumerate(self.shutdown_week) if chip.isChecked()]
        old_city = (self.cfg["weather_city"] or "").strip()
        self.cfg.update(
            {
                "start_work": self.start_edit.time().toString("HH:mm"),
                "off_work": self.off_edit.time().toString("HH:mm"),
                "pre_alert_min": self.pre_spin.value(),
                "work_days": days,
                "sit_enabled": self.sit_check.isChecked(),
                "sit_interval": self.sit_spin.value(),
                "lunch_enabled": self.lunch_check.isChecked(),
                "lunch_start": self.lunch_start.time().toString("HH:mm"),
                "lunch_end": self.lunch_end.time().toString("HH:mm"),
                "drink_enabled": self.drink_check.isChecked(),
                "drink_interval": self.drink_spin.value(),
                "weekly_report_enabled": self.report_check.isChecked(),
                "weekly_report_time": self.report_time.time().toString("HH:mm"),
                "shutdown_enabled": self.shutdown_check.isChecked(),
                "shutdown_days": shut_days,
                "shutdown_time": self.shutdown_time.time().toString("HH:mm"),
                "weather_city": self.city_edit.text().strip(),
                "sound": self.sound_check.isChecked(),
            }
        )
        want_startup = self.startup_check.isChecked()
        config_module.set_autostart(want_startup)
        self.cfg["autostart"] = want_startup
        self.cfg.save()
        self.saved.emit()
        if (self.cfg["weather_city"] or "").strip() != old_city:
            self.weather_changed.emit()
        self.accept()

    # ------------------------------------------------------------ 外观与拖动

    def paintEvent(self, event) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        rect = QRectF(0.5, 0.5, self.width() - 1, self.height() - 1)
        painter.setPen(QPen(QColor(255, 255, 255, 34), 1))
        painter.setBrush(QColor(BG))
        painter.drawRoundedRect(rect, 16, 16)

    def mousePressEvent(self, event) -> None:  # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton and event.position().y() < 50:
            self._drag = event.globalPosition().toPoint() - self.frameGeometry().topLeft()
            event.accept()

    def mouseMoveEvent(self, event) -> None:  # noqa: N802
        if self._drag is not None and event.buttons() & Qt.MouseButton.LeftButton:
            self.move(event.globalPosition().toPoint() - self._drag)
            event.accept()

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802
        self._drag = None


# ---------------------------------------------------------------- 工具


def _to_qtime(value, fallback: str) -> QTime:
    parsed = parse_time(value, fallback)
    return QTime(parsed.hour, parsed.minute)


def _spacer(width: int):
    from PySide6.QtWidgets import QSpacerItem, QSizePolicy

    return QSpacerItem(width, 1, QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Minimum)
