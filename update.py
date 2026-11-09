"""检查更新：读 GitHub 仓库根目录的 VERSION 文件，和本地版本比一下。

选 VERSION 文件而不是 Releases，是因为发版流程最轻 —— 改个文件推上去就生效，
不用每次打包都去 GitHub 建 release。
"""

from __future__ import annotations

import re
import time

from PySide6.QtCore import QObject, QUrl, Signal
from PySide6.QtGui import QDesktopServices
from PySide6.QtNetwork import QNetworkAccessManager, QNetworkReply, QNetworkRequest

REPO = "SanBeHappy/-"
BRANCH = "main"
VERSION_URL = f"https://raw.githubusercontent.com/{REPO}/{BRANCH}/VERSION"
CHANGELOG_URL = f"https://raw.githubusercontent.com/{REPO}/{BRANCH}/CHANGELOG.md"
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
