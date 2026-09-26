"""Phân tích GIỌNG HÁT (mic): cao độ (YIN), mức tín hiệu, nền ồn, độ biến thiên.

Dùng cho bước "hát thử" để đề xuất chỉnh EQ/nén/mức ra trong giới hạn an toàn.
Không nằm trong đường âm thanh thời gian thực — chỉ phân tích bản sao tín hiệu.
"""
from __future__ import annotations

from dataclasses import dataclass, asdict
from typing import List, Optional

import numpy as np

from .keydetect import NOTE_NAMES


def dbfs(x: np.ndarray) -> float:
    rms = float(np.sqrt(np.mean(np.square(x, dtype=np.float64)))) if len(x) else 0.0
    return 20.0 * np.log10(rms + 1e-12)


def peak_dbfs(x: np.ndarray) -> float:
    return 20.0 * np.log10(float(np.max(np.abs(x))) + 1e-12) if len(x) else -240.0


def yin_pitch(frame: np.ndarray, sr: int, fmin: float = 70.0, fmax: float = 800.0,
              threshold: float = 0.15) -> Optional[float]:
    """Ước lượng tần số cơ bản (Hz) theo YIN; None nếu không có cao độ rõ."""
    x = np.asarray(frame, dtype=np.float64)
    x = x - x.mean()
    tau_min, tau_max = int(sr / fmax), int(sr / fmin)
    n = len(x)
    if n < 2 * tau_max or np.max(np.abs(x)) < 1e-4:
        return None
    w = n - tau_max
    # hàm hiệu d(tau) tính bằng FFT
    x0 = x[:w]
    energy = np.concatenate(([0.0], np.cumsum(x ** 2)))
    size = 1 << int(np.ceil(np.log2(n + w)))
    corr = np.fft.irfft(np.fft.rfft(x, size) * np.conj(np.fft.rfft(x0, size)), size)[:tau_max + 1]
    e0 = energy[w]
    etau = energy[np.arange(tau_max + 1) + w] - energy[np.arange(tau_max + 1)]
    d = e0 + etau - 2 * corr
    d[0] = 0
    cmnd = np.ones_like(d)
    cumsum = np.cumsum(d[1:])
    cmnd[1:] = d[1:] * np.arange(1, tau_max + 1) / np.maximum(cumsum, 1e-12)
    tau = None
    for t in range(tau_min, tau_max):
        if cmnd[t] < threshold:
            while t + 1 < tau_max and cmnd[t + 1] < cmnd[t]:
                t += 1
            tau = t
            break
    if tau is None:
        return None
    # nội suy parabol
    if 0 < tau < tau_max:
        a, b, c = cmnd[tau - 1], cmnd[tau], cmnd[tau + 1]
        denom = a - 2 * b + c
        shift = 0.5 * (a - c) / denom if abs(denom) > 1e-12 else 0.0
        tau = tau + shift
    return sr / tau


def hz_to_note(hz: float) -> str:
    m = int(round(69 + 12 * np.log2(hz / 440.0)))
    return f"{NOTE_NAMES[m % 12]}{m // 12 - 1}"


def hz_to_midi(hz: float) -> float:
    return 69 + 12 * np.log2(hz / 440.0)


@dataclass
class VoiceReport:
    noise_floor_db: float
    sing_rms_db: float          # RMS trung bình khi hát
    peak_db: float
    dynamic_range_db: float     # chênh lệch P90-P10 mức khung khi hát
    low_note: Optional[str]
    high_note: Optional[str]
    median_note: Optional[str]
    voiced_ratio: float
    sibilance_ratio_db: float   # năng lượng 5-9 kHz so với 200-4k (cao -> cần de-esser)
    low_mud_ratio_db: float     # năng lượng 150-400 Hz so với 1-4 kHz (cao -> giọng bí/đục)
    clipped: bool
    warnings: List[str]

    def to_dict(self) -> dict:
        return asdict(self)


def _band_energy(x: np.ndarray, sr: int, lo: float, hi: float) -> float:
    spec = np.abs(np.fft.rfft(x * np.hanning(len(x)))) ** 2
    f = np.fft.rfftfreq(len(x), 1 / sr)
    return float(spec[(f >= lo) & (f < hi)].sum()) + 1e-12


def analyze_voice(silence: np.ndarray, singing: np.ndarray, sr: int) -> VoiceReport:
    """silence: vài giây im lặng (đo nền ồn); singing: đoạn hát thử 10-20 giây."""
    frame = int(0.046 * sr)
    hop = frame // 2
    noise = dbfs(silence) if len(silence) else -90.0
    levels, pitches = [], []
    sib, body, mud, pres = 0.0, 0.0, 0.0, 0.0
    for i in range(0, len(singing) - frame, hop):
        fr = singing[i:i + frame]
        lv = dbfs(fr)
        if lv < noise + 10:  # coi như không hát
            continue
        levels.append(lv)
        p = yin_pitch(fr, sr)
        if p:
            pitches.append(p)
        if len(fr) >= 1024:
            sib += _band_energy(fr, sr, 5000, 9000)
            body += _band_energy(fr, sr, 200, 4000)
            mud += _band_energy(fr, sr, 150, 400)
            pres += _band_energy(fr, sr, 1000, 4000)
    total_frames = max(1, (len(singing) - frame) // hop)
    warnings: List[str] = []
    pk = peak_dbfs(singing)
    if not levels:
        warnings.append("Không phát hiện tiếng hát trong bản thử — kiểm tra mic/đường vào.")
        return VoiceReport(noise, -90, pk, 0, None, None, None, 0.0, 0.0, 0.0, pk > -0.5, warnings)
    lv = np.array(levels)
    rng = float(np.percentile(lv, 90) - np.percentile(lv, 10))
    low = high = med = None
    if len(pitches) >= 5:
        mids = np.array([hz_to_midi(p) for p in pitches])
        lo_hz = 440 * 2 ** ((np.percentile(mids, 5) - 69) / 12)
        hi_hz = 440 * 2 ** ((np.percentile(mids, 95) - 69) / 12)
        md_hz = 440 * 2 ** ((np.median(mids) - 69) / 12)
        low, high, med = hz_to_note(lo_hz), hz_to_note(hi_hz), hz_to_note(md_hz)
    sing = float(np.mean(lv))
    if pk > -0.5:
        warnings.append("Tín hiệu bị clip (chạm 0 dBFS): giảm gain trên sound card 1 nấc.")
    if sing < -38:
        warnings.append("Mic rất nhỏ: tăng gain trên sound card (không bù bằng phần mềm quá +12 dB).")
    if noise > -55:
        warnings.append("Nền ồn cao: tắt quạt/điều hoà gần mic hoặc đặt mic gần miệng hơn.")
    if sing - noise < 25:
        warnings.append("Giọng chỉ lớn hơn nền ồn chưa tới 25 dB — nén mạnh sẽ làm to tiếng ồn.")
    return VoiceReport(
        noise_floor_db=round(noise, 1), sing_rms_db=round(sing, 1), peak_db=round(pk, 1),
        dynamic_range_db=round(rng, 1), low_note=low, high_note=high, median_note=med,
        voiced_ratio=round(len(levels) / total_frames, 2),
        sibilance_ratio_db=round(10 * np.log10(sib / body), 1) if body else 0.0,
        low_mud_ratio_db=round(10 * np.log10(mud / pres), 1) if pres else 0.0,
        clipped=pk > -0.5, warnings=warnings)
