"""Bước 1 — Kiểm tra máy. Chạy: python -m ailive.diagnose  (hoặc nút KIỂM TRA MÁY)

Tạo báo cáo tiếng Việt + JSON trong thư mục ứng dụng để gửi lại cho kỹ thuật.
"""
from __future__ import annotations

import json
import platform
import sys
import time
from pathlib import Path
from typing import List, Tuple

from . import winsys
from .midi_link import PORT_FROM_CUBASE, PORT_TO_CUBASE
from .store import app_dir

Check = Tuple[str, str, str]  # (mức: OK/CANH_BAO/LOI, mục, chi tiết + việc cần làm)


def run() -> Tuple[List[Check], dict]:
    checks: List[Check] = []
    raw: dict = {"time": time.strftime("%Y-%m-%d %H:%M:%S"), "os": platform.platform(),
                 "python": sys.version.split()[0], "app_admin": winsys.is_self_admin()}

    cub = winsys.cubase_status()
    raw["cubase"] = cub
    if not cub["running"]:
        checks.append(("LOI", "Cubase", "Chưa mở Cubase. Mở Cubase Pro 15 và project cần hát."))
    else:
        for p in cub["processes"]:
            ver = p.get("version") or "?"
            elev = p.get("elevated")
            checks.append(("OK", "Cubase", f"Đang chạy, phiên bản {ver}"))
            if elev:
                checks.append(("CANH_BAO", "Quyền chạy Cubase",
                               "Cubase đang chạy quyền Administrator. Ứng dụng điều khiển qua MIDI nên VẪN hoạt động; "
                               "không cần mở ứng dụng bằng quyền Admin. (Nếu không có lý do riêng, nên bỏ "
                               "'Run as administrator' trong Properties > Compatibility của Cubase.)"))
        if cub["project_hint"]:
            checks.append(("OK", "Project đang mở", cub["project_hint"]))
        else:
            checks.append(("CANH_BAO", "Project đang mở", "Không đọc được tên project từ tiêu đề cửa sổ."))

    tt = winsys.tiktok_status()
    raw["tiktok"] = tt
    checks.append(("OK" if tt["running"] else "CANH_BAO", "TikTok LIVE Studio",
                   "Đang chạy" if tt["running"] else "Chưa mở (chỉ cần khi kiểm tra đường vào TikTok)."))

    # MIDI
    try:
        import mido
        ins, outs = mido.get_input_names(), mido.get_output_names()
        raw["midi"] = {"in": ins, "out": outs}
        ok_out = any(n.startswith(PORT_TO_CUBASE) for n in outs)
        ok_in = any(n.startswith(PORT_FROM_CUBASE) for n in ins)
        if ok_out and ok_in:
            checks.append(("OK", "Cổng MIDI ảo", "Đã có 2 cổng AILive."))
        else:
            checks.append(("LOI", "Cổng MIDI ảo",
                           f"Thiếu cổng. Mở loopMIDI, tạo 2 cổng tên chính xác: '{PORT_TO_CUBASE}' và "
                           f"'{PORT_FROM_CUBASE}'. (loopMIDI miễn phí: tobias-erichsen.de)"
                           + ("" if winsys.loopmidi_installed() else " — máy CHƯA cài loopMIDI.")))
    except Exception as e:
        checks.append(("LOI", "MIDI", f"Không đọc được MIDI: {e}"))

    script = winsys.midi_remote_script_dir() / "ailive_vocalbridge.js"
    raw["midi_remote_script"] = str(script)
    checks.append(("OK" if script.exists() else "CANH_BAO", "Script MIDI Remote",
                   "Đã cài." if script.exists() else "Chưa cài — bấm 'Cài script vào Cubase' trong mục Nâng cao."))

    # Âm thanh
    try:
        from . import audio
        devs = audio.list_devices()
        raw["audio"] = devs
        checks.append(("OK", "Thiết bị phát (loa)", "; ".join(devs["speakers"]) or "không có"))
        checks.append(("OK", "Thiết bị thu (mic)", "; ".join(devs["mics"]) or "không có"))
        icon = [n for n in devs["mics"] + devs["speakers"] if any(h in n.lower() for h in ("icon", "cube", "vad", "mix"))]
        checks.append(("OK" if icon else "CANH_BAO", "Sound card iCON",
                       "; ".join(icon) if icon else "Không thấy thiết bị iCON/Mix — kiểm tra cáp USB và driver."))
    except Exception as e:
        checks.append(("LOI", "Âm thanh", f"Không liệt kê được thiết bị: {e}"))

    plugins = winsys.plugin_inventory()
    raw["plugins"] = plugins
    for want, group in (("Auto-Tune", "Auto-Tune"), ("Waves", "Waves (C1, CLA-3A, RVox)")):
        checks.append(("OK" if plugins.get(group) else "CANH_BAO", f"Plugin {want}",
                       f"{len(plugins.get(group, []))} file" if plugins.get(group) else "Không thấy trong thư mục VST3."))
    wb = plugins.get("Waves bundles", [])
    for name in ("C1", "CLA-3A", "RVox"):
        hit = [b for b in wb if name.lower() in b.lower()]
        if wb:
            checks.append(("OK" if hit else "CANH_BAO", f"Waves {name}", ", ".join(hit) if hit else "không thấy bundle"))

    checks.append(("CANH_BAO", "Sample rate / Buffer ASIO",
                   "Không đọc được từ bên ngoài Cubase. Xem Studio > Studio Setup > Audio System và ghi lại "
                   "(khuyến nghị 48 kHz, buffer 128–256 nếu không có tiếng rè)."))
    return checks, raw


def write_report(checks: List[Check], raw: dict) -> Path:
    out = app_dir() / "bao-cao-kiem-tra.txt"
    icon = {"OK": "[OK]  ", "CANH_BAO": "[CHÚ Ý]", "LOI": "[LỖI] "}
    lines = [f"BÁO CÁO KIỂM TRA MÁY — AI LIVE VOCAL — {raw['time']}", ""]
    lines += [f"{icon[s]} {k}: {v}" for s, k, v in checks]
    out.write_text("\n".join(lines), encoding="utf-8")
    (app_dir() / "bao-cao-kiem-tra.json").write_text(json.dumps(raw, ensure_ascii=False, indent=2, default=str),
                                                     encoding="utf-8")
    return out


if __name__ == "__main__":
    c, r = run()
    p = write_report(c, r)
    print(p.read_text(encoding="utf-8"))
    print(f"\nĐã lưu: {p}")
