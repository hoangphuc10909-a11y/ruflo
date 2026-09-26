"""Giám sát khi LIVE: mất tín hiệu, bảo vệ đầu ra chống clip, và các bước cài đặt còn thiếu.

Nguyên tắc: tự động chỉ được GIẢM (fader khi clip), không bao giờ tự tăng âm lượng.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Callable, List, Optional


@dataclass
class OutputGuard:
    """Nếu tín hiệu gửi TikTok (Mix) chạm gần 0 dBFS liên tục, hạ fader giọng từng 1 dB,
    tối đa `max_cut_db` mỗi phiên, cách nhau ít nhất `interval` giây."""
    threshold_db: float = -1.0
    hits_needed: int = 3          # số khối 100 ms liên tiếp vượt ngưỡng
    step_db: float = 1.0
    max_cut_db: float = 6.0
    interval: float = 1.0
    cut_total: float = 0.0
    _hits: int = 0
    _last: float = 0.0

    def check(self, peak_db: float, now: Optional[float] = None) -> float:
        """Trả về số dB cần hạ (0 nếu không cần)."""
        now = time.time() if now is None else now
        self._hits = self._hits + 1 if peak_db > self.threshold_db else 0
        if self._hits < self.hits_needed or now - self._last < self.interval:
            return 0.0
        if self.cut_total >= self.max_cut_db:
            return 0.0
        self._last, self._hits = now, 0
        step = min(self.step_db, self.max_cut_db - self.cut_total)
        self.cut_total += step
        return step


@dataclass
class SignalMonitor:
    """Phát hiện mất tín hiệu dựa trên thời gian im lặng của từng nguồn."""
    mic_timeout: float = 45.0
    mix_timeout: float = 5.0
    music_timeout: float = 30.0
    alerts: List[str] = field(default_factory=list)

    def evaluate(self, singing_mode: bool, mic_silent: float, music_silent: float,
                 mix_silent: Optional[float], mic_active: bool, cubase_ok: bool) -> List[str]:
        a: List[str] = []
        if not cubase_ok:
            a.append("Mất kết nối Cubase (giọng vẫn chạy, chỉ là app không chỉnh được). Kiểm tra Cubase còn mở.")
        if singing_mode and music_silent < 3 and mic_silent > self.mic_timeout:
            a.append("Nhạc đang chạy nhưng MIC im lặng lâu — kiểm tra mic, dây, nút Mute trên sound card.")
        if mix_silent is not None and mic_active and mix_silent > self.mix_timeout:
            a.append("Đang có tiếng mic nhưng đường gửi TikTok (Mix) KHÔNG có tín hiệu — kiểm tra Output của Cubase.")
        self.alerts = a
        return a


def setup_steps(ports_ok: bool, script_installed: bool, connected: bool, assignments: dict,
                calibrations: dict, devices: dict, voice_done: bool) -> List[str]:
    """Danh sách việc còn thiếu, theo đúng thứ tự làm. Rỗng = đã sẵn sàng."""
    steps: List[str] = []
    if not ports_ok:
        steps.append("Mở loopMIDI, tạo 2 cổng 'AILive To Cubase' và 'AILive From Cubase'.")
    if not script_installed:
        steps.append("Nâng cao → 1 → 'Cài script cầu nối vào Cubase', rồi trong Cubase bấm Reload Scripts ở khung MIDI Remote.")
    if ports_ok and script_installed and not connected:
        steps.append("Cubase chưa trả lời: mở Cubase, kiểm tra khung MIDI Remote có 'AI LIVE VOCAL'.")
    if connected and "tune_key" not in assignments and "tune_speed" not in assignments:
        steps.append("Chọn kênh giọng trong Cubase, gán Quick Controls cho Auto-Tune, rồi Nâng cao → 2 → 'Tự nhận diện vai trò'.")
    missing_cal = [r for r in assignments if r not in calibrations]
    if connected and assignments and missing_cal:
        steps.append(f"Nâng cao → 2 → 'Hiệu chuẩn tất cả' (còn {len(missing_cal)} tham số chưa hiệu chuẩn).")
    for key, text in (("music_device", "loa phát nhạc"), ("mic_device", "mic"), ("mix_device", "thiết bị Mix gửi TikTok")):
        if not devices.get(key):
            steps.append(f"Nâng cao → 3 → chọn {text}.")
    if not voice_done:
        steps.append("Nâng cao → 4 → HÁT THỬ 18 giây để cân giọng.")
    return steps


def auto_restore_allowed(last_good: dict, calibrations: dict, live_labels: Callable[[int], str],
                         assignments: dict) -> bool:
    """Chỉ tự khôi phục cấu hình lần trước khi TẤT CẢ tham số đang trỏ đúng plugin như lúc hiệu chuẩn."""
    if not last_good:
        return False
    for role, idx in assignments.items():
        cal = calibrations.get(role)
        if str(idx) in last_good and cal and live_labels(int(idx)) != cal.get("label"):
            return False
    return True
