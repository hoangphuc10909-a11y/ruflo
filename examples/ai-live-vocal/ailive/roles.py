"""Vai trò tham số (Auto-Tune key, retune speed, send vang...) + hiệu chuẩn thực tế.

Không đoán thang giá trị của plugin: ứng dụng quét giá trị qua MIDI Remote và ĐỌC
chuỗi hiển thị Cubase trả về ("25", "C#", "-12.0 dB"...) để lập bảng tra.
"""
from __future__ import annotations

import re
import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

from .keydetect import NOTE_NAMES


@dataclass(frozen=True)
class Role:
    key: str
    label: str                 # tiếng Việt, hiện cho người dùng
    kind: str                  # "number" | "enum" | "db"
    keywords: Tuple[str, ...]  # để tự nhận diện từ tên Cubase báo về
    targets: Tuple[int, ...]   # chỉ số đích cho phép (0-7 QC, 8 fader, 9-12 send)
    safe_max: Optional[float] = None   # giới hạn cứng (dB cho fader/send)
    safe_min: Optional[float] = None


QC = tuple(range(8))
SENDS = (9, 10, 11, 12)
ROLES: Dict[str, Role] = {r.key: r for r in [
    Role("tune_key", "Auto-Tune · Key (tone)", "enum", ("key",), QC),
    Role("tune_scale", "Auto-Tune · Scale", "enum", ("scale",), QC),
    Role("tune_speed", "Auto-Tune · Retune Speed", "number", ("retune",), QC),
    Role("tune_humanize", "Auto-Tune · Humanize", "number", ("humanize",), QC),
    Role("delay_time", "Delay · Time (ms, khớp nhịp)", "number", ("delay time", "time"), QC, 1500.0, 20.0),
    Role("eq_lowmid", "EQ · cắt vùng đục 200-400 Hz (gain)", "number", ("low mid", "lmf", "band 2 gain", "gain 2"), QC, 3.0, -8.0),
    Role("eq_presence", "EQ · độ sáng/rõ lời 3-5 kHz (gain)", "number", ("presence", "hmf", "band 3 gain", "gain 3"), QC, 6.0, -3.0),
    Role("deess", "De-esser · Threshold", "number", ("de-ess", "deess", "sibil"), QC),
    Role("comp", "Compressor · Threshold", "number", ("threshold", "thresh"), QC),
    Role("vocal_fader", "Fader kênh giọng", "db", ("",), (8,), 3.0, -40.0),
    Role("reverb_send", "Send vang (Reverb)", "db", ("verb", "vang", "hall", "plate", "room"), SENDS, -4.0, -60.0),
    Role("delay_send", "Send delay/echo", "db", ("delay", "echo"), SENDS, -6.0, -60.0),
]}

_NUM = re.compile(r"[-+]?\d+(?:[.,]\d+)?")


def parse_number(display: str) -> Optional[float]:
    d = display.strip().lower()
    if not d:
        return None
    if d.startswith("-oo") or "-inf" in d or "-∞" in d or d in ("off", "-"):
        return -120.0
    m = _NUM.search(d)
    return float(m.group(0).replace(",", ".")) if m else None


_ENHARMONIC = {"C#": "Db", "D#": "Eb", "F#": "Gb", "G#": "Ab", "A#": "Bb",
               "Db": "Db", "Eb": "Eb", "Gb": "Gb", "Ab": "Ab", "Bb": "Bb"}


def norm_note(text: str) -> Optional[str]:
    """'C#', 'Db', 'c♯', 'C# Major' -> tên chuẩn (dạng giáng cho nốt đen)."""
    t = text.strip().replace("♯", "#").replace("♭", "b")
    m = re.match(r"^([A-Ga-g])([#b]?)", t)
    if not m:
        return None
    n = m.group(1).upper() + m.group(2)
    return _ENHARMONIC.get(n, n)


def tonic_to_norm(tonic: int) -> str:
    return norm_note(NOTE_NAMES[tonic % 12]) or NOTE_NAMES[tonic % 12]


@dataclass
class Calibration:
    """Bảng tra giá trị 0..1 <-> chuỗi hiển thị cho một vai trò, gắn với tên tham số."""
    role: str
    target: int
    label: str                               # "Auto-Tune Artist · Retune Speed" lúc hiệu chuẩn
    points: List[Tuple[float, str]] = field(default_factory=list)
    created: float = field(default_factory=time.time)

    # ----- số -----
    def numeric(self) -> List[Tuple[float, float]]:
        out = []
        for v, d in self.points:
            n = parse_number(d)
            if n is not None:
                out.append((v, n))
        return out

    def value_for_number(self, target: float) -> Optional[float]:
        pts = self.numeric()
        if len(pts) < 2:
            return None
        pts.sort()
        lo_n, hi_n = min(p[1] for p in pts), max(p[1] for p in pts)
        target = max(lo_n, min(hi_n, target))
        best = None
        for (v0, n0), (v1, n1) in zip(pts, pts[1:]):
            if min(n0, n1) <= target <= max(n0, n1):
                v = v0 if n1 == n0 else v0 + (v1 - v0) * (target - n0) / (n1 - n0)
                best = v if best is None else best
                break
        if best is None:
            best = min(pts, key=lambda p: abs(p[1] - target))[0]
        return best

    def number_for_value(self, v: float) -> Optional[float]:
        pts = sorted(self.numeric())
        if not pts:
            return None
        return min(pts, key=lambda p: abs(p[0] - v))[1]

    def range(self) -> Optional[Tuple[float, float]]:
        nums = [n for _, n in self.numeric() if n > -120]
        return (min(nums), max(nums)) if nums else None

    # ----- liệt kê -----
    def options(self) -> Dict[str, float]:
        """Mỗi chuỗi hiển thị -> giá trị ở GIỮA vùng của nó (tránh rơi vào ranh giới)."""
        groups: Dict[str, List[float]] = {}
        for v, d in self.points:
            groups.setdefault(d.strip(), []).append(v)
        return {d: (min(vs) + max(vs)) / 2 for d, vs in groups.items() if d}

    def value_for_option(self, wanted: str) -> Optional[float]:
        opts = self.options()
        w = wanted.strip().lower()
        for d, v in opts.items():
            if d.lower() == w:
                return v
        nw = norm_note(wanted)
        if nw and len(wanted.strip()) <= 3:
            for d, v in opts.items():
                if len(d) <= 3 and norm_note(d) == nw:
                    return v
        for d, v in opts.items():
            if w and w in d.lower():
                return v
        return None

    def to_dict(self) -> dict:
        return {"role": self.role, "target": self.target, "label": self.label,
                "points": self.points, "created": self.created}

    @classmethod
    def from_dict(cls, d: dict) -> "Calibration":
        return cls(d["role"], d["target"], d["label"], [tuple(p) for p in d["points"]], d.get("created", 0))


def guess_assignments(labels: Dict[int, str]) -> Dict[str, int]:
    """Đề xuất vai trò dựa trên tên Cubase báo về (người dùng xác nhận trong mục Nâng cao)."""
    out: Dict[str, int] = {}
    used = set()
    for role in ROLES.values():
        if role.key == "vocal_fader":
            out[role.key] = 8
            continue
        for idx in role.targets:
            lab = labels.get(idx, "").lower()
            if idx in used or not lab:
                continue
            if any(k and k in lab for k in role.keywords):
                out[role.key] = idx
                used.add(idx)
                break
    return out


def calibrate(link, role: Role, target: int, steps: int = 128, settle: float = 0.25) -> Calibration:
    """Quét tham số và đọc lại hiển thị. Với fader/send: quét TĂNG DẦN và dừng ngay khi
    vượt safe_max để không bao giờ làm tiếng to đột ngột. Khôi phục giá trị ban đầu."""
    state = link.targets[target]
    original = state.value
    cal = Calibration(role.key, target, state.label)
    try:
        for k in range(steps):
            v = k / (steps - 1)
            disp = link.set_and_read(target, v, timeout=settle)
            if disp is None:
                continue
            cal.points.append((v, disp))
            if role.kind == "db" and role.safe_max is not None:
                n = parse_number(disp)
                if n is not None and n > role.safe_max:
                    break
    finally:
        if original is not None:
            link.send_raw(target, original)
    return cal
