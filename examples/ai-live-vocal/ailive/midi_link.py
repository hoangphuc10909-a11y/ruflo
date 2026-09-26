"""Kết nối ứng dụng <-> Cubase qua MIDI Remote (cổng loopMIDI).

Vì sao MIDI thay vì bấm giao diện: Windows chặn tiến trình quyền thường gửi
thao tác chuột/phím vào cửa sổ chạy quyền Administrator (UIPI). Cổng MIDI không
bị chặn, nên ứng dụng hoạt động dù Cubase chạy quyền nào. Mọi giá trị đều được
Cubase gửi ngược lại (SysEx) để kiểm chứng thay vì đoán.
"""
from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass
from typing import Callable, Dict, List, Optional

log = logging.getLogger("ailive.midi")

PORT_TO_CUBASE = "AILive To Cubase"
PORT_FROM_CUBASE = "AILive From Cubase"
HEADER = [0x7D, 0x41, 0x4C]  # sau F0 (mido bỏ F0/F7 trong .data)
CC_BASE = 20
N_TARGETS = 13
TARGET_NAMES = [f"Quick Control {i + 1}" for i in range(8)] + ["Fader"] + [f"Send {i + 1}" for i in range(4)]
SEP = (0x7F, 0x7F, 0x7F)


def decode_string(data: List[int]) -> str:
    units = []
    for i in range(0, len(data) - 2, 3):
        units.append((data[i] << 14) | (data[i + 1] << 7) | data[i + 2])
    raw = b"".join(u.to_bytes(2, "little") for u in units if u <= 0xFFFF)
    return raw.decode("utf-16-le", errors="replace")


def encode_string(s: str) -> List[int]:
    """Bản Python của encodeString trong script JS (dùng cho kiểm thử)."""
    out: List[int] = []
    for u in memoryview(s.encode("utf-16-le")).cast("H"):
        out += [(u >> 14) & 0x7F, (u >> 7) & 0x7F, u & 0x7F]
    return out


@dataclass
class TargetState:
    value: Optional[float] = None        # 0..1 từ Cubase
    display: str = ""                    # ví dụ "-6.02 dB", "25", "C"
    obj: str = ""                        # ví dụ "Auto-Tune Artist"
    title: str = ""                      # ví dụ "Retune Speed"
    updated: float = 0.0

    @property
    def label(self) -> str:
        return f"{self.obj} · {self.title}".strip(" ·")


@dataclass
class LinkStatus:
    ports_found: bool = False
    connected: bool = False
    script_version: Optional[int] = None
    last_pong: float = 0.0
    error: str = ""


class CubaseLink:
    """Gửi CC có làm mượt (ramp) và nhận trạng thái phản hồi từ script MIDI Remote."""

    def __init__(self, backend=None):
        self._mido = backend  # cho phép chèn backend giả khi kiểm thử
        self.targets: Dict[int, TargetState] = {i: TargetState() for i in range(N_TARGETS)}
        self.status = LinkStatus()
        self._out = None
        self._in = None
        self._lock = threading.RLock()
        self._ramps: Dict[int, threading.Event] = {}
        self._events: Dict[int, threading.Event] = {i: threading.Event() for i in range(N_TARGETS)}
        self.on_change: Optional[Callable[[int, TargetState], None]] = None
        self._stop = threading.Event()
        self._hb: Optional[threading.Thread] = None

    # ---------- cổng ----------
    def _lib(self):
        if self._mido is None:
            import mido  # noqa: WPS433
            self._mido = mido
        return self._mido

    def available_ports(self) -> Dict[str, List[str]]:
        lib = self._lib()
        return {"in": list(lib.get_input_names()), "out": list(lib.get_output_names())}

    @staticmethod
    def _match(names: List[str], wanted: str) -> Optional[str]:
        # Windows thường thêm số thứ tự: "AILive To Cubase 1"
        for n in names:
            if n == wanted or n.startswith(wanted + " ") or n.startswith(wanted):
                return n
        return None

    def open(self) -> bool:
        self.close()
        try:
            ports = self.available_ports()
        except Exception as e:  # thiếu python-rtmidi hoặc driver MIDI lỗi
            self.status.error = f"Không đọc được danh sách cổng MIDI: {e}"
            return False
        out_name = self._match(ports["out"], PORT_TO_CUBASE)
        in_name = self._match(ports["in"], PORT_FROM_CUBASE)
        self.status.ports_found = bool(out_name and in_name)
        if not self.status.ports_found:
            missing = [p for p, n in ((PORT_TO_CUBASE, out_name), (PORT_FROM_CUBASE, in_name)) if not n]
            self.status.error = "Chưa có cổng MIDI ảo: " + ", ".join(missing) + " (tạo trong loopMIDI)."
            return False
        lib = self._lib()
        try:
            self._out = lib.open_output(out_name)
            self._in = lib.open_input(in_name, callback=self._on_msg)
        except Exception as e:
            self.status.error = f"Không mở được cổng MIDI (có thể ứng dụng khác đang giữ): {e}"
            self.close()
            return False
        self.status.error = ""
        self._stop.clear()
        self._hb = threading.Thread(target=self._heartbeat, name="midi-heartbeat", daemon=True)
        self._hb.start()
        self.request_dump()
        return True

    def close(self) -> None:
        self._stop.set()
        for ev in list(self._ramps.values()):
            ev.set()
        for p in (self._in, self._out):
            try:
                if p is not None:
                    p.close()
            except Exception:
                pass
        self._in = self._out = None
        self.status.connected = False

    # ---------- gửi ----------
    def _send(self, msg) -> None:
        with self._lock:
            if self._out is None:
                raise ConnectionError("Chưa kết nối Cubase")
            self._out.send(msg)

    def _sysex(self, cmd: int) -> None:
        self._send(self._lib().Message("sysex", data=HEADER + [cmd]))

    def request_dump(self) -> None:
        self._sysex(0x01)

    def ping(self) -> None:
        self._sysex(0x02)

    def send_raw(self, idx: int, value01: float) -> None:
        cc = int(round(max(0.0, min(1.0, value01)) * 127))
        self._send(self._lib().Message("control_change", channel=0, control=CC_BASE + idx, value=cc))

    def set_value(self, idx: int, target01: float, ramp_s: float = 0.35) -> None:
        """Đặt giá trị có chuyển mượt để tránh giật âm lượng/âm sắc. Không chặn luồng gọi."""
        target01 = max(0.0, min(1.0, target01))
        old = self._ramps.pop(idx, None)
        if old is not None:
            old.set()
        start = self.targets[idx].value
        if start is None or ramp_s <= 0:
            self.send_raw(idx, target01)
            return
        cancel = threading.Event()
        self._ramps[idx] = cancel

        def run():
            steps = max(1, int(abs(target01 - start) * 127))
            dt = ramp_s / steps
            for k in range(1, steps + 1):
                if cancel.is_set() or self._out is None:
                    return
                self.send_raw(idx, start + (target01 - start) * k / steps)
                time.sleep(dt)
            self._ramps.pop(idx, None)

        threading.Thread(target=run, name=f"ramp-{idx}", daemon=True).start()

    def set_and_read(self, idx: int, value01: float, timeout: float = 0.25) -> Optional[str]:
        """Gửi ngay giá trị rồi chờ Cubase báo lại chuỗi hiển thị (dùng khi hiệu chuẩn)."""
        ev = self._events[idx]
        ev.clear()
        self.send_raw(idx, value01)
        return self.targets[idx].display if ev.wait(timeout) else None

    # ---------- nhận ----------
    def _on_msg(self, msg) -> None:
        if msg.type != "sysex":
            return
        self.handle_sysex(list(msg.data))

    def handle_sysex(self, data: List[int]) -> None:
        if len(data) < 5 or data[:3] != HEADER:
            return
        typ, idx, payload = data[3], data[4], data[5:]
        now = time.time()
        if typ == 0x20:
            self.status.last_pong, self.status.connected = now, True
            self.status.script_version = payload[0] if payload else None
            return
        if typ == 0x21:
            self.status.script_version = payload[0] if payload else None
            self.status.last_pong, self.status.connected = now, True
            return
        if idx >= N_TARGETS:
            return
        t = self.targets[idx]
        if typ == 0x10 and len(payload) >= 2:
            t.value = ((payload[0] << 7) | payload[1]) / 16383.0
        elif typ == 0x11:
            t.display = decode_string(payload)
            self._events[idx].set()
        elif typ == 0x12:
            cut = next((i for i in range(0, len(payload) - 2, 3) if tuple(payload[i:i + 3]) == SEP), len(payload))
            t.obj, t.title = decode_string(payload[:cut]), decode_string(payload[cut + 3:])
        else:
            return
        t.updated = now
        self.status.last_pong, self.status.connected = now, True
        if self.on_change:
            try:
                self.on_change(idx, t)
            except Exception:
                log.exception("on_change lỗi")

    def _heartbeat(self) -> None:
        while not self._stop.wait(2.0):
            try:
                self.ping()
            except Exception as e:
                self.status.error = str(e)
            if time.time() - self.status.last_pong > 6.0:
                self.status.connected = False

    def snapshot(self) -> Dict[int, dict]:
        return {i: {"value": t.value, "display": t.display, "obj": t.obj, "title": t.title}
                for i, t in self.targets.items()}
