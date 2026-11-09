"""检查更新：读 GitHub 仓库根目录的 VERSION 文件，和本地版本比一下。

选 VERSION 文件而不是 Releases，是因为发版流程最轻 —— 改个文件推上去就生效，
不用每次打包都去 GitHub 建 release。
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
import tempfile
import time
from pathlib import Path

from PySide6.QtCore import QObject, QUrl, Signal
from PySide6.QtGui import QDesktopServices
from PySide6.QtNetwork import QNetworkAccessManager, QNetworkReply, QNetworkRequest

REPO = "SanBeHappy/-"
BRANCH = "main"
VERSION_URL = f"https://raw.githubusercontent.com/{REPO}/{BRANCH}/VERSION"
CHANGELOG_URL = f"https://raw.githubusercontent.com/{REPO}/{BRANCH}/CHANGELOG.md"
ASSET_URL = f"https://raw.githubusercontent.com/{REPO}/{BRANCH}/release/DeskMate.exe"

UPDATE_DIR = Path(tempfile.gettempdir()) / "DeskMate-update"
PAGE_URL = f"https://github.com/{REPO}"

_NUM = re.compile(r"\d+")


def parse_version(text: str) -> tuple[int, ...]:
    """把 1.0.10 拆成 (1, 0, 10)，保证 10 比 9 大。"""
    return tuple(int(x) for x in _NUM.findall(text or "")[:3]) or (0,)


def is_newer(remote: str, local: str) -> bool:
    a, b = parse_version(remote), parse_version(local)
    size = max(len(a), len(b))
    a += (0,) * (size - len(a))
    b += (0,) * (size - len(b))
    return a > b


def parse_changelog(text: str, version: str) -> list[str]:
    """从 CHANGELOG 里挑出指定版本那一段的条目。"""
    items: list[str] = []
    inside = False
    for raw in (text or "").splitlines():
        line = raw.rstrip()
        if line.startswith("## "):
            if inside:
                break
            inside = line[3:].strip().lstrip("v") == version
            continue
        if inside and line.strip().startswith(("- ", "* ")):
            items.append(line.strip()[2:].strip())
    return items


def open_repo() -> None:
    QDesktopServices.openUrl(QUrl(PAGE_URL))


class UpdateChecker(QObject):
    """一次性的版本查询，成功失败都会回调。"""

    finished = Signal(str, str, list)   # (远端版本号, 错误信息, 更新日志条目)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._nam = QNetworkAccessManager(self)
        self._busy = False

    def check(self) -> None:
        if self._busy:
            return
        self._busy = True

        request = QNetworkRequest(QUrl(f"{VERSION_URL}?t={int(time.time())}"))
        request.setHeader(
            QNetworkRequest.KnownHeaders.UserAgentHeader,
            "Mozilla/5.0 DeskMate-UpdateCheck",
        )
        request.setTransferTimeout(10000)
        reply = self._nam.get(request)
        reply.finished.connect(lambda r=reply: self._on_done(r))

    def _on_done(self, reply: QNetworkReply) -> None:
        try:
            if reply.error() != QNetworkReply.NetworkError.NoError:
                self._busy = False
                self.finished.emit("", "网络不通，稍后再试", [])
                return
            text = bytes(reply.readAll()).decode("utf-8", "ignore").strip()
            match = re.search(r"\d+(?:\.\d+){0,2}", text)
            if not match:
                self._busy = False
                self.finished.emit("", "远端的版本文件读不出来", [])
                return
            version = match.group(0)
            self._fetch_notes(version)
        except Exception:
            self._busy = False
            self.finished.emit("", "检查更新失败", [])
        finally:
            reply.deleteLater()

    def _fetch_notes(self, version: str) -> None:
        """拿到版本号后顺手拉更新日志，失败也不影响提示。"""
        request = QNetworkRequest(QUrl(f"{CHANGELOG_URL}?t={int(time.time())}"))
        request.setHeader(
            QNetworkRequest.KnownHeaders.UserAgentHeader,
            "Mozilla/5.0 DeskMate-UpdateCheck",
        )
        request.setTransferTimeout(10000)
        reply = self._nam.get(request)

        def done(r=reply) -> None:
            self._busy = False
            notes: list[str] = []
            try:
                if r.error() == QNetworkReply.NetworkError.NoError:
                    text = bytes(r.readAll()).decode("utf-8", "ignore")
                    notes = parse_changelog(text, version)
            except Exception:
                notes = []
            finally:
                r.deleteLater()
            self.finished.emit(version, "", notes)

        reply.finished.connect(done)


# ---------------------------------------------------------------- 下载与替换


class UpdateDownloader(QObject):
    """把新版本 exe 下到临时目录，带进度回调。"""

    progress = Signal(int, int)      # 已下载字节, 总字节
    finished = Signal(str, str)      # 文件路径, 错误

    MIN_SIZE = 5 * 1024 * 1024       # 小于 5MB 一定是坏包

    def __init__(self) -> None:
        super().__init__()
        self._nam = QNetworkAccessManager(self)
        self._file = None
        self._target: Path | None = None
        self._part: Path | None = None

    def start(self) -> None:
        UPDATE_DIR.mkdir(parents=True, exist_ok=True)
        self._target = UPDATE_DIR / "DeskMate.exe"
        self._part = UPDATE_DIR / "DeskMate.part"
        try:
            self._file = open(self._part, "wb")
        except OSError as exc:
            self.finished.emit("", f"写不了临时目录：{exc}")
            return

        request = QNetworkRequest(QUrl(f"{ASSET_URL}?t={int(time.time())}"))
        request.setHeader(
            QNetworkRequest.KnownHeaders.UserAgentHeader,
            "Mozilla/5.0 DeskMate-Update",
        )
        request.setTransferTimeout(300000)
        reply = self._nam.get(request)
        reply.downloadProgress.connect(self.progress.emit)
        reply.readyRead.connect(lambda r=reply: self._on_chunk(r))
        reply.finished.connect(lambda r=reply: self._on_done(r))

    def _on_chunk(self, reply: QNetworkReply) -> None:
        if self._file is None:
            return
        data = bytes(reply.readAll())
        if data:
            try:
                self._file.write(data)
            except OSError:
                pass

    def _on_done(self, reply: QNetworkReply) -> None:
        error = ""
        if reply.error() != QNetworkReply.NetworkError.NoError:
            error = "下载失败，检查网络后再试"
        try:
            if self._file is not None:
                self._file.close()
                self._file = None
        except OSError:
            pass

        if not error and self._part is not None and self._target is not None:
            size = self._part.stat().st_size if self._part.exists() else 0
            if size < self.MIN_SIZE:
                error = "下载到的文件不完整"
            else:
                try:
                    os.replace(self._part, self._target)
                except OSError as exc:
                    error = f"保存失败：{exc}"
        reply.deleteLater()

        if error:
            self.finished.emit("", error)
        else:
            self.finished.emit(str(self._target), "")


def can_self_update() -> bool:
    """只有打包后的 exe 才能替换自己。"""
    return bool(getattr(sys, "frozen", False))


def apply_update(new_exe: Path) -> tuple[bool, str]:
    """用批处理在程序退出后替换 exe 并重启。返回是否已交给脚本。"""
    target = Path(sys.executable).resolve() if getattr(sys, "frozen", False) else None
    if target is None:
        return False, "开发模式下不支持自动更新"
    if not Path(new_exe).exists():
        return False, "找不到下载好的文件"

    script = UPDATE_DIR / "apply.bat"
    backup = target.with_suffix(".old.exe")
    try:
        script.write_text(
            "@echo off\r\n"
            "chcp 65001 >nul\r\n"
            "timeout /t 2 /nobreak >nul\r\n"
            "taskkill /f /im \"DeskMate.exe\" >nul 2>&1\r\n"
            "timeout /t 1 /nobreak >nul\r\n"
            f'if exist "{backup}" del /f /q "{backup}" >nul 2>&1\r\n'
            f'copy /y "{target}" "{backup}" >nul 2>&1\r\n'
            f'move /y "{new_exe}" "{target}" >nul 2>&1\r\n'
            f'start "" "{target}"\r\n'
            'del /f /q "%~f0" >nul 2>&1\r\n',
            encoding="utf-8",
        )
    except OSError as exc:
        return False, f"写更新脚本失败：{exc}"

    try:
        subprocess.Popen(
            ["cmd", "/c", str(script)],
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            close_fds=True,
        )
    except OSError as exc:
        return False, f"启动更新脚本失败：{exc}"
    return True, ""
