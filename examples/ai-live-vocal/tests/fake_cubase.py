"""Mô phỏng script MIDI Remote trong Cubase để kiểm thử (tái hiện đúng giao thức SysEx)."""
from __future__ import annotations

import mido

from ailive.midi_link import CC_BASE, CC_DUMP, CC_PING, HEADER, PORT_FROM_CUBASE, PORT_TO_CUBASE, encode_string

NOTES = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]
SCALES = ["Chromatic", "Major", "Minor"]


def fader_db(v: float) -> str:
    if v <= 0.001:
        return "-oo"
    # xấp xỉ đường cong fader Cubase: 0.75 ≈ 0 dB, 1.0 ≈ +6 dB
    db = (v - 0.75) * 24 if v >= 0.75 else -60 * (1 - v / 0.75) ** 1.6
    return f"{db:.2f}"


class Param:
    def __init__(self, obj, title, fmt, value=0.5):
        self.obj, self.title, self.fmt, self.value = obj, title, fmt, value


def default_params():
    return {
        0: Param("Auto-Tune Artist", "Key", lambda v: NOTES[min(11, int(v * 12))], 0.0),
        1: Param("Auto-Tune Artist", "Scale", lambda v: SCALES[min(2, int(v * 3))], 0.5),
        2: Param("Auto-Tune Artist", "Retune Speed", lambda v: str(int(round(v * 400))), 0.05),
        3: Param("Auto-Tune Artist", "Humanize", lambda v: str(int(round(v * 100))), 0.3),
        4: Param("MonoDelay", "Delay Time", lambda v: f"{20 + v * 1480:.0f} ms", 0.2),
        8: Param("VOCAL", "Volume", fader_db, 0.7),
        9: Param("FX 1-Reverb", "Send 1 Level", fader_db, 0.4),
        10: Param("FX 2-Delay", "Send 2 Level", fader_db, 0.3),
    }


class FakeCubase:
    def __init__(self, params=None, sysex_input=False):
        # Mặc định KHÔNG hỗ trợ nhận SysEx (trường hợp xấu nhất): chỉ dùng CC cho ping/dump
        self.sysex_input = sysex_input
        self.params = params or default_params()
        self.link = None
        self.cc_log = []

    def attach(self, link):
        self.link = link

    def _reply(self, typ, idx, payload):
        if self.link:
            self.link.handle_sysex(HEADER + [typ, idx] + payload)

    def announce(self):
        for idx, p in self.params.items():
            self._reply(0x12, idx, encode_string(p.obj) + [0x7F, 0x7F, 0x7F] + encode_string(p.title))
            self._emit(idx)

    def _emit(self, idx):
        p = self.params[idx]
        n = int(round(p.value * 16383))
        self._reply(0x10, idx, [(n >> 7) & 0x7F, n & 0x7F])
        self._reply(0x11, idx, encode_string(p.fmt(p.value)))

    def receive(self, msg):
        if msg.type == "control_change" and msg.control == CC_PING:
            self._reply(0x20, 0, [4])
        elif msg.type == "control_change" and msg.control == CC_DUMP:
            self._reply(0x21, 0, [4])
            self.announce()
        elif msg.type == "control_change":
            idx = msg.control - CC_BASE
            self.cc_log.append((idx, msg.value))
            if idx in self.params:
                self.params[idx].value = msg.value / 127
                self._emit(idx)
        elif msg.type == "sysex" and self.sysex_input and list(msg.data[:3]) == HEADER:
            if msg.data[3] == 0x02:
                self._reply(0x20, 0, [4])
            elif msg.data[3] == 0x01:
                self._reply(0x21, 0, [4])
                self.announce()


class _Out:
    def __init__(self, cub):
        self.cub = cub

    def send(self, msg):
        self.cub.receive(msg)

    def close(self):
        pass


class FakeMido:
    Message = mido.Message

    def __init__(self, cub):
        self.cub = cub

    def get_input_names(self):
        return [PORT_FROM_CUBASE + " 2"]

    def get_output_names(self):
        return [PORT_TO_CUBASE + " 1"]

    def open_output(self, name):
        return _Out(self.cub)

    def open_input(self, name, callback=None):
        return _Out(self.cub)
