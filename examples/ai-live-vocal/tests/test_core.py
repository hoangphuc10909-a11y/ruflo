import time
from pathlib import Path

import numpy as np
import pytest

from ailive import audio, store
from ailive.controller import Controller, strength_to_tune
from ailive.keydetect import KeyTracker, chroma_from_audio, estimate_key
from ailive.midi_link import CubaseLink, decode_string, encode_string
from ailive.roles import ROLES, calibrate, guess_assignments, norm_note, parse_number
from ailive.voice import analyze_voice, yin_pitch
from tests.fake_cubase import FakeCubase, FakeMido

SR = 22050


def tone(freqs, dur, sr=SR, harmonics=4):
    t = np.arange(int(dur * sr)) / sr
    x = np.zeros_like(t)
    for f in freqs:
        for h in range(1, harmonics + 1):
            x += np.sin(2 * np.pi * f * h * t) / h
    return x / (len(freqs) * 2)


def midi_hz(m):
    return 440 * 2 ** ((m - 69) / 12)


def progression(chords, dur=1.5, seed=0):
    rng = np.random.default_rng(seed)
    parts = [tone([midi_hz(n) for n in c], dur) for c in chords]
    x = np.concatenate(parts)
    return x + 0.02 * rng.standard_normal(len(x))


G_MAJOR = [[43, 59, 62, 67], [50, 62, 66, 69], [52, 64, 67, 71], [48, 60, 64, 67]] * 3  # G D Em C
A_MINOR = [[45, 57, 60, 64], [41, 57, 60, 65], [48, 60, 64, 67], [43, 59, 62, 67]] * 3  # Am F C G
E_MAJOR = [[40, 56, 59, 64], [47, 59, 63, 66], [49, 61, 64, 68], [45, 57, 61, 64]] * 3  # E B C#m A


@pytest.mark.parametrize("chords,accept", [
    (G_MAJOR, {"G Major", "E Minor"}),
    (A_MINOR, {"A Minor", "C Major"}),
    (E_MAJOR, {"E Major", "C# Minor"}),
])
def test_key_estimate(chords, accept):
    k = estimate_key(chroma_from_audio(progression(chords), SR))
    assert k is not None and k.name in accept
    assert k.confidence > 0.3


def test_single_sung_note_is_not_confident():
    """Một nốt đơn không đủ để kết luận tone (yêu cầu: không suy tone từ một nốt giọng)."""
    k = estimate_key(chroma_from_audio(tone([midi_hz(57)], 6), SR))
    assert k is None or k.confidence < 0.55


def test_tracker_needs_stability_and_respects_lock():
    tr = KeyTracker(min_confidence=0.3, stable_hits=3)
    blocks = [chroma_from_audio(progression(G_MAJOR[:4], seed=i), SR) for i in range(6)]
    results = [tr.update(b) for b in blocks]
    first = next(i for i, r in enumerate(results) if r is not None)
    assert first >= 2  # không đổi ngay lần đầu
    assert tr.current.name in {"G Major", "E Minor"}
    tr.locked = True
    tr.decay = 0.3
    for i in range(8):
        assert tr.update(chroma_from_audio(progression(E_MAJOR[:4], seed=10 + i), SR)) is None
    assert tr.current.name in {"G Major", "E Minor"}
    assert tr.modulation_suspected


@pytest.mark.parametrize("hz", [98.0, 146.8, 220.0, 329.6])
def test_yin(hz):
    p = yin_pitch(tone([hz], 0.06, sr=44100), 44100)
    assert p is not None and abs(12 * np.log2(p / hz)) < 0.15


def test_voice_report():
    rng = np.random.default_rng(1)
    silence = 0.001 * rng.standard_normal(3 * SR)
    sing = np.concatenate([tone([midi_hz(m)], 1.0) * 0.3 for m in (48, 50, 52, 55, 57, 55, 52)])
    sing += 0.001 * rng.standard_normal(len(sing))
    rep = analyze_voice(silence, sing, SR)
    assert rep.low_note in {"C3", "C#3", "B2"} and rep.high_note in {"A3", "Ab3", "G#3"}
    assert rep.noise_floor_db < -55 and not rep.clipped


def test_sysex_string_roundtrip_vietnamese():
    s = "Giọng hát · Auto-Tune Artist ♯"
    assert decode_string(encode_string(s)) == s


def make_link():
    cub = FakeCubase()
    link = CubaseLink(backend=FakeMido(cub))
    cub.attach(link)
    assert link.open()
    time.sleep(0.05)
    return cub, link


def test_link_receives_titles_and_values():
    cub, link = make_link()
    assert link.status.connected and link.status.script_version == 3
    assert link.targets[2].label == "Auto-Tune Artist · Retune Speed"
    assert link.targets[2].display == "20"
    link.close()


def test_ramp_is_smooth_and_monotonic():
    cub, link = make_link()
    link.set_value(8, 0.2, ramp_s=0.1)
    time.sleep(0.4)
    vals = [v for i, v in cub.cc_log if i == 8]
    assert len(vals) > 20 and vals == sorted(vals, reverse=True)
    assert max(abs(a - b) for a, b in zip(vals, vals[1:])) <= 2
    link.close()


def test_calibration_and_fader_never_exceeds_safe_max():
    cub, link = make_link()
    cal = calibrate(link, ROLES["tune_speed"], 2, settle=0.05)
    assert cal.range() == (0.0, 400.0)
    assert abs(cub.params[2].value - 0.05) < 0.01  # đã trả về giá trị gốc
    v = cal.value_for_number(25)
    assert abs(float(cub.params[2].fmt(v)) - 25) <= 4

    key = calibrate(link, ROLES["tune_key"], 0, settle=0.05)
    assert norm_note(cub.params[0].fmt(key.value_for_option("Db"))) == "Db"

    cub.cc_log.clear()
    calibrate(link, ROLES["reverb_send"], 9, settle=0.05)
    worst = max(parse_number(cub.params[9].fmt(v / 127)) for i, v in cub.cc_log if i == 9 and v > 0)
    assert worst <= ROLES["reverb_send"].safe_max + 1.0  # quét dừng ngay khi vượt ngưỡng
    link.close()


def test_guess_assignments():
    cub, link = make_link()
    g = guess_assignments({i: t.label for i, t in link.targets.items()})
    assert g["tune_key"] == 0 and g["tune_scale"] == 1 and g["tune_speed"] == 2
    assert g["reverb_send"] == 9 and g["delay_send"] == 10
    link.close()


@pytest.fixture
def ctl(tmp_path, monkeypatch):
    monkeypatch.setenv("AILIVE_HOME", str(tmp_path))
    cub, link = make_link()
    cfg = store.Config(tmp_path / "c.json")
    c = Controller(cfg, link, store.ChangeLog(tmp_path / "log.jsonl"))
    cfg["assignments"] = guess_assignments({i: t.label for i, t in link.targets.items()})
    for role, idx in cfg["assignments"].items():
        cfg["calibrations"][role] = calibrate(link, ROLES[role], idx, settle=0.05).to_dict()
    yield cub, link, c
    link.close()


def test_style_key_and_restore(ctl):
    cub, link, c = ctl
    before = {i: p.value for i, p in cub.params.items()}
    applied = c.apply_style("bay")
    time.sleep(1.2)
    assert len(applied) == 4
    assert abs(float(cub.params[2].fmt(cub.params[2].value)) - strength_to_tune(65)["tune_speed"]) <= 4
    assert abs(parse_number(cub.params[9].fmt(cub.params[9].value)) - (-14)) <= 1.5

    k = estimate_key(chroma_from_audio(progression(A_MINOR), SR))
    assert c.apply_key(k)
    assert (cub.params[0].fmt(cub.params[0].value), cub.params[1].fmt(cub.params[1].value)) in {("A", "Minor"), ("C", "Major")}

    c.talk_mode()
    time.sleep(1.2)
    assert parse_number(cub.params[9].fmt(cub.params[9].value)) < -35
    assert cub.params[1].fmt(cub.params[1].value) == "Chromatic"

    c.restore_baseline()
    time.sleep(1.0)
    for i, v in before.items():
        assert abs(cub.params[i].value - v) < 0.02, i


def test_wrong_track_selected_blocks_control(ctl):
    cub, link, c = ctl
    cub.params[2].obj = "Guitar EQ"
    cub.announce()
    assert "tham số đã đổi" in c.role_ready("tune_speed")
    assert "Auto-Tune · Retune Speed = " not in " ".join(c.apply_style("tu_nhien"))


def test_project_backup_copy_restore(tmp_path, monkeypatch):
    monkeypatch.setenv("AILIVE_HOME", str(tmp_path / "home"))
    proj = tmp_path / "songs" / "PROJECT-10.cpr"
    proj.parent.mkdir()
    proj.write_bytes(b"ORIGINAL")
    live = store.create_live_copy(proj)
    assert live.name == "PROJECT-10-TIKTOK-LIVE.cpr" and live.read_bytes() == b"ORIGINAL"
    (b,) = store.list_backups("PROJECT-10")
    proj.write_bytes(b"BROKEN")
    store.restore_project(b)
    assert proj.read_bytes() == b"ORIGINAL"
    assert len(store.list_backups("PROJECT-10")) == 2  # bản BROKEN cũng được giữ


def test_tempo_and_double_detection():
    sr = 8000
    x = np.zeros(sr * 12)
    rng = np.random.default_rng(3)
    beat = int(sr * 60 / 120)
    for i in range(0, len(x) - 400, beat):
        x[i:i + 400] += rng.standard_normal(400) * np.hanning(400)
    bpm, conf = audio.estimate_tempo(x, sr)
    assert abs(bpm - 120) < 3 or abs(bpm - 60) < 2
    music = progression(A_MINOR, dur=0.9)[: SR * 10]
    single = music.copy()
    delay = int(0.23 * SR)
    double = music.copy()
    double[delay:] += music[:-delay]
    assert not audio.detect_double(music, single, SR)["doubled"]
    assert audio.detect_double(music, double, SR)["doubled"]


def test_cubase_js_script_speaks_same_protocol():
    """Chạy script MIDI Remote thật bằng Node (API giả lập) và giải mã bằng Python."""
    import json
    import shutil
    import subprocess
    if not shutil.which("node"):
        pytest.skip("không có node")
    out = subprocess.run(["node", str(Path(__file__).parent / "js" / "run_script.cjs")],
                         capture_output=True, text=True, check=True).stdout
    d = json.loads(out)
    assert d["knobs"] == 13 and d["bindings"][8] == [28, "Volume"]
    link = CubaseLink(backend=object())
    for m in d["sent"]:
        assert m[0] == 0xF0 and m[-1] == 0xF7 and all(0 <= b <= 0x7F for b in m[1:-1])
        link.handle_sysex(m[1:-1])
    assert link.targets[2].label == "Auto-Tune Artist · Retune Speed" and link.targets[2].display == "25"
    assert link.targets[8].label == "Giọng Chính · Volume" and link.targets[8].display == "-6.02 dB"
    assert link.status.script_version == 3


def test_delay_follows_tempo_only_when_confident(ctl):
    cub, link, c = ctl
    assert c.target_of("delay_time") == 4
    assert c.sync_delay(120, 0.2) is None  # chưa đủ tin cậy: không đổi
    assert c.sync_delay(120, 0.9) == 500
    time.sleep(0.1)
    assert abs(parse_number(cub.params[4].fmt(cub.params[4].value)) - 500) <= 15
    assert c.sync_delay(121, 0.9) is None  # lệch < 5%: giữ nguyên
    assert c.sync_delay(80, 0.9) == 375     # 750 ms quá dài → nửa phách


def test_output_guard_only_lowers_and_is_bounded(ctl):
    cub, link, c = ctl
    start = parse_number(cub.params[8].fmt(cub.params[8].value))
    c.guard.interval = 0.0
    total = 0.0
    for _ in range(60):
        total += c.protect_output(-0.2)
        time.sleep(0.02)
    time.sleep(0.5)
    end = parse_number(cub.params[8].fmt(cub.params[8].value))
    assert total == c.guard.max_cut_db == 6.0
    assert start - 7.5 <= end < start - 4.5
    assert c.protect_output(-20) == 0.0


def test_health_helpers():
    from ailive.health import SignalMonitor, auto_restore_allowed, setup_steps
    m = SignalMonitor()
    assert m.evaluate(True, 60, 0, 1, False, True)[0].startswith("Nhạc đang chạy nhưng MIC")
    assert "Mix" in m.evaluate(True, 0, 0, 10, True, True)[0]
    assert m.evaluate(False, 999, 0, None, False, True) == []
    steps = setup_steps(False, False, False, {}, {}, {}, False)
    assert steps[0].startswith("Mở loopMIDI") and len(steps) == 6
    assert setup_steps(True, True, True, {"tune_key": 0}, {"tune_key": {}},
                       {"music_device": 1, "mic_device": 1, "mix_device": 1}, True) == []
    cal = {"tune_speed": {"label": "Auto-Tune Artist · Retune Speed"}}
    assert auto_restore_allowed({"2": 0.1}, cal, lambda i: "Auto-Tune Artist · Retune Speed", {"tune_speed": 2})
    assert not auto_restore_allowed({"2": 0.1}, cal, lambda i: "Guitar · Gain", {"tune_speed": 2})
    assert not auto_restore_allowed({}, cal, lambda i: "", {})
