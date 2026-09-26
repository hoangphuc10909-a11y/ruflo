"""Bộ điều khiển: nối phân tích (tone, giọng) với tham số Cubase theo giới hạn an toàn."""
from __future__ import annotations

import logging
import threading
from typing import Dict, List, Optional

import numpy as np

from .health import OutputGuard
from .keydetect import KeyResult, KeyTracker, chroma_from_audio
from .midi_link import CubaseLink
from .roles import ROLES, Calibration, parse_number, tonic_to_norm
from .store import ChangeLog, Config
from .voice import VoiceReport

log = logging.getLogger("ailive.ctl")

# Phong cách: mức chỉnh cao độ mặc định + mức send (dB). Người dùng chỉnh thêm bằng 2 thanh trượt.
STYLES: Dict[str, dict] = {
    "tu_nhien": {"label": "GIỌNG TỰ NHIÊN", "strength": 45, "reverb_db": -20.0, "delay_db": -30.0},
    "bay": {"label": "GIỌNG BAY", "strength": 65, "reverb_db": -14.0, "delay_db": -22.0},
    "ro": {"label": "HIỆU ỨNG RÕ", "strength": 100, "reverb_db": -16.0, "delay_db": -24.0},
}
TALK = {"strength": 0, "reverb_db": -40.0, "delay_db": -60.0}


def strength_to_tune(strength: float) -> Dict[str, float]:
    """0 = gần như không kéo nốt, 100 = kéo tức thì (hiệu ứng robot).
    Auto-Tune: Retune Speed nhỏ = nhanh/mạnh; Humanize lớn = tự nhiên ở nốt ngân."""
    s = max(0.0, min(100.0, strength)) / 100.0
    return {"tune_speed": round(80.0 * (1 - s) ** 1.5, 1), "tune_humanize": round(60.0 * (1 - s), 1)}


class Controller:
    def __init__(self, cfg: Config, link: CubaseLink, changes: ChangeLog):
        self.cfg, self.link, self.changes = cfg, link, changes
        self.tracker = KeyTracker(min_confidence=cfg["key_min_confidence"])
        self.mode = "sing"               # "sing" | "talk"
        self.current_key: Optional[str] = None
        self.key_note: str = ""          # thông báo cho giao diện
        self.singing = False
        self._duck_applied = False
        self._lock = threading.RLock()
        self.guard = OutputGuard()

    # ---------- vai trò ----------
    def target_of(self, role: str) -> Optional[int]:
        t = self.cfg["assignments"].get(role)
        return int(t) if t is not None else None

    def calibration(self, role: str) -> Optional[Calibration]:
        d = self.cfg["calibrations"].get(role)
        return Calibration.from_dict(d) if d else None

    def role_ready(self, role: str) -> str:
        """'' nếu dùng được, ngược lại là lý do (tiếng Việt)."""
        t = self.target_of(role)
        if t is None:
            return "chưa gán"
        cal = self.calibration(role)
        if cal is None:
            return "chưa hiệu chuẩn"
        live = self.link.targets[t].label
        if live and cal.label and live != cal.label:
            return f"tham số đã đổi ('{live}' ≠ '{cal.label}') — hãy chọn đúng kênh giọng hoặc hiệu chuẩn lại"
        return ""

    def _set_number(self, role: str, number: float, ramp: float = 0.4) -> bool:
        if self.role_ready(role):
            return False
        r = ROLES[role]
        if r.safe_max is not None:
            number = min(number, r.safe_max)
        if r.safe_min is not None:
            number = max(number, r.safe_min)
        v = self.calibration(role).value_for_number(number)
        if v is None:
            return False
        self.link.set_value(self.target_of(role), v, ramp_s=ramp)
        return True

    def _set_option(self, role: str, option: str) -> bool:
        if self.role_ready(role):
            return False
        v = self.calibration(role).value_for_option(option)
        if v is None:
            return False
        self.link.set_value(self.target_of(role), v, ramp_s=0)
        return True

    # ---------- bản gốc & khôi phục ----------
    def capture_baseline(self, force: bool = False) -> int:
        """Lưu trạng thái hiện tại của mọi tham số được gán TRƯỚC khi ứng dụng chỉnh lần đầu."""
        base = self.cfg["baseline"]
        n = 0
        for role, t in self.cfg["assignments"].items():
            st = self.link.targets[int(t)]
            if st.value is None:
                continue
            if force or str(t) not in base:
                base[str(t)] = {"value": st.value, "display": st.display, "label": st.label}
                n += 1
        self.cfg["baseline"] = base
        self.cfg.save()
        if n:
            self.changes.add("baseline", count=n)
        return n

    def restore_baseline(self) -> List[str]:
        done = []
        for t, rec in self.cfg["baseline"].items():
            st = self.link.targets[int(t)]
            if st.label and rec.get("label") and st.label != rec["label"]:
                continue  # đang chọn kênh khác: không ghi nhầm
            self.link.set_value(int(t), rec["value"], ramp_s=0.6)
            done.append(f"{rec.get('label') or t}: {rec.get('display')}")
        self.changes.add("restore_baseline", items=done)
        return done

    def save_last_good(self) -> None:
        snap = {str(t): self.link.targets[int(t)].value for t in self.cfg["assignments"].values()
                if self.link.targets[int(t)].value is not None}
        self.cfg["last_good"] = snap
        self.cfg.save()
        self.changes.add("save_last_good", count=len(snap))

    def restore_last_good(self) -> int:
        n = 0
        for t, v in self.cfg["last_good"].items():
            if v is not None:
                self.link.set_value(int(t), float(v), ramp_s=0.6)
                n += 1
        self.changes.add("restore_last_good", count=n)
        return n

    # ---------- phong cách ----------
    def apply_style(self, style: Optional[str] = None) -> List[str]:
        with self._lock:
            if style:
                self.cfg["style"] = style
                self.cfg["tune_strength"] = STYLES[style]["strength"]
            self.mode = "sing"
            self.capture_baseline()
            applied = self._apply(self.cfg["tune_strength"], STYLES[self.cfg["style"]])
            self.cfg.save()
            self.changes.add("apply_style", style=self.cfg["style"], strength=self.cfg["tune_strength"],
                             reverb_offset=self.cfg["reverb_offset_db"], applied=applied)
            return applied

    def talk_mode(self) -> List[str]:
        with self._lock:
            self.mode = "talk"
            self.capture_baseline()
            applied = self._apply(TALK["strength"], TALK, offset=0.0)
            if not self.role_ready("tune_scale"):
                self._set_option("tune_scale", "Chromatic")
            self.changes.add("talk_mode", applied=applied)
            return applied

    def _apply(self, strength: float, style: dict, offset: Optional[float] = None) -> List[str]:
        offset = self.cfg["reverb_offset_db"] if offset is None else offset
        applied = []
        for role, val in strength_to_tune(strength).items():
            if self._set_number(role, val):
                applied.append(f"{ROLES[role].label} = {val}")
        for role, base in (("reverb_send", style["reverb_db"]), ("delay_send", style["delay_db"])):
            val = base + offset if base > -60 else base
            if self._set_number(role, val, ramp=0.8):
                applied.append(f"{ROLES[role].label} = {val:.1f} dB")
        return applied

    # ---------- tone ----------
    def feed_music(self, block: np.ndarray, sr: int) -> Optional[KeyResult]:
        new = self.tracker.update(chroma_from_audio(block, sr))
        est = self.tracker.last_estimate
        if self.tracker.modulation_suspected:
            self.key_note = f"Nhạc có vẻ đã chuyển sang {est.name if est else '?'} — đang KHOÁ tone {self.current_key}."
        if new is not None and self.mode == "sing":
            self.apply_key(new)
        return new

    def apply_key(self, key: KeyResult) -> bool:
        ok_k = self._set_option("tune_key", tonic_to_norm(key.tonic))
        ok_s = self._set_option("tune_scale", "Major" if key.mode == "major" else "Minor")
        self.current_key = key.name
        self.key_note = (f"Đã đặt Auto-Tune: {key.name} (tin cậy {key.confidence:.0%})" if ok_k and ok_s
                         else f"Nhạc: {key.name} (tin cậy {key.confidence:.0%}) — chưa điều khiển được Key/Scale")
        self.changes.add("apply_key", key=key.name, confidence=round(key.confidence, 2), ok=ok_k and ok_s)
        return ok_k and ok_s

    def fallback_chromatic(self) -> bool:
        """Khi chưa chắc tone: Chromatic kéo về bán cung gần nhất — an toàn, không kéo sai tone."""
        ok = self._set_option("tune_scale", "Chromatic")
        self.key_note = "Chưa chắc tone → dùng Chromatic (an toàn)." if ok else self.key_note
        self.changes.add("fallback_chromatic", ok=ok)
        return ok

    def sync_delay(self, bpm: float, confidence: float, min_conf: float = 0.5) -> Optional[float]:
        """Đặt thời gian delay = 1 phách (hoặc 1/2 phách nếu quá dài) khi nhận diện nhịp đủ tin cậy.
        Không đổi nếu lệch < 5% để tránh chỉnh liên tục."""
        if bpm <= 0 or confidence < min_conf or self.role_ready("delay_time"):
            return None
        ms = 60000.0 / bpm
        if ms > 600:
            ms /= 2
        t = self.target_of("delay_time")
        cur = parse_number(self.link.targets[t].display)
        if cur is not None and cur > 0 and abs(cur - ms) / cur < 0.05:
            return None
        if self._set_number("delay_time", ms, ramp=0.0):
            self.changes.add("sync_delay", bpm=bpm, ms=round(ms, 1))
            return ms
        return None

    def protect_output(self, mix_peak_db: float) -> float:
        """Chống clip đầu ra: chỉ HẠ fader giọng từng bước nhỏ, có giới hạn tổng."""
        cut = self.guard.check(mix_peak_db)
        if not cut or self.role_ready("vocal_fader"):
            return 0.0
        t = self.target_of("vocal_fader")
        cur = parse_number(self.link.targets[t].display)
        if cur is None or cur <= -120:
            return 0.0
        # bước 1 dB đặt ngay (như limiter), để lần kiểm tra sau đọc đúng mức mới
        if self._set_number("vocal_fader", cur - cut, ramp=0.0):
            self.changes.add("protect_output", peak=round(mix_peak_db, 1), cut_db=cut, total=self.guard.cut_total)
            return cut
        return 0.0

    def set_lock(self, locked: bool) -> None:
        self.tracker.locked = locked
        self.changes.add("key_lock", locked=locked)

    # ---------- vang thông minh ----------
    def update_singing(self, mic_rms_db: float, noise_db: float) -> None:
        """Giảm send vang khi đang hát, mở lại ở khoảng nghỉ. Chuyển chậm để không nghe giật."""
        if self.mode != "sing" or self.role_ready("reverb_send"):
            return
        singing = mic_rms_db > noise_db + 15
        if singing == self._duck_applied:
            return
        self._duck_applied = singing
        style = STYLES[self.cfg["style"]]
        val = style["reverb_db"] + self.cfg["reverb_offset_db"] - (self.cfg["duck_db"] if singing else 0.0)
        self._set_number("reverb_send", val, ramp=0.25 if singing else 0.9)

    # ---------- tự cân giọng ----------
    def voice_suggestions(self, rep: VoiceReport) -> List[dict]:
        """Đề xuất thay đổi TƯƠNG ĐỐI so với hiện tại, trong giới hạn. Người dùng bấm Áp dụng."""
        sug: List[dict] = []

        def cur(role):
            t = self.target_of(role)
            cal = self.calibration(role)
            if t is None or cal is None or self.link.targets[t].value is None:
                return None
            n = parse_number(self.link.targets[t].display)
            return n if n is not None else cal.number_for_value(self.link.targets[t].value)

        if rep.low_mud_ratio_db > 3 and cur("eq_lowmid") is not None:
            sug.append({"role": "eq_lowmid", "delta": -2.0, "why": "Giọng hơi đục/bí vùng 200-400 Hz"})
        if rep.low_mud_ratio_db > -2 and cur("eq_presence") is not None:
            sug.append({"role": "eq_presence", "delta": +1.5, "why": "Tăng nhẹ độ rõ lời 3-5 kHz"})
        if rep.sibilance_ratio_db > -8 and cur("deess") is not None:
            sug.append({"role": "deess", "delta": -3.0, "why": "Âm 's/x' khá gắt"})
        if rep.dynamic_range_db > 16 and cur("comp") is not None:
            sug.append({"role": "comp", "delta": -3.0, "why": "Âm lượng lúc to lúc nhỏ nhiều"})
        if rep.dynamic_range_db < 6 and cur("comp") is not None:
            sug.append({"role": "comp", "delta": +3.0, "why": "Có dấu hiệu nén quá tay (giọng phẳng, dễ bí)"})
        if rep.sing_rms_db < -30 and cur("vocal_fader") is not None:
            sug.append({"role": "vocal_fader", "delta": min(6.0, -24 - rep.sing_rms_db),
                        "why": "Giọng nhỏ — tăng fader có giới hạn; nên tăng gain mic trên sound card trước"})
        for s in sug:
            base = cur(s["role"])
            r = ROLES[s["role"]]
            new = base + s["delta"]
            if r.safe_max is not None:
                new = min(new, r.safe_max)
            if r.safe_min is not None:
                new = max(new, r.safe_min)
            rng = self.calibration(s["role"]).range()
            if rng:
                new = max(rng[0], min(rng[1], new))
            s.update({"from": base, "to": round(new, 1), "label": r.label})
        return sug

    def apply_suggestions(self, sug: List[dict]) -> List[str]:
        self.capture_baseline()
        done = []
        for s in sug:
            if self._set_number(s["role"], s["to"], ramp=1.0):
                done.append(f"{s['label']}: {s['from']} → {s['to']}")
        self.changes.add("apply_voice_suggestions", items=done)
        return done
