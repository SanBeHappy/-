"""打包后自检：dist\\DeskMate\\DeskMate.exe 的版本必须等于 config.APP_VERSION。

打包时如果 exe 还被旧进程占用，PyInstaller 会失败或者写不进去，dist 里留下的
就是上一版；以前光看「打包完成」会误以为成功，结果把旧包当新包发出去。
这个脚本堵这个坑，顺便把 dist\\DeskMate 打成 DeskMate.zip、写 SHA256SUMS
（传 Release 用），并打印体积和 sha256 方便对照。

退出码：0 = 一致，1 = 不一致或文件缺失。
"""

from __future__ import annotations

import ctypes
import hashlib
import sys
import zipfile
from ctypes import wintypes
from pathlib import Path

ROOT = Path(__file__).resolve().parent
APP_DIR = ROOT / "dist" / "DeskMate"
EXE = APP_DIR / "DeskMate.exe"
ZIP = ROOT / "dist" / "DeskMate.zip"


class _FixedFileInfo(ctypes.Structure):
    _fields_ = [
        ("dwSignature", wintypes.DWORD),
        ("dwStrucVersion", wintypes.DWORD),
        ("dwFileVersionMS", wintypes.DWORD),
        ("dwFileVersionLS", wintypes.DWORD),
        ("dwProductVersionMS", wintypes.DWORD),
        ("dwProductVersionLS", wintypes.DWORD),
        ("dwFileFlagsMask", wintypes.DWORD),
        ("dwFileFlags", wintypes.DWORD),
        ("dwFileOS", wintypes.DWORD),
        ("dwFileType", wintypes.DWORD),
        ("dwFileSubtype", wintypes.DWORD),
        ("dwFileDateMS", wintypes.DWORD),
        ("dwFileDateLS", wintypes.DWORD),
    ]


def exe_version(path: Path) -> str:
    """读 PE 里的文件版本，形如 1.0.7.0；读不到返回空串。"""
    try:
        api = ctypes.windll.version
    except AttributeError:
        return ""
    size = api.GetFileVersionInfoSizeW(str(path), None)
    if not size:
        return ""
    buffer = ctypes.create_string_buffer(size)
    if not api.GetFileVersionInfoW(str(path), 0, size, buffer):
        return ""
    pointer = wintypes.LPVOID()
    length = wintypes.UINT()
    if not api.VerQueryValueW(buffer, "\\", ctypes.byref(pointer), ctypes.byref(length)):
        return ""
    info = ctypes.cast(pointer, ctypes.POINTER(_FixedFileInfo)).contents
    ms, ls = info.dwFileVersionMS, info.dwFileVersionLS
    return f"{ms >> 16}.{ms & 0xFFFF}.{ls >> 16}.{ls & 0xFFFF}"


def make_zip() -> None:
    """把 dist\\DeskMate 整个目录压成 DeskMate.zip（内容放在 zip 根上）。"""
    if ZIP.exists():
        ZIP.unlink()
    with zipfile.ZipFile(ZIP, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as zf:
        for item in sorted(APP_DIR.rglob("*")):
            if item.is_file():
                zf.write(item, item.relative_to(APP_DIR).as_posix())


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def main() -> int:
    sys.path.insert(0, str(ROOT))
    from config import APP_VERSION  # noqa: E402

    if not EXE.exists():
        print(f"  [X] 找不到 {EXE}")
        return 1

    found = exe_version(EXE)
    want = f"{APP_VERSION}.0"
    size = EXE.stat().st_size / 1048576
    digest = sha256(EXE)

    print(f"  期望版本 {want} / 实际文件版本 {found or '(读不到)'}")
    print(f"  体积 {size:.1f} MB")
    print(f"  sha256 {digest}")

    if found != want:
        print("  [X] 版本不一致，dist 里还是旧包，不要上传")
        return 1

    try:
        make_zip()
    except OSError as exc:
        print(f"  [X] 打 zip 失败：{exc}")
        return 1
    zip_digest = sha256(ZIP)
    zip_size = ZIP.stat().st_size / 1048576
    print(f"  已打包 {ZIP.name}（{zip_size:.1f} MB）")
    print(f"  zip sha256 {zip_digest}")

    sums = ROOT / "SHA256SUMS"
    try:
        sums.write_text(f"{zip_digest}  DeskMate.zip\n", encoding="utf-8")
        print(f"  已写入 {sums.name}（客户端下载完会拿它校验）")
    except OSError as exc:
        print(f"  [X] 写 SHA256SUMS 失败：{exc}")
        return 1
    print("  [OK] 版本一致")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
