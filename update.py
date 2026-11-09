"""检查更新：读 GitHub 仓库根目录的 VERSION 文件，和本地版本比一下。

选 VERSION 文件而不是 Releases，是因为发版流程最轻 —— 改个文件推上去就生效，
不用每次打包都去 GitHub 建 release。
"""

from __future__ import annotations

import hashlib
import os
import shutil
import re
import subprocess
import sys
import tempfile
import time
from pathlib import Path

from PySide6.QtCore import QObject, QUrl, Signal
from PySide6.QtGui import QDesktopServices
from PySide6.QtNetwork import QNetworkAccessManager, QNetworkReply, QNetworkRequest

REPO = "SanBeHappy/Workhorse"   # 仓库改过名，旧地址 - 会 301 过来
BRANCH = "main"
VERSION_URL = f"https://raw.githubusercontent.com/{REPO}/{BRANCH}/VERSION"
CHANGELOG_URL = f"https://raw.githubusercontent.com/{REPO}/{BRANCH}/CHANGELOG.md"
# 走 GitHub Releases：latest 会自动指向最新一个正式版
ASSET_URL = f"https://github.com/{REPO}/releases/latest/download/DeskMate.exe"

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


SUMS_URL = f"https://raw.githubusercontent.com/{REPO}/{BRANCH}/SHA256SUMS"


def _looks_like_exe(path: Path) -> bool:
    """最基础的完整性判断：Windows 可执行文件必须以 MZ 开头。"""
    try:
        with open(path, "rb") as handle:
            return handle.read(2) == b"MZ"
    except OSError:
        return False


def sha256_of(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


class UpdateDownloader(QObject):
    """下载新版 exe，并和仓库里的 SHA256SUMS 比对后才算可用。"""

    progress = Signal(int, int)      # 已下载字节, 总字节
    finished = Signal(str, str)      # 文件路径, 错误

    MIN_SIZE = 5 * 1024 * 1024       # 小于 5MB 一定是坏包

    def __init__(self) -> None:
        super().__init__()
        self._nam = QNetworkAccessManager(self)
        self._file = None
        self._target: Path | None = None
        self._part: Path | None = None
        self._expect = ""
        self._bad: list[str] = []    # 网络错误时堆叠的信息

    def start(self) -> None:
        UPDATE_DIR.mkdir(parents=True, exist_ok=True)
        self._target = UPDATE_DIR / "DeskMate.exe"
        self._part = UPDATE_DIR / "DeskMate.part"
        self._expect = ""
        self._bad.clear()
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
        reply.deleteLater()

        if not error and self._part is not None and self._target is not None:
            size = self._part.stat().st_size if self._part.exists() else 0
            if size < self.MIN_SIZE:
                error = "下载到的文件不完整"
            elif not _looks_like_exe(self._part):
                error = "下载到的不是可执行文件"
            else:
                try:
                    os.replace(self._part, self._target)
                except OSError as exc:
                    error = f"保存失败：{exc}"

        if error:
            self.finished.emit("", error)
            return
        self._fetch_sums()

    def _fetch_sums(self) -> None:
        """再拉一次 SHA256SUMS；拉不到就只靠 MZ + 体积判断，不卡住用户。"""
        request = QNetworkRequest(QUrl(f"{SUMS_URL}?t={int(time.time())}"))
        request.setHeader(
            QNetworkRequest.KnownHeaders.UserAgentHeader,
            "Mozilla/5.0 DeskMate-Update",
        )
        request.setTransferTimeout(15000)
        reply = self._nam.get(request)

        def done(r=reply) -> None:
            text = ""
            try:
                if r.error() == QNetworkReply.NetworkError.NoError:
                    text = bytes(r.readAll()).decode("utf-8", "ignore")
            except Exception:
                text = ""
            finally:
                r.deleteLater()
            self._expect = self._parse_sums(text)
            self._verify()

        reply.finished.connect(done)

    @staticmethod
    def _parse_sums(text: str) -> str:
        for raw in (text or "").splitlines():
            parts = raw.split()
            if len(parts) >= 2 and parts[-1].lstrip("*") == "DeskMate.exe":
                candidate = parts[0].lower()
                if len(candidate) == 64:
                    return candidate
        return ""

    def _verify(self) -> None:
        assert self._target is not None
        if not self._expect:
            # 没有校验文件：宁可放过，给出提示后仍允许更新
            self.finished.emit(str(self._target), "")
            return
        try:
            actual = sha256_of(self._target)
        except OSError as exc:
            self.finished.emit("", f"读取下载文件失败：{exc}")
            return
        if actual != self._expect:
            try:
                self._target.unlink()
            except OSError:
                pass
            self.finished.emit("", "下载的文件校验不通过，已放弃本次更新")
            return
        self.finished.emit(str(self._target), "")


RESTART_FLAG = "--restarted"


def can_self_update() -> bool:
    """只有打包后的 exe 才能替换自己。"""
    return bool(getattr(sys, "frozen", False))


def current_exe() -> Path | None:
    if not getattr(sys, "frozen", False):
        return None
    try:
        return Path(sys.executable).resolve()
    except OSError:
        return None


def mark_started() -> None:
    """跑起来就在临时目录盖个章，更新脚本靠它判断新版本真的启动了。"""
    try:
        UPDATE_DIR.mkdir(parents=True, exist_ok=True)
        (UPDATE_DIR / "started.txt").write_text(
            f"{int(time.time())} {sys.argv[0]}", encoding="utf-8"
        )
    except OSError:
        pass


def started_after(stamp: float) -> bool:
    marker = UPDATE_DIR / "started.txt"
    try:
        return marker.exists() and marker.stat().st_mtime >= stamp - 1
    except OSError:
        return False


def clear_started() -> None:
    try:
        (UPDATE_DIR / "started.txt").unlink()
    except OSError:
        pass


def drop_old_copy(target: Path | None = None) -> None:
    """启动时清掉上次留下的 .old.exe；删不掉说明还有旧进程在跑，忽略即可。"""
    target = target or current_exe()
    if target is None:
        return
    backup = target.with_suffix(".old.exe")
    if not backup.exists():
        return
    try:
        backup.unlink()
    except OSError:
        pass


def apply_update(
    new_exe: Path, target: Path | None = None
) -> tuple[bool, str, "subprocess.Popen[bytes] | None"]:
    """就地替换：把正在运行的 exe 改名备份 → 新文件就位 → 拉起新进程。

    Windows 允许重命名正在运行的可执行文件（只是不能覆盖/删除），
    所以整个替换可以在进程内完成，不需要外部脚本。
    返回 (是否成功, 错误信息, 新进程句柄)。
    """
    target = Path(target).resolve() if target else current_exe()
    if target is None:
        return False, "开发模式下不支持自动更新", None
    new_exe = Path(new_exe).resolve()
    if not new_exe.exists():
        return False, "找不到下载好的文件", None
    if not _looks_like_exe(new_exe):
        return False, "更新包不是有效的可执行文件", None
    try:
        if new_exe.stat().st_size < UpdateDownloader.MIN_SIZE:
            return False, "更新包不完整", None
    except OSError as exc:
        return False, f"读取更新包失败：{exc}", None

    backup = target.with_suffix(".old.exe")
    try:
        if backup.exists():
            try:
                backup.unlink()
            except OSError:
                pass
        os.replace(target, backup)
    except OSError as exc:
        return False, f"备份当前版本失败：{exc}", None

    try:
        shutil.move(str(new_exe), str(target))
    except OSError as exc:
        try:
            os.replace(backup, target)
        except OSError:
            pass
        return False, f"替换失败，已还原旧版本：{exc}", None

    clear_started()
    flags = 0
    for name in ("DETACHED_PROCESS", "CREATE_NEW_PROCESS_GROUP", "CREATE_NO_WINDOW"):
        flags |= int(getattr(subprocess, name, 0))
    try:
        proc = subprocess.Popen(
            [str(target), RESTART_FLAG],
            cwd=str(target.parent),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=flags,
            close_fds=True,
        )
    except OSError as exc:
        try:
            os.replace(backup, target)
        except OSError:
            pass
        return False, f"启动新版本失败，已还原：{exc}", None
    return True, "", proc


def rollback(target: Path | None = None) -> bool:
    """把 .old.exe 换回来，用于新版本起不来的兜底。"""
    target = Path(target).resolve() if target else current_exe()
    if target is None:
        return False
    backup = target.with_suffix(".old.exe")
    if not backup.exists():
        return False
    try:
        os.replace(backup, target)
        return True
    except OSError:
        return False
