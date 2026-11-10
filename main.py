"""工位伴侣 · 桌面小程序入口。

功能一：下班提醒（准点 + 提前预警 + 加班计时）
功能二：久坐提醒（定时起身 + 午休免打扰 + 重复催办）
"""

from __future__ import annotations

import math
import os
import sys
import threading
import time
import traceback
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import QPoint, QTimer
from PySide6.QtGui import QCursor, QGuiApplication
from PySide6.QtNetwork import QLocalServer, QLocalSocket
from PySide6.QtGui import QActionGroup
from PySide6.QtWidgets import QApplication, QMenu, QSystemTrayIcon

import char_theme
import update
from card import MainCard
from config import APP_TITLE, APP_VERSION, Config
from engine import Engine
from settings import SettingsWindow
from theme_ui import OpacityDialog, ThemeEditorWindow, ThemeManagerWindow, UpdateDialog
from theme import MINT, ORANGE, SETTINGS_QSS, app_icon
from toast import (
    ToastManager,
    show_off_again,
    show_off_work,
    show_pre_off,
    show_sit,
    show_drink,
    show_report,
)

SERVER_NAME = "DeskMate.SingleInstance.v1"
TICK_MS = 250

# 菜单里的透明度档位；40% 以下字就看不清了，所以下限压到 40
OPACITY_STEPS = (100, 90, 80, 70, 60, 50)
OPACITY_MIN = 40

LOG_FILE = Path(os.environ.get("APPDATA") or Path.home()) / "DeskMate" / "error.log"


def log(message: str) -> None:
    """轻量日志，方便排查启动异常（打包后没有控制台）。"""
    try:
        LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
        with LOG_FILE.open("a", encoding="utf-8") as handle:
            handle.write(f"{datetime.now():%Y-%m-%d %H:%M:%S}  {message}\n")
    except Exception:
        pass


def _excepthook(exc_type, exc, tb) -> None:
    log("未捕获异常:\n" + "".join(traceback.format_exception(exc_type, exc, tb)))
    sys.__excepthook__(exc_type, exc, tb)


sys.excepthook = _excepthook


# ---------------------------------------------------------------- 声音


def play_sound(kind: str) -> None:
    """用系统自带 winsound 合成两声轻提示，避免额外依赖。"""

    def run() -> None:
        try:
            import winsound

            if kind == "off":
                for freq, dur in ((784, 110), (988, 110), (1319, 190)):
                    winsound.Beep(freq, dur)
            elif kind == "sit":
                for freq, dur in ((880, 100), (1175, 150)):
                    winsound.Beep(freq, dur)
            else:
                winsound.Beep(1046, 110)
        except Exception:
            pass

    threading.Thread(target=run, daemon=True).start()


# ---------------------------------------------------------------- 主程序


class DeskMate:
    def __init__(self, app: QApplication) -> None:
        self.app = app
        self.cfg = Config()
        # 主题可能被外部删掉了，静默回落到内置并回写
        resolved = char_theme.resolve(self.cfg["char_theme"])
        if resolved != self.cfg["char_theme"]:
            self.cfg["char_theme"] = resolved
            self.cfg.save()
        self.engine = Engine(self.cfg)
        self.toasts = ToastManager(self.cfg)
        self.settings_window: SettingsWindow | None = None
        self.theme_manager: ThemeManagerWindow | None = None
        self.theme_editor: ThemeEditorWindow | None = None
        self.opacity_dialog: OpacityDialog | None = None
        self.updater: update.UpdateChecker | None = None
        self._silent_check = False
        # 每 30 分钟悄悄查一次新版本，有更新就在卡片上亮红字
        self.update_timer = QTimer(self.app)
        self.update_timer.setInterval(30 * 60 * 1000)
        self.update_timer.timeout.connect(lambda: self.check_update(silent=True))
        self.update_timer.start()
        QTimer.singleShot(20000, lambda: self.check_update(silent=True))

        self.card = MainCard(self.cfg, self.engine)
        self.card.request_settings.connect(self.open_settings)
        self.card.request_menu.connect(self.popup_menu)
        self.card.request_hide.connect(self.toggle_card)
        self.card.request_drink.connect(self.drink_done)
        self.card.request_update.connect(lambda: self.check_update())
        self.toasts.anchor = self._toast_anchor

        self.tray = self._build_tray()
        self.apply_opacity(self.cfg["opacity"], persist=False)

        self.timer = QTimer()
        self.timer.setInterval(TICK_MS)
        self.timer.timeout.connect(self.on_tick)
        self.timer.start()

        self.card.show()
        self.card.ensure_position()
        QTimer.singleShot(0, self.on_tick)

    # ------------------------------------------------------------ 托盘

    def _build_tray(self) -> QSystemTrayIcon | None:
        if not QSystemTrayIcon.isSystemTrayAvailable():
            return None
        tray = QSystemTrayIcon(app_icon(), self.app)
        tray.setToolTip(APP_TITLE)

        menu = QMenu()
        menu.setStyleSheet(SETTINGS_QSS)
        self.action_show = menu.addAction("显示卡片")
        self.action_show.triggered.connect(self.show_card)
        menu.addSeparator()
        self.action_stand = menu.addAction("我起身了 · 重新计时")
        self.action_stand.triggered.connect(self.engine.stand_up)
        self.action_drink = menu.addAction("喝水重置")
        self.action_drink.triggered.connect(self.reset_drink)
        self.action_pause = menu.addAction("暂停久坐提醒 30 分钟")
        self.action_pause.triggered.connect(self._toggle_pause)
        menu.addSeparator()
        self.menu_theme = menu.addMenu("角色主题")
        self.menu_opacity = menu.addMenu("窗口透明度")
        self._build_opacity_menu()
        menu.addSeparator()
        self.action_update = menu.addAction(f"检查更新(V{APP_VERSION})")
        self.action_update.triggered.connect(self.check_update)
        action_settings = menu.addAction("设置…")
        action_settings.triggered.connect(self.open_settings)
        action_quit = menu.addAction("退出")
        action_quit.triggered.connect(self.quit)

        menu.aboutToShow.connect(self._sync_menu)
        tray.setContextMenu(menu)
        tray.activated.connect(self._on_tray_activated)
        tray.show()
        self._rebuild_theme_menu()
        return tray

    def _sync_menu(self) -> None:
        self.action_show.setText("隐藏卡片" if self.card.isVisible() else "显示卡片")
        paused = bool(self.engine.pause_until)
        self.action_pause.setText(
            "恢复久坐提醒" if paused else "暂停久坐提醒 30 分钟"
        )
        drink_on = bool(self.cfg["drink_enabled"])
        self.action_drink.setEnabled(drink_on)
        if drink_on:
            left = self.engine.snapshot.drink_left
            self.action_drink.setText(
                f"喝水重置（还剩 {left} 分钟）" if left > 0 else "喝水重置"
            )
        else:
            self.action_drink.setText("喝水重置（提醒已关闭）")
        self._rebuild_theme_menu()
        self._sync_opacity_menu()

    def _rebuild_theme_menu(self) -> None:
        sub = self.menu_theme
        sub.clear()
        group = QActionGroup(sub)
        group.setExclusive(True)
        current = char_theme.resolve(self.cfg["char_theme"])
        for info in char_theme.list_themes():
            act = sub.addAction(info.name)
            act.setCheckable(True)
            act.setChecked(info.id == current)
            act.triggered.connect(lambda _=False, i=info.id: self.apply_theme(i))
            group.addAction(act)
        sub.addSeparator()
        manage = sub.addAction("管理主题…")
        manage.triggered.connect(self.open_theme_manager)
        self._theme_group = group

    # ------------------------------------------------------------ 透明度

    def _opacity_value(self) -> int:
        try:
            value = int(self.cfg["opacity"])
        except (TypeError, ValueError):
            value = 100
        return max(OPACITY_MIN, min(100, value))

    def _build_opacity_menu(self) -> None:
        sub = self.menu_opacity
        sub.clear()
        group = QActionGroup(sub)
        group.setExclusive(True)
        self._opacity_actions: dict[int, object] = {}
        for value in OPACITY_STEPS:
            text = f"{value}% · 不透明" if value == 100 else f"{value}%"
            act = sub.addAction(text)
            act.setCheckable(True)
            act.triggered.connect(lambda _=False, v=value: self.apply_opacity(v))
            group.addAction(act)
            self._opacity_actions[value] = act
        sub.addSeparator()
        custom = sub.addAction("自定义…")
        custom.triggered.connect(self.open_opacity_dialog)
        self._opacity_group = group
        self._sync_opacity_menu()

    def _sync_opacity_menu(self) -> None:
        if not hasattr(self, "_opacity_actions"):
            return
        value = self._opacity_value()
        for step, act in self._opacity_actions.items():
            act.setChecked(step == value)
        if value in self._opacity_actions:
            self.menu_opacity.setTitle(f"窗口透明度（{value}%）")
        else:
            self.menu_opacity.setTitle(f"窗口透明度（{value}% · 自定义）")

    def apply_opacity(self, value: int, persist: bool = True) -> None:
        value = max(OPACITY_MIN, min(100, int(value)))
        self.cfg["opacity"] = value
        if persist:
            self.cfg.save()
        self.card.setWindowOpacity(value / 100.0)
        self._sync_opacity_menu()

    def open_opacity_dialog(self) -> None:
        if self.opacity_dialog is not None and self.opacity_dialog.isVisible():
            self.opacity_dialog.raise_()
            self.opacity_dialog.activateWindow()
            return
        dialog = OpacityDialog(self._opacity_value(), None)
        dialog.setWindowIcon(app_icon())
        dialog.previewed.connect(lambda v: self.apply_opacity(v, persist=False))
        dialog.confirmed.connect(self.apply_opacity)
        self.opacity_dialog = dialog
        dialog.show()
        dialog.raise_()
        dialog.activateWindow()

    def _toggle_pause(self) -> None:
        if self.engine.pause_until:
            self.engine.resume_sit()
        else:
            self.engine.pause_sit(30)

    def _on_tray_activated(self, reason) -> None:
        if reason in (
            QSystemTrayIcon.ActivationReason.Trigger,
            QSystemTrayIcon.ActivationReason.DoubleClick,
        ):
            self.toggle_card()

    # ------------------------------------------------------------ 窗口

    def show_card(self) -> None:
        self.card.show()
        self.card.ensure_position()
        self.card.raise_()

    def toggle_card(self) -> None:
        if self.card.isVisible():
            self.card.hide()
        else:
            self.show_card()

    def popup_menu(self, global_pos: QPoint) -> None:
        if not self.tray or not self.tray.contextMenu():
            return
        menu = self.tray.contextMenu()
        self._sync_menu()
        menu.popup(global_pos)

    def open_settings(self) -> None:
        if self.settings_window is not None and self.settings_window.isVisible():
            self.settings_window.raise_()
            self.settings_window.activateWindow()
            return
        self.settings_window = SettingsWindow(self.cfg, None)
        self.settings_window.saved.connect(self.on_settings_saved)
        self.settings_window.request_themes.connect(self.open_theme_manager)
        self.settings_window.weather_changed.connect(self.refresh_weather)
        self.settings_window.show()
        self.settings_window.setWindowIcon(app_icon())
        self._center_settings()
        self.settings_window.raise_()
        self.settings_window.activateWindow()

    def apply_theme(self, theme_id: str) -> None:
        theme_id = char_theme.resolve(theme_id)
        self.cfg["char_theme"] = theme_id
        self.cfg.save()
        self.card.apply_theme(theme_id)
        self.on_tick()
        if self.settings_window is not None and self.settings_window.isVisible():
            self.settings_window.refresh_theme()

    def open_theme_manager(self) -> None:
        if self.theme_manager is None:
            self.theme_manager = ThemeManagerWindow(self.cfg, None)
            self.theme_manager.theme_applied.connect(self.apply_theme)
            self.theme_manager.edit_requested.connect(self.open_theme_editor)
        else:
            self.theme_manager.reload_list()
        self.theme_manager.show()
        self.theme_manager.setWindowIcon(app_icon())
        self.theme_manager.raise_()
        self.theme_manager.activateWindow()

    def open_theme_editor(self, theme_id: str) -> None:
        if char_theme.theme_dir(theme_id) is None:
            return
        if self.theme_editor is not None:
            self.theme_editor.close()
            self.theme_editor.deleteLater()
        self.theme_editor = ThemeEditorWindow(theme_id, self.cfg, None)
        self.theme_editor.theme_applied.connect(self.apply_theme)
        self.theme_editor.theme_touched.connect(self.card.apply_theme)
        self.theme_editor.show()
        self.theme_editor.setWindowIcon(app_icon())
        self.theme_editor.raise_()
        self.theme_editor.activateWindow()

    def _center_settings(self) -> None:
        window = self.settings_window
        if window is None:
            return
        screen = QGuiApplication.screenAt(QCursor.pos()) or QGuiApplication.primaryScreen()
        area = screen.availableGeometry()
        window.adjustSize()
        window.move(
            area.center().x() - window.width() // 2,
            area.center().y() - window.height() // 2,
        )

    def on_settings_saved(self) -> None:
        # 只刷新界面，不动久坐计时 —— 改设置不该把「已经坐了多久」清零
        self.on_tick()

    def drink_done(self) -> None:
        """点了「喝了」：记一杯、重新计时，并让她当场喝一杯。"""
        self.engine.drink_done()
        self.card.fish.react("drink")
        self.on_tick()

    def release_instance(self) -> None:
        """更新前先让出单实例锁，否则新进程会以为「已经有实例在跑」而直接退出。"""
        server = getattr(self.app, "_deskmate_server", None)
        if server is None:
            return
        try:
            server.close()
        except Exception:
            pass
        try:
            QLocalServer.removeServer(SERVER_NAME)
        except Exception:
            pass
        self.app._deskmate_server = None

    def restore_instance(self) -> None:
        """更新失败、旧版本还在跑时，把锁重新拿回来。"""
        if getattr(self.app, "_deskmate_server", None) is not None:
            return
        self.app._deskmate_server = serve_single_instance(self.show_card)

    def _toast_anchor(self):
        """提醒窗贴在卡片旁边，别压住倒计时。"""
        if self.card is None or not self.card.isVisible():
            return None
        return self.card.frameGeometry()

    def reset_drink(self) -> None:
        """托盘 / 卡片菜单：把喝水计时归零（不记杯数）。"""
        self.engine.reset_drink()
        self.on_tick()

    def reset_sit(self) -> None:
        """卡片上点「起来了」：重置久坐计时。"""
        self.engine.stand_up()
        self.on_tick()

    def check_update(self, silent: bool = False) -> None:
        """silent=True 时只在卡片上亮提示，不弹窗、不打扰（后台轮询用）。"""
        if self.updater is None:
            self.updater = update.UpdateChecker()   # DeskMate 不是 QObject，不能当 parent
            self.updater.finished.connect(self.on_update_result)
        if getattr(self.updater, "_busy", False):
            return
        self._silent_check = silent
        self.updater.check()

    def on_update_result(self, remote: str, error: str, notes: list) -> None:
        silent = self._silent_check
        self._silent_check = False
        newer = bool(remote) and not error and update.is_newer(remote, APP_VERSION)
        self.card.set_update_available(newer)

        if error:
            if silent:
                return
            self.toasts.show(
                ORANGE, "检查更新失败", error,
                [("知道了", "primary", "noop")], self.on_toast_action,
                auto_close_ms=12000,
            )
            return
        if newer:
            if silent:
                return          # 后台查到的，只亮红字，不打断
            # 弹框自己负责下载和应用更新，这里只管把窗口弹出来
            dialog = UpdateDialog(remote, APP_VERSION, notes, None)
            dialog.setWindowIcon(app_icon())
            dialog.before_apply = self.release_instance
            dialog.after_fail = self.restore_instance
            dialog.exec()
        elif not silent:
            self.toasts.show(
                MINT,
                "已经是最新版本",
                f"当前 v{APP_VERSION}，有新版本会在这里提醒你。",
                [("知道了", "primary", "noop")], self.on_toast_action,
                auto_close_ms=12000,
            )

    def refresh_weather(self) -> None:
        """城市改了立刻重拉，不用等下一个 30 分钟。"""
        self.card.weather_service.refresh()

    # ------------------------------------------------------------ 心跳

    def on_tick(self) -> None:
        now = datetime.now()
        events = self.engine.tick(now)
        pulse = 0.5 + 0.5 * math.sin(now.timestamp() * 2 * math.pi / 1.9)
        self.card.refresh(self.engine.snapshot, pulse)
        self._update_tooltip()

        for event in events:
            self.dispatch(event)

    def _update_tooltip(self) -> None:
        if not self.tray:
            return
        snap = self.engine.snapshot
        if snap.phase == "off":
            text = "已下班 · 记得关电脑"
        elif snap.phase == "rest":
            text = "今天休息"
        else:
            hours, rest = divmod(max(0, snap.seconds_left), 3600)
            text = f"距离下班 {hours} 小时 {rest // 60} 分"
        if snap.sit_active:
            text += f" · 久坐 {int(snap.sit_minutes)} 分钟"
        self.tray.setToolTip(f"{APP_TITLE} · {text}")

    def dispatch(self, event) -> None:
        if event.kind == "pre_off":
            self._sound("pre")
            show_pre_off(self.toasts, event.minutes, self.on_toast_action)
        elif event.kind == "off_work":
            self._sound("off")
            self.card.fish.react("off")
            show_off_work(self.toasts, self.on_toast_action)
        elif event.kind == "off_again":
            self._sound("off")
            show_off_again(self.toasts, self.on_toast_action)
        elif event.kind == "drink":
            self.card.fish.react("sit")
            show_drink(self.toasts, self.engine.snapshot.drink_cups, self.on_toast_action)
            return
        elif event.kind == "weekly_report":
            self._sound("pre")
            show_report(self.toasts, event.monthly, self.on_toast_action)
            return
        elif event.kind == "sit":
            self._sound("sit")
            self.card.fish.react("sit")
            show_sit(
                self.toasts, event.minutes, event.hard, self.on_toast_action
            )

    def _sound(self, kind: str) -> None:
        if self.cfg["sound"]:
            play_sound(kind)

    def on_toast_action(self, key: str) -> None:
        if key == "sit_stand":
            self.engine.stand_up()
        elif key == "sit_ok":
            pass
        elif key == "sit_snooze":
            self.engine.snooze_sit()
        elif key == "drink_ok":
            self.drink_done()
        elif key == "drink_snooze":
            self.engine.snooze_drink(10)
        elif key == "open_repo":
            update.open_repo()
        elif key == "report_ok":
            self.engine.mark_report_done()
        elif key == "report_snooze":
            self.engine.snooze_report(10)
        elif key == "off_snooze":
            self.engine.snooze_off(10)
        self.on_tick()

    # ------------------------------------------------------------ 退出

    def quit(self) -> None:
        try:
            self.card.remember_position()
        except Exception:
            pass
        if self.tray:
            self.tray.hide()
        self.app.quit()


# ---------------------------------------------------------------- 单实例


def already_running() -> bool:
    """只有在对方真的应答时才算已有实例，避免残留管道把程序挡在门外。"""
    socket = QLocalSocket()
    socket.connectToServer(SERVER_NAME)
    if not socket.waitForConnected(250):
        return False
    socket.write(b"ping")
    socket.flush()
    socket.waitForBytesWritten(250)
    alive = socket.waitForReadyRead(400)
    socket.disconnectFromServer()
    return alive


def wait_previous_instance() -> bool:
    """返回 True 表示不该启动（已有实例在跑）。

    更新后重启带 --restarted：直接接管，不去等旧进程让出锁。
    以前是「等它退出，最多 10 秒」，但旧进程正等着新进程写启动标记，
    两边互等，最后一起超时 —— 表现就是「更新到 100% 提示失败」。
    serve_single_instance() 里本来就会 removeServer 再 listen，
    直接接管不会有两个实例长期并存（旧进程看到标记就退）。
    """
    if update.RESTART_FLAG in sys.argv:
        return False
    return already_running()


def serve_single_instance(on_ping) -> QLocalServer:
    QLocalServer.removeServer(SERVER_NAME)
    server = QLocalServer()
    server.listen(SERVER_NAME)

    def handle() -> None:
        while server.hasPendingConnections():
            conn = server.nextPendingConnection()

            def respond(c=conn) -> None:
                try:
                    c.readAll()
                    c.write(b"pong")
                    c.flush()
                    c.disconnectFromServer()
                except Exception:
                    pass
                on_ping()

            conn.readyRead.connect(respond)
            QTimer.singleShot(600, conn.deleteLater)

    server.newConnection.connect(handle)
    return server


def main() -> int:
    try:
        app = QApplication(sys.argv)
        app.setApplicationName("DeskMate")
        app.setApplicationDisplayName(APP_TITLE)
        app.setQuitOnLastWindowClosed(False)
        app.setWindowIcon(app_icon())

        if wait_previous_instance():
            return 0

        mate = DeskMate(app)
        update.mark_started()
        # 上一版留的 .old.exe 等一会儿再删：万一本进程起不来，老版本还要靠它还原
        QTimer.singleShot(20000, update.drop_old_copy)
        server = serve_single_instance(mate.show_card)
        app._deskmate_server = server  # 保活

        code = app.exec()
        mate.quit()
        return code
    except Exception:
        log("启动失败:\n" + traceback.format_exc())
        raise


if __name__ == "__main__":
    sys.exit(main())
