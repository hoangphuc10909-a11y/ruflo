"""Lưu cấu hình, nhật ký thay đổi, sao lưu/khôi phục project Cubase.

Project .cpr chỉ được SAO CHÉP nguyên file (không đọc/sửa dữ liệu nhị phân).
"""
from __future__ import annotations

import json
import logging
import os
import shutil
import time
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Any, Dict, List, Optional

APP_NAME = "AILiveVocal"
LIVE_SUFFIX = "-TIKTOK-LIVE"


def app_dir() -> Path:
    base = os.environ.get("AILIVE_HOME") or os.environ.get("APPDATA") or str(Path.home() / ".config")
    p = Path(base) / APP_NAME
    p.mkdir(parents=True, exist_ok=True)
    return p


def setup_logging() -> Path:
    path = app_dir() / "ailive.log"
    h = RotatingFileHandler(path, maxBytes=2_000_000, backupCount=3, encoding="utf-8")
    h.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    root.addHandler(h)
    return path


DEFAULTS: Dict[str, Any] = {
    "project_path": "",
    "assignments": {},          # role -> target idx
    "calibrations": {},         # role -> Calibration dict
    "baseline": {},             # target idx -> {value, display, label}: trạng thái GỐC trước khi app chỉnh
    "last_good": {},            # target idx -> value: cấu hình đang hát tốt lần trước
    "style": "tu_nhien",
    "tune_strength": 45,
    "reverb_offset_db": 0.0,
    "duck_db": 4.0,
    "key_min_confidence": 0.55,
    "music_device": "",         # thiết bị loa phát nhạc (thu loopback)
    "mic_device": "",           # thiết bị mic (bản sao để phân tích)
    "mix_device": "",           # thiết bị nhận tín hiệu đã xử lý (vd "Mix 01")
    "vocal_track_hint": "",     # tên kênh giọng trong Cubase, để kiểm tra đang chọn đúng track
    "voice_report": None,
}


class Config:
    def __init__(self, path: Optional[Path] = None):
        self.path = path or (app_dir() / "config.json")
        self.data: Dict[str, Any] = dict(DEFAULTS)
        self.load()

    def load(self) -> None:
        if self.path.exists():
            try:
                self.data.update(json.loads(self.path.read_text(encoding="utf-8")))
            except (OSError, ValueError):
                bad = self.path.with_suffix(".corrupt.json")
                shutil.copy2(self.path, bad)
                logging.getLogger("ailive").warning("Config hỏng, đã lưu bản lỗi ở %s", bad)

    def save(self) -> None:
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(self.data, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(tmp, self.path)  # ghi nguyên tử: mất điện giữa chừng không hỏng file

    def __getitem__(self, k: str) -> Any:
        return self.data.get(k, DEFAULTS.get(k))

    def __setitem__(self, k: str, v: Any) -> None:
        self.data[k] = v


class ChangeLog:
    def __init__(self, path: Optional[Path] = None):
        self.path = path or (app_dir() / "changes.jsonl")

    def add(self, action: str, **info: Any) -> None:
        rec = {"t": time.strftime("%Y-%m-%d %H:%M:%S"), "action": action, **info}
        with self.path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")

    def tail(self, n: int = 50) -> List[dict]:
        if not self.path.exists():
            return []
        lines = self.path.read_text(encoding="utf-8").splitlines()[-n:]
        return [json.loads(x) for x in lines if x.strip()]


# ---------------- Project Cubase ----------------

def backup_dir() -> Path:
    p = app_dir() / "backups"
    p.mkdir(exist_ok=True)
    return p


def backup_project(cpr: Path) -> Path:
    """Chép nguyên file .cpr sang thư mục sao lưu có dấu thời gian. Trả về đường dẫn bản sao."""
    cpr = Path(cpr)
    if not cpr.is_file() or cpr.suffix.lower() != ".cpr":
        raise FileNotFoundError(f"Không thấy file project: {cpr}")
    stamp = time.strftime("%Y%m%d-%H%M%S")
    dest = backup_dir() / f"{cpr.stem}__{stamp}.cpr"
    n = 1
    while dest.exists():  # không bao giờ ghi đè một bản sao lưu đã có
        dest = backup_dir() / f"{cpr.stem}__{stamp}-{n}.cpr"
        n += 1
    shutil.copy2(cpr, dest)
    meta = dest.with_suffix(".json")
    meta.write_text(json.dumps({"source": str(cpr), "size": cpr.stat().st_size,
                                "mtime": cpr.stat().st_mtime}, ensure_ascii=False), encoding="utf-8")
    if dest.stat().st_size != cpr.stat().st_size:
        raise IOError("Bản sao lưu không khớp kích thước — không tiếp tục.")
    return dest


def create_live_copy(cpr: Path) -> Path:
    """Tạo project riêng để hát TikTok, CÙNG THƯ MỤC để đường dẫn Audio/ vẫn đúng.
    Không ghi đè nếu đã tồn tại."""
    cpr = Path(cpr)
    live = cpr.with_name(cpr.stem + LIVE_SUFFIX + ".cpr")
    if live.exists():
        return live
    backup_project(cpr)
    shutil.copy2(cpr, live)
    return live


def list_backups(stem: Optional[str] = None) -> List[Path]:
    # copy2 giữ mtime của file gốc, nên sắp theo thời điểm tạo bản sao (ctime)
    items = sorted(backup_dir().glob("*.cpr"), key=lambda p: p.stat().st_ctime, reverse=True)
    return [p for p in items if stem is None or p.name.startswith(stem + "__")]


def restore_project(backup: Path) -> Path:
    """Đưa bản sao lưu về vị trí gốc. Bản hiện tại được sao lưu thêm lần nữa trước khi ghi đè."""
    backup = Path(backup)
    meta = json.loads(backup.with_suffix(".json").read_text(encoding="utf-8"))
    target = Path(meta["source"])
    if target.exists():
        backup_project(target)
    shutil.copy2(backup, target)
    return target


def find_projects(name_hint: str = "", roots: Optional[List[Path]] = None, limit: int = 20) -> List[Path]:
    """Tìm file .cpr gần đây trong thư mục người dùng (Documents, Desktop, Music, ổ D:/E:)."""
    home = Path.home()
    roots = roots or [home / "Documents", home / "Desktop", home / "Music", home / "OneDrive",
                      Path("D:/"), Path("E:/")]
    found: List[Path] = []
    for r in roots:
        if not r.exists():
            continue
        try:
            for dirpath, dirnames, files in os.walk(r):
                # bỏ các thư mục lớn không liên quan
                dirnames[:] = [d for d in dirnames if not d.startswith((".", "$")) and d not in
                               ("Windows", "Program Files", "Program Files (x86)", "node_modules", "AppData")]
                if dirpath.count(os.sep) - str(r).count(os.sep) > 5:
                    dirnames[:] = []
                for f in files:
                    if f.lower().endswith(".cpr") and (not name_hint or name_hint.lower() in f.lower()):
                        found.append(Path(dirpath) / f)
        except OSError:
            continue
    found.sort(key=lambda p: p.stat().st_mtime if p.exists() else 0, reverse=True)
    return found[:limit]


# ---------------- Cấu hình ứng dụng (preset đã hiệu chuẩn) ----------------

def export_settings(cfg: "Config", dest: Path) -> Path:
    """Xuất toàn bộ cấu hình (gán vai trò, hiệu chuẩn, cấu hình hát tốt) ra file JSON."""
    dest = Path(dest)
    data = dict(cfg.data)
    data["_export"] = {"app": APP_NAME, "time": time.strftime("%Y-%m-%d %H:%M:%S")}
    dest.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    return dest


def import_settings(cfg: "Config", src: Path) -> int:
    """Nhập cấu hình từ file đã xuất. Tự sao lưu cấu hình hiện tại trước khi ghi đè."""
    data = json.loads(Path(src).read_text(encoding="utf-8"))
    if data.get("_export", {}).get("app") != APP_NAME:
        raise ValueError("File không phải cấu hình AI LIVE VOCAL.")
    snapshot_settings(cfg, "truoc-khi-nhap")
    data.pop("_export", None)
    keys = [k for k in data if k in DEFAULTS]
    for k in keys:
        cfg[k] = data[k]
    cfg.save()
    return len(keys)


def snapshot_settings(cfg: "Config", tag: str = "tu-dong") -> Path:
    stamp = time.strftime("%Y%m%d-%H%M%S")
    dest = backup_dir() / f"cau-hinh__{stamp}__{tag}.json"
    n = 1
    while dest.exists():
        dest = backup_dir() / f"cau-hinh__{stamp}__{tag}-{n}.json"
        n += 1
    return export_settings(cfg, dest)
