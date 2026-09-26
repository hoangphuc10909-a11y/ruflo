"""Ước lượng tone (key/scale) của NHẠC NỀN.

Chỉ nhận tín hiệu nhạc (không phải giọng hát) để tránh suy tone từ một nốt giọng.
Thuật toán: chroma (năng lượng 12 cung) tích lũy nhiều giây -> tương quan với
profile Krumhansl-Kessler cho 24 tone (12 trưởng + 12 thứ).
Độ tin cậy = khoảng cách giữa tone tốt nhất và tone tốt nhì (không tính tone
song song/tương đối vì chúng chung bộ nốt với Auto-Tune ở chế độ Chromatic-scale).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional

import numpy as np

NOTE_NAMES = ["C", "C#", "D", "Eb", "E", "F", "F#", "G", "Ab", "A", "Bb", "B"]

# Krumhansl-Kessler key profiles
_MAJOR = np.array([6.35, 2.23, 3.48, 2.33, 4.38, 4.09, 2.52, 5.19, 2.39, 3.66, 2.29, 2.88])
_MINOR = np.array([6.33, 2.68, 3.52, 5.38, 2.60, 3.53, 2.54, 4.75, 3.98, 2.69, 3.34, 3.17])


@dataclass(frozen=True)
class KeyResult:
    tonic: int            # 0..11 (C=0)
    mode: str             # "major" | "minor"
    confidence: float     # 0..1 (đã chuẩn hoá)
    score: float          # hệ số tương quan của tone tốt nhất
    runner_up: str        # tên tone tốt nhì (để hiển thị)

    @property
    def name(self) -> str:
        return key_name(self.tonic, self.mode)

    @property
    def relative(self) -> "tuple[int, str]":
        """Tone song song cùng bộ nốt (C major <-> A minor)."""
        if self.mode == "major":
            return ((self.tonic + 9) % 12, "minor")
        return ((self.tonic + 3) % 12, "major")


def key_name(tonic: int, mode: str) -> str:
    return f"{NOTE_NAMES[tonic % 12]} {'Major' if mode == 'major' else 'Minor'}"


def chroma_from_audio(x: np.ndarray, sr: int, n_fft: int = 8192, hop: int = 4096,
                      fmin: float = 55.0, fmax: float = 2000.0) -> np.ndarray:
    """Trả về chroma 12 chiều (tổng năng lượng theo cung) của đoạn âm thanh mono."""
    x = np.asarray(x, dtype=np.float64)
    if x.ndim > 1:
        x = x.mean(axis=1)
    if len(x) < n_fft:
        return np.zeros(12)
    win = np.hanning(n_fft)
    freqs = np.fft.rfftfreq(n_fft, 1.0 / sr)
    band = (freqs >= fmin) & (freqs <= fmax)
    midi = 69 + 12 * np.log2(freqs[band] / 440.0)
    pcs = np.mod(np.round(midi).astype(int), 12)
    # trọng số: ưu tiên nốt nằm gần tâm bán cung (giảm rò rỉ giữa hai cung)
    frac = np.abs(midi - np.round(midi))
    weight = np.clip(1.0 - 2.0 * frac, 0.0, 1.0)
    chroma = np.zeros(12)
    for start in range(0, len(x) - n_fft + 1, hop):
        frame = x[start:start + n_fft] * win
        mag = np.abs(np.fft.rfft(frame))[band]
        # nén log để giảm ảnh hưởng của trống/bass quá lớn
        mag = np.log1p(100.0 * mag / (mag.max() + 1e-12))
        np.add.at(chroma, pcs, mag * weight)
    return chroma


def estimate_key(chroma: np.ndarray) -> Optional[KeyResult]:
    c = np.asarray(chroma, dtype=np.float64)
    if c.sum() <= 1e-9 or np.allclose(c, c[0]):
        return None
    scores = []
    for mode, prof in (("major", _MAJOR), ("minor", _MINOR)):
        for t in range(12):
            r = np.corrcoef(c, np.roll(prof, t))[0, 1]
            scores.append((float(r), t, mode))
    scores.sort(reverse=True)
    best = scores[0]
    rel = ((best[1] + 9) % 12, "minor") if best[2] == "major" else ((best[1] + 3) % 12, "major")
    # tone tốt nhì KHÁC bộ nốt (bỏ qua tone song song)
    second = next(s for s in scores[1:] if (s[1], s[2]) != rel)
    gap = best[0] - second[0]
    # gap ~0.15 trở lên là rõ ràng với nhạc pop; chuẩn hoá về 0..1
    confidence = float(np.clip(gap / 0.15, 0.0, 1.0) * np.clip(best[0] / 0.6, 0.0, 1.0))
    return KeyResult(best[1], best[2], confidence, best[0], key_name(second[1], second[2]))


@dataclass
class KeyTracker:
    """Theo dõi tone theo thời gian, có ngưỡng tin cậy, trễ (hysteresis) và khoá tone.

    - Chỉ đề xuất tone mới khi độ tin cậy >= min_confidence và kết quả lặp lại
      `stable_hits` lần liên tiếp -> tránh nhảy tone giữa câu hát.
    - Khi `locked` = True: không bao giờ đổi tone tự động, chỉ báo "có thể đã chuyển giọng".
    """
    min_confidence: float = 0.55
    stable_hits: int = 3
    decay: float = 0.85          # trọng số giữ lại chroma cũ mỗi lần cập nhật
    locked: bool = False
    current: Optional[KeyResult] = None
    _acc: np.ndarray = field(default_factory=lambda: np.zeros(12))
    _candidate: Optional[tuple] = None
    _hits: int = 0
    last_estimate: Optional[KeyResult] = None
    modulation_suspected: bool = False

    def reset(self) -> None:
        self._acc = np.zeros(12)
        self._candidate, self._hits = None, 0
        self.current, self.last_estimate = None, None
        self.modulation_suspected = False

    def update(self, chroma_block: np.ndarray) -> Optional[KeyResult]:
        """Nạp chroma của một khối nhạc mới. Trả về tone mới nếu cần áp dụng, ngược lại None."""
        if np.sum(chroma_block) <= 1e-9:
            return None  # nhạc im lặng: giữ nguyên
        self._acc = self._acc * self.decay + chroma_block / (np.sum(chroma_block) + 1e-12)
        est = estimate_key(self._acc)
        self.last_estimate = est
        if est is None or est.confidence < self.min_confidence:
            self._hits = 0
            return None
        key = (est.tonic, est.mode)
        if self.current is not None and key == (self.current.tonic, self.current.mode):
            self._hits, self.modulation_suspected = 0, False
            return None
        if key == self._candidate:
            self._hits += 1
        else:
            self._candidate, self._hits = key, 1
        if self._hits < self.stable_hits:
            return None
        if self.locked and self.current is not None:
            self.modulation_suspected = True
            return None
        self.current = est
        self._hits, self.modulation_suspected = 0, False
        return est

    def top_candidates(self, n: int = 3) -> List[str]:
        if self._acc.sum() <= 0:
            return []
        out = []
        for mode, prof in (("major", _MAJOR), ("minor", _MINOR)):
            for t in range(12):
                out.append((float(np.corrcoef(self._acc, np.roll(prof, t))[0, 1]), key_name(t, mode)))
        out.sort(reverse=True)
        return [name for _, name in out[:n]]
