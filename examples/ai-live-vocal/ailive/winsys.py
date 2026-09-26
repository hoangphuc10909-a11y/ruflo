"""Kiểm tra hệ thống Windows: Cubase, quyền Admin, TikTok LIVE Studio, plugin, cổng MIDI.

Chỉ ĐỌC thông tin — không sửa Cubase, không đụng bản quyền.
Đọc tiêu đề cửa sổ bằng GetWindowTextW hoạt động cả khi Cubase chạy quyền Admin.
"""
from __future__ import annotations

import ctypes
import os
import platform
import subprocess
from pathlib import Path
from typing import Dict, List, Optional

IS_WIN = platform.system() == "Windows"

PLUGIN_HINTS = {
    "Auto-Tune": ("auto-tune", "autotune", "antares"),
    "Waves (C1, CLA-3A, RVox)": ("waveshell", "waves"),
    "FabFilter": ("fabfilter",),
    "Steinberg (tích hợp)": (),
}


def is_self_admin() -> bool:
    if not IS_WIN:
        return os.geteuid() == 0 if hasattr(os, "geteuid") else False
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:
        return False


def _processes() -> List[dict]:
    try:
        import psutil
    except ImportError:
        return []
    out = []
    for p in psutil.process_iter(["pid", "name", "exe"]):
        out.append(p.info)
    return out


def process_elevated(pid: int) -> Optional[bool]:
    """True = tiến trình chạy quyền Admin; None = không xác định được."""
    if not IS_WIN:
        return None
    k32, adv = ctypes.windll.kernel32, ctypes.windll.advapi32
    PROCESS_QUERY_LIMITED_INFORMATION, TOKEN_QUERY, TokenElevation = 0x1000, 0x0008, 20
    h = k32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
    if not h:
        return None
    try:
        tok = ctypes.c_void_p()
        if not adv.OpenProcessToken(h, TOKEN_QUERY, ctypes.byref(tok)):
            # tiến trình quyền thường không mở được token của tiến trình Admin
            return True if not is_self_admin() else None
        try:
            elev = ctypes.c_uint32()
            size = ctypes.c_uint32()
            ok = adv.GetTokenInformation(tok, TokenElevation, ctypes.byref(elev), 4, ctypes.byref(size))
            return bool(elev.value) if ok else None
        finally:
            k32.CloseHandle(tok)
    finally:
        k32.CloseHandle(h)


def window_titles() -> List[str]:
    if not IS_WIN:
        return []
    user32 = ctypes.windll.user32
    titles: List[str] = []
    proto = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)

    def cb(hwnd, _):
        if user32.IsWindowVisible(hwnd):
            n = user32.GetWindowTextLengthW(hwnd)
            if n:
                buf = ctypes.create_unicode_buffer(n + 1)
                user32.GetWindowTextW(hwnd, buf, n + 1)
                titles.append(buf.value)
        return True

    user32.EnumWindows(proto(cb), 0)
    return titles


def cubase_status() -> dict:
    procs = [p for p in _processes() if (p.get("name") or "").lower().startswith("cubase")]
    info: dict = {"running": bool(procs), "processes": []}
    for p in procs:
        info["processes"].append({"pid": p["pid"], "exe": p.get("exe"), "elevated": process_elevated(p["pid"]),
                                  "version": file_version(p.get("exe"))})
    titles = [t for t in window_titles() if "cubase" in t.lower()]
    info["windows"] = titles
    info["project_hint"] = project_from_titles(titles)
    return info


def project_from_titles(titles: List[str]) -> str:
    """'Cubase Pro Project - PROJECT-10' -> 'PROJECT-10'."""
    for t in titles:
        if " - " in t:
            name = t.split(" - ", 1)[1].strip().strip("*").strip()
            if name.lower().endswith(".cpr"):
                name = name[:-4]
            if name:
                return name
    return ""


def file_version(exe: Optional[str]) -> str:
    if not (IS_WIN and exe and Path(exe).exists()):
        return ""
    try:
        r = subprocess.run(["powershell", "-NoProfile", "-Command",
                            f"(Get-Item -LiteralPath '{exe}').VersionInfo.ProductVersion"],
                           capture_output=True, text=True, timeout=10,
                           creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        return r.stdout.strip()
    except Exception:
        return ""


def tiktok_status() -> dict:
    procs = [p for p in _processes() if "tiktok" in (p.get("name") or "").lower()]
    return {"running": bool(procs), "names": sorted({p["name"] for p in procs})}


def plugin_inventory() -> Dict[str, List[str]]:
    dirs = [Path(os.environ.get("CommonProgramFiles", r"C:\Program Files\Common Files")) / "VST3",
            Path(r"C:\Program Files\VSTPlugins"), Path(r"C:\Program Files\Steinberg\VSTPlugins")]
    found: Dict[str, List[str]] = {}
    for d in dirs:
        if not d.exists():
            continue
        for p in d.rglob("*"):
            if p.suffix.lower() in (".vst3", ".dll"):
                n = p.name.lower()
                for group, hints in PLUGIN_HINTS.items():
                    if any(h in n for h in hints):
                        found.setdefault(group, []).append(str(p))
    # Waves: danh sách plugin cụ thể nằm trong thư mục Waves
    waves = Path(r"C:\Program Files (x86)\Waves\Plug-Ins V15"), Path(r"C:\Program Files (x86)\Waves")
    for w in waves:
        if w.exists():
            names = sorted({p.stem for p in w.rglob("*.bundle")})
            if names:
                found["Waves bundles"] = names[:200]
            break
    return found


def midi_remote_script_dir() -> Path:
    return (Path.home() / "Documents" / "Steinberg" / "Cubase" / "MIDI Remote" / "Driver Scripts"
            / "Local" / "ailive" / "vocalbridge")


def install_midi_remote_script(src: Path) -> Path:
    dest_dir = midi_remote_script_dir()
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / "ailive_vocalbridge.js"
    dest.write_bytes(Path(src).read_bytes())
    return dest


def loopmidi_installed() -> bool:
    if not IS_WIN:
        return False
    for base in (os.environ.get("ProgramFiles(x86)", ""), os.environ.get("ProgramFiles", "")):
        if base and (Path(base) / "Tobias Erichsen" / "loopMIDI" / "loopMIDI.exe").exists():
            return True
    return False
