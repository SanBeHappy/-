"""角色主题的管理与编辑界面。

三个窗口：
  ThemeManagerWindow —— 主题列表（新建 / 重命名 / 删除 / 应用）
  ThemeEditorWindow  —— 28 个槽位的图片编辑器
      + NewThemeDialog / PreviewDialog / SlotCard / CheckerThumb

风格跟 SettingsWindow 一致：无边框圆角深色底、标题栏可拖。
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QRectF, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QFont, QPainter, QPainterPath, QPixmap
from PySide6.QtWidgets import (
    QApplication,
    QDialog,
    QFileDialog,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

import char_theme
import image_proc
import update
from image_proc import ImageImportError
from settings import Check, FIELD_QSS
from theme import (
    BASE_QSS,
    BG,
    BG_INPUT,
    BG_RAISED,
    MINT,
    ORANGE,
    SETTINGS_QSS,
    TEXT_HI,
    TEXT_LOW,
    TEXT_MID,
    THEME_UI_QSS,
    ui_font,
)

DIALOG_QSS = BASE_QSS + SETTINGS_QSS + THEME_UI_QSS


# ---------------------------------------------------------------- 基类


class DarkDialog(QDialog):
    """无边框圆角深色窗口，标题栏区域可拖动。"""

    def __init__(
        self,
        title: str,
        width: int,
        height: int | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(
            parent,
            Qt.WindowType.FramelessWindowHint | Qt.WindowType.Dialog,
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setStyleSheet(DIALOG_QSS)
        self.setFixedWidth(width)
        self._drag_at = None

        self._root = QVBoxLayout(self)
        self._root.setContentsMargins(26, 17, 26, 20)
        self._root.setSpacing(0)
        self._root.addLayout(self._header(title))
        self._root.addSpacing(12)
        self._root.addWidget(self._divider())
        self._root.addSpacing(10)

        self._content = QVBoxLayout()
        self._content.setContentsMargins(0, 0, 0, 0)
        self._content.setSpacing(0)
        self._root.addLayout(self._content, 1)

        if height:
            self.setFixedHeight(height)
        else:
            self.adjustSize()

    # ---- 结构 ----

    def body(self) -> QVBoxLayout:
        return self._content

    def _header(self, title: str) -> QHBoxLayout:
        row = QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        label = QLabel(title)
        label.setFont(ui_font(15, QFont.Weight.DemiBold))
        label.setStyleSheet(f"color: {TEXT_HI}; padding: 0;")
        close = QPushButton("×")
        close.setCursor(Qt.CursorShape.PointingHandCursor)
        close.setFixedSize(26, 26)
        close.setFont(ui_font(19))
        close.setStyleSheet(
            "QPushButton { background: transparent; border: none; color: #6B717C;"
            " border-radius: 13px; padding-bottom: 4px; }"
            "QPushButton:hover { background: rgba(255,255,255,22); color: #F2F3F5; }"
        )
        close.clicked.connect(self.reject)
        row.addWidget(label)
        row.addStretch(1)
        row.addWidget(close)
        return row

    def _divider(self) -> QWidget:
        line = QWidget(self)
        line.setFixedHeight(1)
        line.setStyleSheet("background: rgba(255,255,255,18);")
        return line

    def _section(self, text: str) -> QLabel:
        label = QLabel(text)
        label.setObjectName("section")
        label.setFont(ui_font(11))
        label.setStyleSheet(f"color: {TEXT_LOW}; padding: 0; letter-spacing: 1px;")
        return label

    def _hint(self, text: str) -> QLabel:
        label = QLabel(text)
        label.setWordWrap(True)
        label.setFont(ui_font(11))
        label.setStyleSheet(f"color: {TEXT_LOW}; padding: 0;")
        return label

    def _primary(self, text: str) -> QPushButton:
        btn = QPushButton(text)
        btn.setObjectName("primary")
        btn.setCursor(Qt.CursorShape.PointingHandCursor)
        return btn

    def _ghost(self, text: str, width: int = 0) -> QPushButton:
        btn = QPushButton(text)
        btn.setObjectName("mini")
        btn.setCursor(Qt.CursorShape.PointingHandCursor)
        btn.setFixedHeight(28)
        if width:
            btn.setFixedWidth(width)
        return btn

    # ---- 外框 ----

    def paintEvent(self, event) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        rect = QRectF(0.5, 0.5, self.width() - 1, self.height() - 1)
        painter.setPen(QColor(255, 255, 255, 34))
        painter.setBrush(QColor(BG))
        painter.drawRoundedRect(rect, 16, 16)

    def mousePressEvent(self, event) -> None:  # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton and event.position().y() < 50:
            self._drag_at = event.globalPosition().toPoint() - self.frameGeometry().topLeft()
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:  # noqa: N802
        if self._drag_at is not None and event.buttons() & Qt.MouseButton.LeftButton:
            self.move(event.globalPosition().toPoint() - self._drag_at)
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802
        self._drag_at = None
        super().mouseReleaseEvent(event)


# ---------------------------------------------------------------- 缩略图


class CheckerThumb(QWidget):
    """棋盘格底 + 等比居中图，圆角裁切。用来显示透明图不会被白底骗到。"""

    def __init__(self, size: int, radius: int = 10, parent=None) -> None:
        super().__init__(parent)
        self.setFixedSize(size, size)
        self._radius = radius
        self._pix: QPixmap | None = None
        self._placeholder = ""

    def set_pixmap(self, pix: QPixmap | None, placeholder: str = "") -> None:
        self._pix = pix
        self._placeholder = placeholder
        self.update()

    def paintEvent(self, event) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        w, h = self.width(), self.height()

        path_rect = QRectF(0, 0, w, h)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor("#1B2438"))
        painter.drawRoundedRect(path_rect, self._radius, self._radius)

        painter.save()
        clip = QPainterPath()
        clip.addRoundedRect(path_rect, self._radius, self._radius)
        painter.setClipPath(clip)

        step = 8
        painter.setBrush(QColor("#232E48"))
        for row in range(0, h, step):
            for col in range(0, w, step):
                if ((row // step) + (col // step)) % 2 == 0:
                    painter.drawRect(col, row, step, step)

        if self._pix is not None and not self._pix.isNull():
            scaled = self._pix.scaled(
                QSize(w - 8, h - 8),
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
            painter.drawPixmap(
                (w - scaled.width()) // 2, (h - scaled.height()) // 2, scaled
            )
        elif self._placeholder:
            painter.setPen(QColor(TEXT_LOW))
            painter.setFont(ui_font(13))
            painter.drawText(self.rect(), int(Qt.AlignmentFlag.AlignCenter), self._placeholder)
        painter.restore()

        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.setPen(QColor(255, 255, 255, 24))
        painter.drawRoundedRect(QRectF(0.5, 0.5, w - 1, h - 1), self._radius, self._radius)


# ---------------------------------------------------------------- 新建


class NewThemeDialog(DarkDialog):
    """先要一个名字，再建目录。"""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__("新建角色主题", 380, parent=parent)
        body = self.body()

        body.addWidget(self._section("名称"))
        body.addSpacing(7)
        self.edit = QLineEdit()
        self.edit.setStyleSheet(FIELD_QSS)
        self.edit.setPlaceholderText("例如：粉色小鲸鱼")
        self.edit.setMaxLength(24)
        self.edit.textChanged.connect(self._revalidate)
        body.addWidget(self.edit)
        body.addSpacing(6)

        self.message = QLabel("")
        self.message.setFont(ui_font(11))
        self.message.setWordWrap(True)
        self.message.setStyleSheet(f"color: {TEXT_LOW}; padding: 0;")
        body.addWidget(self.message)
        body.addSpacing(12)

        self.copy_check = Check("复制「大肥鱼」的 28 张图作为起点")
        self.copy_check.setChecked(False)
        body.addWidget(self.copy_check)
        body.addSpacing(14)

        footer = QHBoxLayout()
        footer.addStretch(1)
        cancel = self._ghost("取消", 76)
        cancel.clicked.connect(self.reject)
        self.create_btn = self._primary("创建")
        self.create_btn.setEnabled(False)
        self.create_btn.clicked.connect(self._accept)
        footer.addWidget(cancel)
        footer.addSpacing(8)
        footer.addWidget(self.create_btn)
        body.addLayout(footer)

        self.edit.returnPressed.connect(self._accept)
        self._revalidate("")
        self.adjustSize()

    @property
    def name(self) -> str:
        return self.edit.text().strip()

    @property
    def copy_builtin(self) -> bool:
        return self.copy_check.isChecked()

    def _revalidate(self, _text: str) -> None:
        ok, msg = char_theme.valid_name(self.edit.text())
        self.create_btn.setEnabled(ok)
        if not self.edit.text().strip():
            self.message.setText("名称不能包含 \\ / : * ? \" < > |，最长 24 字")
            self.message.setStyleSheet(f"color: {TEXT_LOW}; padding: 0;")
        else:
            self.message.setText("" if ok else msg)
            color = TEXT_LOW if ok else ORANGE
            self.message.setStyleSheet(f"color: {color}; padding: 0;")

    def _accept(self) -> None:
        ok, msg = char_theme.valid_name(self.edit.text())
        if not ok:
            self.message.setText(msg)
            self.message.setStyleSheet(f"color: {ORANGE}; padding: 0;")
            return
        self.accept()


# ---------------------------------------------------------------- 预览


class PreviewDialog(DarkDialog):
    RETRY = 2

    def __init__(self, image: QPixmap, slot: char_theme.Slot, result, parent=None) -> None:
        super().__init__("确认这张图", 360, parent=parent)
        body = self.body()

        thumb = CheckerThumb(220, radius=12)
        thumb.set_pixmap(image)
        holder = QHBoxLayout()
        holder.addStretch(1)
        holder.addWidget(thumb)
        holder.addStretch(1)
        body.addLayout(holder)
        body.addSpacing(12)

        name = QLabel(slot.label)
        name.setFont(ui_font(14, QFont.Weight.DemiBold))
        name.setStyleSheet(f"color: {TEXT_HI}; padding: 0;")
        body.addWidget(name)
        body.addSpacing(5)

        note = self._hint(result.note)
        note.setStyleSheet(f"color: {TEXT_MID}; padding: 0;")
        body.addWidget(note)
        body.addSpacing(16)

        footer = QHBoxLayout()
        retry = self._ghost("重新选择", 88)
        retry.clicked.connect(lambda: self.done(self.RETRY))
        cancel = self._ghost("取消", 68)
        cancel.clicked.connect(self.reject)
        ok = self._primary("使用这张")
        ok.clicked.connect(self.accept)
        footer.addStretch(1)
        footer.addWidget(retry)
        footer.addSpacing(8)
        footer.addWidget(cancel)
        footer.addSpacing(8)
        footer.addWidget(ok)
        body.addLayout(footer)
        self.adjustSize()


# ---------------------------------------------------------------- 槽位卡片


class SlotCard(QWidget):
    upload_requested = Signal(str)
    reset_requested = Signal(str)

    W, H = 150, 162

    def __init__(self, slot: char_theme.Slot, parent=None) -> None:
        super().__init__(parent)
        self.slot = slot
        self.setObjectName("slotCard")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setFixedSize(self.W, self.H)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setToolTip(f"{slot.label} · {slot.usage}")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(9, 9, 9, 8)
        layout.setSpacing(5)

        self.thumb = CheckerThumb(72, radius=8)
        thumb_row = QHBoxLayout()
        thumb_row.addStretch(1)
        thumb_row.addWidget(self.thumb)
        thumb_row.addStretch(1)
        layout.addLayout(thumb_row)

        self.title = QLabel(slot.label)
        self.title.setFont(ui_font(12))
        self.title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.title.setStyleSheet(f"color: {TEXT_HI}; padding: 0;")
        layout.addWidget(self.title)

        self.badge = QLabel("○ 默认")
        self.badge.setFont(ui_font(10))
        self.badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.badge.setStyleSheet(f"color: {TEXT_LOW}; padding: 0;")
        layout.addWidget(self.badge)

        buttons = QHBoxLayout()
        buttons.setContentsMargins(0, 0, 0, 0)
        buttons.setSpacing(4)
        buttons.addStretch(1)
        self.upload = QPushButton("上传")
        self.upload.setObjectName("mini")
        self.upload.setCursor(Qt.CursorShape.PointingHandCursor)
        self.upload.setFixedHeight(24)
        self.upload.setFixedWidth(78)
        self.upload.setFont(ui_font(11))
        self.upload.clicked.connect(lambda: self.upload_requested.emit(self.slot.key))
        self.reset = QPushButton("还原")
        self.reset.setObjectName("mini")
        self.reset.setCursor(Qt.CursorShape.PointingHandCursor)
        self.reset.setFixedHeight(24)
        self.reset.setFixedWidth(38)
        self.reset.setFont(ui_font(11))
        self.reset.clicked.connect(lambda: self.reset_requested.emit(self.slot.key))
        buttons.addWidget(self.upload)
        buttons.addWidget(self.reset)
        buttons.addStretch(1)
        layout.addLayout(buttons)

    def set_state(self, pix: QPixmap | None, custom: bool) -> None:
        self.thumb.set_pixmap(pix, "缺图")
        if custom:
            self.badge.setText("● 自定义")
            self.badge.setStyleSheet(f"color: {MINT}; padding: 0;")
            self.upload.setText("替换")
            self.reset.setVisible(True)
        else:
            self.badge.setText("○ 默认")
            self.badge.setStyleSheet(f"color: {TEXT_LOW}; padding: 0;")
            self.upload.setText("上传")
            self.reset.setVisible(False)

    def mousePressEvent(self, event) -> None:  # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton:
            self.upload_requested.emit(self.slot.key)
            event.accept()


# ---------------------------------------------------------------- 编辑器


class ThemeEditorWindow(DarkDialog):
    theme_applied = Signal(str)
    theme_touched = Signal(str)

    def __init__(self, theme_id: str, cfg, parent=None) -> None:
        super().__init__("编辑主题", 720, 680, parent)
        self.theme_id = theme_id
        self.cfg = cfg
        self.cards: dict[str, SlotCard] = {}
        self._group_counters: dict[str, QLabel] = {}
        self._last_dir = str(Path.home())

        info = char_theme.get_theme(theme_id)
        self.setWindowTitle(info.name if info else "编辑主题")

        body = self.body()
        line = QHBoxLayout()
        self.title_label = QLabel(info.name if info else theme_id)
        self.title_label.setFont(ui_font(14, QFont.Weight.DemiBold))
        self.title_label.setStyleSheet(f"color: {TEXT_HI}; padding: 0;")
        line.addWidget(self.title_label)
        line.addStretch(1)
        line.addWidget(self._hint("没上传的槽位自动沿用「大肥鱼」的图"))
        body.addLayout(line)
        body.addSpacing(10)

        scroll = QScrollArea(self)
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        inner = QWidget()
        self.inner_layout = QVBoxLayout(inner)
        self.inner_layout.setContentsMargins(0, 0, 6, 4)
        self.inner_layout.setSpacing(0)

        for group in char_theme.GROUP_ORDER:
            self._build_group(inner, group)
        self.inner_layout.addStretch(1)
        scroll.setWidget(inner)
        body.addWidget(scroll, 1)
        body.addSpacing(10)

        footer = QHBoxLayout()
        reset_all = self._ghost("全部还原", 92)
        reset_all.clicked.connect(self._reset_all)
        apply_btn = self._primary("设为当前")
        apply_btn.clicked.connect(self._on_apply)
        close = self._ghost("完成", 76)
        close.clicked.connect(self.accept)
        footer.addWidget(reset_all)
        footer.addStretch(1)
        footer.addWidget(apply_btn)
        footer.addSpacing(8)
        footer.addWidget(close)
        body.addLayout(footer)

        self.refresh_all()

    # ---- 构建 ----

    def _build_group(self, parent: QWidget, group: str) -> None:
        slots = [s for s in char_theme.SLOTS if s.group == group]
        if not slots:
            return

        head = QHBoxLayout()
        head.setContentsMargins(0, 14 if parent.layout().count() else 0, 0, 8)
        title = self._section(char_theme.GROUP_TITLES[group])
        hint = self._hint(char_theme.GROUP_HINTS[group])
        counter = QLabel(f"0/{len(slots)}")
        counter.setFont(ui_font(11))
        counter.setStyleSheet(f"color: {TEXT_LOW}; padding: 0;")
        self._group_counters[group] = counter
        head.addWidget(title)
        head.addSpacing(8)
        head.addWidget(hint)
        head.addStretch(1)
        head.addWidget(counter)
        parent.layout().addLayout(head)

        grid = QGridLayout()
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setHorizontalSpacing(12)
        grid.setVerticalSpacing(12)
        for index, slot in enumerate(slots):
            card = SlotCard(slot)
            card.upload_requested.connect(self._pick_image)
            card.reset_requested.connect(self._reset_slot)
            self.cards[slot.key] = card
            grid.addWidget(card, index // 4, index % 4)
        for col in range(4):
            grid.setColumnStretch(col, 0)
        grid.setColumnStretch(5, 1)
        parent.layout().addLayout(grid)

    # ---- 刷新 ----

    def refresh_all(self) -> None:
        frames = char_theme.load_frames(self.theme_id)
        for key, card in self.cards.items():
            card.set_state(frames.get(key), char_theme.is_custom(self.theme_id, key))
        for group in char_theme.GROUP_ORDER:
            slots = [s for s in char_theme.SLOTS if s.group == group]
            done = sum(1 for s in slots if char_theme.is_custom(self.theme_id, s.key))
            label = self._group_counters.get(group)
            if label is not None:
                label.setText(f"{done}/{len(slots)}")

    def refresh_slot(self, key: str) -> None:
        card = self.cards.get(key)
        if card is None:
            return
        frames = char_theme.load_frames(self.theme_id)
        card.set_state(frames.get(key), char_theme.is_custom(self.theme_id, key))
        slot = char_theme.SLOT_BY_KEY[key]
        slots = [s for s in char_theme.SLOTS if s.group == slot.group]
        done = sum(1 for s in slots if char_theme.is_custom(self.theme_id, s.key))
        label = self._group_counters.get(slot.group)
        if label is not None:
            label.setText(f"{done}/{len(slots)}")

    # ---- 上传 ----

    def _pick_image(self, key: str) -> None:
        slot = char_theme.SLOT_BY_KEY.get(key)
        if slot is None:
            return
        if char_theme.theme_dir(self.theme_id) is None:
            self._notify("主题已被删除，无法继续编辑")
            self.reject()
            return

        while True:
            path, _ = QFileDialog.getOpenFileName(
                self,
                f"为「{slot.label}」选择图片",
                self._last_dir,
                "图片 (*.png *.jpg *.jpeg *.webp *.bmp *.gif)",
            )
            if not path:
                return
            self._last_dir = str(Path(path).parent)

            QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
            try:
                result = image_proc.process_image(path)
            except ImageImportError as exc:
                QApplication.restoreOverrideCursor()
                self._notify(str(exc))
                continue
            except (OSError, MemoryError):
                QApplication.restoreOverrideCursor()
                self._notify("处理这张图失败了，换一张试试")
                continue
            finally:
                if QApplication.overrideCursor() is not None:
                    QApplication.restoreOverrideCursor()

            preview = PreviewDialog(QPixmap.fromImage(result.image), slot, result, self)
            code = preview.exec()
            if code == PreviewDialog.RETRY:
                continue
            if code != QDialog.DialogCode.Accepted:
                return

            try:
                char_theme.set_slot(self.theme_id, key, result.image)
            except (PermissionError, OSError) as exc:
                self._notify(f"保存失败：{exc}")
                return
            self.refresh_slot(key)
            if self.cfg["char_theme"] == self.theme_id:
                self.theme_touched.emit(self.theme_id)
            return

    def _reset_slot(self, key: str) -> None:
        if not char_theme.is_custom(self.theme_id, key):
            return
        char_theme.reset_slot(self.theme_id, key)
        self.refresh_slot(key)
        if self.cfg["char_theme"] == self.theme_id:
            self.theme_touched.emit(self.theme_id)

    def _reset_all(self) -> None:
        if not any(char_theme.is_custom(self.theme_id, k) for k in char_theme.SLOT_KEYS):
            return
        confirm = ConfirmDialog(
            "全部还原",
            "把「{}」里所有槽位都恢复成大肥鱼的默认图？".format(
                char_theme.display_name(self.theme_id)
            ),
            "还原",
            self,
        )
        if confirm.exec() != QDialog.DialogCode.Accepted:
            return
        char_theme.reset_all(self.theme_id)
        self.refresh_all()
        if self.cfg["char_theme"] == self.theme_id:
            self.theme_touched.emit(self.theme_id)

    def _on_apply(self) -> None:
        self.theme_applied.emit(self.theme_id)

    def _notify(self, text: str) -> None:
        tip = QLabel(text, self)
        tip.setStyleSheet(
            f"background: {BG_INPUT}; color: {TEXT_HI}; border-radius: 8px;"
            " padding: 8px 12px; font-size: 12px;"
        )
        tip.adjustSize()
        tip.move(
            (self.width() - tip.width()) // 2,
            self.height() - tip.height() - 76,
        )
        tip.show()
        QTimer.singleShot(2200, tip.deleteLater)


class UpdateDialog(DarkDialog):
    """发现新版本时先看更新日志，再决定去不去。"""

    def __init__(self, version: str, current: str, notes: list[str], parent=None) -> None:
        super().__init__("发现新版本", 440, parent=parent)
        body = self.body()

        head = QHBoxLayout()
        big = QLabel(f"v{version}")
        big.setFont(ui_font(24, QFont.Weight.DemiBold))
        big.setStyleSheet(f"color: {MINT}; padding: 0;")
        head.addWidget(big)
        head.addSpacing(10)
        head.addWidget(self._hint(f"你现在用的是 v{current}"), 0, Qt.AlignmentFlag.AlignBottom)
        head.addStretch(1)
        body.addLayout(head)
        body.addSpacing(14)

        body.addWidget(self._section("更新内容"))
        body.addSpacing(9)

        if notes:
            for note in notes[:6]:
                item = QLabel(f"·  {note}")
                item.setWordWrap(True)
                item.setFont(ui_font(12))
                item.setStyleSheet(f"color: {TEXT_MID}; padding: 0;")
                body.addWidget(item)
                body.addSpacing(5)
        else:
            body.addWidget(self._hint("这次没写更新说明，去仓库看看提交记录。"))

        self.status = QLabel("")
        self.status.setFont(ui_font(11))
        self.status.setStyleSheet(f"color: {TEXT_LOW}; padding: 0;")
        body.addWidget(self.status)
        body.addSpacing(10)

        footer = QHBoxLayout()
        footer.addStretch(1)
        self.later = self._ghost("以后再说", 92)
        self.later.clicked.connect(self.reject)
        self.go = self._primary("立即更新")
        self.go.clicked.connect(self._start_download)
        footer.addWidget(self.later)
        footer.addSpacing(8)
        footer.addWidget(self.go)
        body.addLayout(footer)
        self.adjustSize()

        self._downloader = None

    def _start_download(self) -> None:
        if not update.can_self_update():
            self.status.setText("开发模式下不支持自动更新")
            self.status.setStyleSheet(f"color: {ORANGE}; padding: 0;")
            return
        self.go.setEnabled(False)
        self.go.setText("下载中")
        self.later.setEnabled(False)
        self.status.setText("正在连接…")
        self.status.setStyleSheet(f"color: {TEXT_MID}; padding: 0;")

        self._downloader = update.UpdateDownloader()
        self._downloader.progress.connect(self._on_progress)
        self._downloader.finished.connect(self._on_downloaded)
        self._downloader.start()

    def _on_progress(self, done: int, total: int) -> None:
        if total > 0:
            pct = min(100, int(done * 100 / total))
            self.status.setText(f"正在下载 {pct}%  ·  {done / 1048576:.1f} / {total / 1048576:.1f} MB")
        else:
            self.status.setText(f"正在下载  ·  {done / 1048576:.1f} MB")

    def _on_downloaded(self, path: str, error: str) -> None:
        if error:
            self.status.setText(error)
            self.status.setStyleSheet(f"color: {ORANGE}; padding: 0;")
            self.go.setEnabled(True)
            self.go.setText("重试")
            self.later.setEnabled(True)
            return
        ok, msg = update.apply_update(__import__("pathlib").Path(path))
        if ok:
            self.status.setText("更新完成，程序即将重启…")
            self.status.setStyleSheet(f"color: {MINT}; padding: 0;")
            QTimer.singleShot(900, QApplication.instance().quit)
        else:
            self.status.setText(msg)
            self.status.setStyleSheet(f"color: {ORANGE}; padding: 0;")
            self.go.setEnabled(True)
            self.go.setText("重试")
            self.later.setEnabled(True)


# ---------------------------------------------------------------- 简易确认框


class ConfirmDialog(DarkDialog):
    def __init__(self, title: str, message: str, ok_text: str, parent=None) -> None:
        super().__init__(title, 360, parent=parent)
        body = self.body()
        text = QLabel(message)
        text.setWordWrap(True)
        text.setFont(ui_font(12))
        text.setStyleSheet(f"color: {TEXT_MID}; padding: 0;")
        body.addWidget(text)
        body.addSpacing(16)
        footer = QHBoxLayout()
        footer.addStretch(1)
        cancel = self._ghost("取消", 68)
        cancel.clicked.connect(self.reject)
        ok = self._primary(ok_text)
        ok.clicked.connect(self.accept)
        footer.addWidget(cancel)
        footer.addSpacing(8)
        footer.addWidget(ok)
        body.addLayout(footer)
        self.adjustSize()


# ---------------------------------------------------------------- 管理器


class ThemeManagerWindow(DarkDialog):
    theme_applied = Signal(str)
    edit_requested = Signal(str)

    def __init__(self, cfg, parent=None) -> None:
        super().__init__("角色主题", 540, 520, parent)
        self.cfg = cfg
        body = self.body()

        body.addWidget(self._hint(f"主题图片存放在 {char_theme.themes_root()}"))
        body.addSpacing(10)

        self.scroll = QScrollArea(self)
        self.scroll.setWidgetResizable(True)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        host = QWidget()
        self.list_layout = QVBoxLayout(host)
        self.list_layout.setContentsMargins(0, 0, 6, 0)
        self.list_layout.setSpacing(10)
        self.scroll.setWidget(host)
        body.addWidget(self.scroll, 1)
        body.addSpacing(12)

        footer = QHBoxLayout()
        footer.addStretch(1)
        new_btn = self._primary("新建主题")
        new_btn.clicked.connect(self._on_new)
        footer.addWidget(new_btn)
        body.addLayout(footer)

        self.reload_list()

    def reload_list(self) -> None:
        while self.list_layout.count():
            item = self.list_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()
        for info in char_theme.list_themes():
            self.list_layout.addWidget(self._row(info))
        self.list_layout.addStretch(1)

    def _row(self, info: char_theme.ThemeInfo) -> QWidget:
        row = QWidget()
        row.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        row.setObjectName("slotCard")
        row.setFixedHeight(78)
        layout = QHBoxLayout(row)
        layout.setContentsMargins(11, 11, 12, 11)
        layout.setSpacing(12)

        thumb = CheckerThumb(56, radius=9)
        thumb.set_pixmap(info.cover, "?")
        layout.addWidget(thumb)

        texts = QVBoxLayout()
        texts.setContentsMargins(0, 2, 0, 2)
        texts.setSpacing(4)
        name = QLabel(info.name)
        name.setFont(ui_font(14, QFont.Weight.DemiBold))
        name.setStyleSheet(f"color: {TEXT_HI}; padding: 0;")
        sub = QLabel(info.summary)
        sub.setFont(ui_font(11))
        sub.setStyleSheet(f"color: {TEXT_LOW}; padding: 0;")
        texts.addWidget(name)
        texts.addWidget(sub)
        texts.addStretch(1)
        layout.addLayout(texts, 1)

        if info.id == char_theme.resolve(self.cfg["char_theme"]):
            badge = QLabel("使用中")
            badge.setObjectName("badge")
            badge.setFont(ui_font(11))
            layout.addWidget(badge)

        if info.builtin:
            layout.addSpacing(4)
            return row

        use = self._ghost("使用", 54)
        use.clicked.connect(lambda _=False, i=info.id: self._on_apply(i))
        edit = self._ghost("编辑", 54)
        edit.clicked.connect(lambda _=False, i=info.id: self.edit_requested.emit(i))
        rename = self._ghost("重命名", 66)
        rename.clicked.connect(lambda _=False, i=info.id: self._on_rename(i))
        delete = self._ghost("删除", 54)
        delete.clicked.connect(lambda _=False, i=info.id: self._on_delete(i))
        for btn in (use, edit, rename, delete):
            btn.setFixedHeight(26)
            layout.addWidget(btn)
        return row

    # ---- 操作 ----

    def _on_new(self) -> None:
        dialog = NewThemeDialog(self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        try:
            info = char_theme.create_theme(dialog.name, dialog.copy_builtin)
        except (ValueError, OSError) as exc:
            return
        self.reload_list()
        self.theme_applied.emit(info.id)
        self.edit_requested.emit(info.id)

    def _on_apply(self, theme_id: str) -> None:
        self.theme_applied.emit(theme_id)
        self.reload_list()

    def _on_rename(self, theme_id: str) -> None:
        current = char_theme.display_name(theme_id)
        dialog = RenameDialog(current, self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        try:
            char_theme.rename_theme(theme_id, dialog.name)
        except ValueError:
            return
        self.reload_list()

    def _on_delete(self, theme_id: str) -> None:
        in_use = char_theme.resolve(self.cfg["char_theme"]) == theme_id
        message = "删除「{}」？图片会被一起删掉。".format(char_theme.display_name(theme_id))
        if in_use:
            message += "\n\n这个主题正在使用，删除后会自动切回「大肥鱼」。"
        confirm = ConfirmDialog("删除主题", message, "删除", self)
        if confirm.exec() != QDialog.DialogCode.Accepted:
            return
        char_theme.delete_theme(theme_id)
        if in_use:
            self.theme_applied.emit(char_theme.BUILTIN_ID)
        self.reload_list()


class RenameDialog(DarkDialog):
    def __init__(self, current: str, parent=None) -> None:
        super().__init__("重命名主题", 380, parent=parent)
        body = self.body()
        body.addWidget(self._section("名称"))
        body.addSpacing(7)
        self.edit = QLineEdit(current)
        self.edit.setStyleSheet(FIELD_QSS)
        self.edit.setMaxLength(24)
        body.addWidget(self.edit)
        body.addSpacing(6)
        self.message = QLabel("")
        self.message.setFont(ui_font(11))
        self.message.setStyleSheet(f"color: {ORANGE}; padding: 0;")
        body.addWidget(self.message)
        body.addSpacing(14)
        footer = QHBoxLayout()
        footer.addStretch(1)
        cancel = self._ghost("取消", 68)
        cancel.clicked.connect(self.reject)
        ok = self._primary("保存")
        ok.clicked.connect(self._accept)
        footer.addWidget(cancel)
        footer.addSpacing(8)
        footer.addWidget(ok)
        body.addLayout(footer)
        self.adjustSize()

    @property
    def name(self) -> str:
        return self.edit.text().strip()

    def _accept(self) -> None:
        ok, msg = char_theme.valid_name(self.edit.text())
        if not ok:
            self.message.setText(msg)
            return
        self.accept()
