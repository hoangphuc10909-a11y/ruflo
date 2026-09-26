"""Thu BẢN SAO tín hiệu để phân tích (không nằm trong đường âm thanh của Cubase).

- Nhạc: thu loopback từ thiết bị loa đang phát nhạc (WASAPI loopback).
- Mic: thu thiết bị mic (WDM) nếu driver cho dùng song song với ASIO.
- Mix: thu thiết bị nhận tín hiệu đã xử lý (vd "Mix 01" của sound card) — chính là
  thứ TikTok LIVE Studio sẽ nghe.
"""
from __future__ import annotations

import logging
import threading
import time
import wave
from collections import deque
from pathlib import Path
from typing import Deque, Dict, List, Optional

import numpy as np

log = logging.getLogger("ailive.audio")
SR = 48000
BLOCK = 4800  # 100 ms


def _sc():
    import soundcard as sc  # noqa: WPS433 (chỉ có trên máy thật)
    return sc


def list_devices() -> Dict[str, List[str]]:
    sc = _sc()
    return {
        "speakers": [s.name for s in sc.all_speakers()],
        "mics": [m.name for m in sc.all_microphones(include_loopback=False)],
    }


def find_device(names: List[str], hints: List[str]) -> str:
    for h in hints:
        for n in names:
            if h.lower() in n.lower():
                return n
    return ""


def open_source(name: str, loopback: bool):
    sc = _sc()
    if loopback:
        return sc.get_microphone(id=name, include_loopback=True)
    return sc.get_microphone(id=name, include_loopback=False)


class Capture(threading.Thread):
    """Luồng thu nền. Lỗi thiết bị không làm sập ứng dụng: tự thử lại mỗi 3 giây."""

    def __init__(self, label: str, device: str, loopback: bool, seconds: float = 30.0):
        super().__init__(name=f"cap-{label}", daemon=True)
        self.label, self.device, self.loopback = label, device, loopback
        self.buf: Deque[np.ndarray] = deque(maxlen=int(seconds * SR / BLOCK))
        self.rms_db = -120.0
        self.peak_db = -120.0
        self.last_signal = 0.0     # lần cuối có tín hiệu > -60 dBFS
        self.error = ""
        self.running = False
        self._stop = threading.Event()
        self._rec_lock = threading.Lock()
        self._rec: Optional[List[np.ndarray]] = None

    def stop(self) -> None:
        self._stop.set()

    def run(self) -> None:
        while not self._stop.is_set():
            try:
                src = open_source(self.device, self.loopback)
                with src.recorder(samplerate=SR, blocksize=BLOCK) as rec:
                    self.error, self.running = "", True
                    while not self._stop.is_set():
                        data = rec.record(numframes=BLOCK)
                        mono = data.mean(axis=1) if data.ndim > 1 else data
                        self._push(mono.astype(np.float32))
            except Exception as e:  # thiết bị bị rút, driver đổi, v.v.
                self.running = False
                self.error = f"{type(e).__name__}: {e}"
                log.warning("Thu %s lỗi: %s", self.label, self.error)
                self._stop.wait(3.0)

    def _push(self, mono: np.ndarray) -> None:
        self.buf.append(mono)
        rms = float(np.sqrt(np.mean(mono.astype(np.float64) ** 2)))
        self.rms_db = 20 * np.log10(rms + 1e-12)
        self.peak_db = 20 * np.log10(float(np.max(np.abs(mono))) + 1e-12)
        if self.rms_db > -60:
            self.last_signal = time.time()
        with self._rec_lock:
            if self._rec is not None:
                self._rec.append(mono)

    def latest(self, seconds: float) -> np.ndarray:
        n = max(1, int(seconds * SR / BLOCK))
        blocks = list(self.buf)[-n:]
        return np.concatenate(blocks) if blocks else np.zeros(0, dtype=np.float32)

    def silent_for(self) -> float:
        return time.time() - self.last_signal if self.last_signal else float("inf")

    def start_recording(self) -> None:
        with self._rec_lock:
            self._rec = []

    def stop_recording(self) -> np.ndarray:
        with self._rec_lock:
            data, self._rec = self._rec or [], None
        return np.concatenate(data) if data else np.zeros(0, dtype=np.float32)


def write_wav(path: Path, x: np.ndarray, sr: int = SR) -> Path:
    path = Path(path)
    pcm = (np.clip(x, -1, 1) * 32767).astype("<i2")
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sr)
        w.writeframes(pcm.tobytes())
    return path


def envelope(x: np.ndarray, sr: int = SR, hop_s: float = 0.01) -> np.ndarray:
    hop = int(sr * hop_s)
    n = len(x) // hop
    if n == 0:
        return np.zeros(0)
    return np.sqrt(np.mean(x[:n * hop].reshape(n, hop).astype(np.float64) ** 2, axis=1))


def estimate_tempo(x: np.ndarray, sr: int = SR, lo: float = 60, hi: float = 180) -> tuple:
    """BPM từ tự tương quan của đường bao onset. Trả về (bpm, độ tin cậy 0..1)."""
    env = envelope(x, sr)
    if len(env) < 400:
        return (0.0, 0.0)
    onset = np.maximum(np.diff(np.log1p(1000 * env)), 0)
    onset -= onset.mean()
    ac = np.correlate(onset, onset, mode="full")[len(onset) - 1:]
    if ac[0] <= 0:
        return (0.0, 0.0)
    ac /= ac[0]
    lags = np.arange(len(ac)) * 0.01
    band = (lags >= 60 / hi) & (lags <= 60 / lo)
    if not band.any():
        return (0.0, 0.0)
    i = np.argmax(np.where(band, ac, -1))
    return (round(60 / lags[i], 1), float(np.clip(ac[i] / 0.3, 0, 1)))


def detect_double(reference: np.ndarray, mix: np.ndarray, sr: int = SR, max_lag_s: float = 0.5) -> dict:
    """Phát hiện 'tiếng đôi': trong tín hiệu mix có 2 bản của cùng nguồn lệch thời gian
    (vd TikTok thu cả loa desktop lẫn Mix). Dựa trên tương quan đường bao."""
    a, b = envelope(reference, sr), envelope(mix, sr)
    n = min(len(a), len(b))
    if n < 300:
        return {"ok": False, "reason": "chưa đủ dữ liệu"}
    a, b = a[:n] - a[:n].mean(), b[:n] - b[:n].mean()
    maxlag = int(max_lag_s / 0.01)
    corr = np.array([np.dot(a[:n - k], b[k:]) for k in range(maxlag)])
    norm = np.sqrt(np.dot(a, a) * np.dot(b, b)) + 1e-12
    corr = corr / norm
    order = np.argsort(corr)[::-1]
    main = int(order[0])
    second = next((int(k) for k in order[1:] if abs(int(k) - main) > 3), None)
    doubled = False
    if second is not None and corr[main] > 0.3 and corr[second] > 0.5 * corr[main]:
        # loại trừ trường hợp đỉnh thứ hai chỉ do nhịp lặp của chính bài nhạc
        d = abs(second - main)
        self_corr = float(np.dot(a[:n - d], a[d:]) / (np.dot(a, a) + 1e-12))
        doubled = self_corr < 0.5 * float(corr[second] / corr[main])
    return {"ok": True, "lag_ms": main * 10, "corr": round(float(corr[main]), 2),
            "doubled": bool(doubled), "second_lag_ms": (second * 10) if second is not None else None}
