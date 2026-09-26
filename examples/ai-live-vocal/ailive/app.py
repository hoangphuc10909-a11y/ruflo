"""AI LIVE VOCAL — màn hình chính (tiếng Việt, nút lớn)."""
from __future__ import annotations

import logging
import threading
import time
import tkinter as tk
from tkinter import messagebox, ttk
from typing import Optional

from . import audio, winsys
from .controller import STYLES, Controller
from .midi_link import CubaseLink
from .store import ChangeLog, Config, setup_logging

log = logging.getLogger("ailive.app")
GREEN, RED, GREY, AMBER = "#1e9e4a", "#d0342c", "#8a8f98", "#e3a008"
FONT = ("Segoe UI", 13)
BIG = ("Segoe UI", 16, "bold")


class App:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.cfg = Config()
        self.changes = ChangeLog()
        self.link = CubaseLink()
        self.ctl = Controller(self.cfg, self.link, self.changes)
        self.caps: dict = {}
        self.tiktok = {"running": False}
        self.detecting_since: Optional[float] = None
        self.smart_reverb = tk.BooleanVar(value=True)
        self._stop = threading.Event()
        self._build()
        self._start_audio()
        threading.Thread(target=self._link_loop, name="link", daemon=True).start()
        threading.Thread(target=self._analysis_loop, name="analysis", daemon=True).start()
        self.root.after(300, self._refresh)
        self.root.protocol("WM_DELETE_WINDOW", self._quit)

    # ---------------- giao diện ----------------
    def _build(self) -> None:
        r = self.root
        r.title("AI LIVE VOCAL")
        r.geometry("760x720")
        r.configure(bg="#15171c")
        st = ttk.Style()
        st.theme_use("clam")
        st.configure("TLabel", background="#15171c", foreground="#f2f3f5", font=FONT)
        st.configure("Big.TButton", font=BIG, padding=14)
        st.configure("Mid.TButton", font=("Segoe UI", 13, "bold"), padding=10)
        st.configure("Sel.TButton", font=("Segoe UI", 13, "bold"), padding=10, background="#2d6cdf", foreground="white")
        st.configure("TScale", background="#15171c")

        top = tk.Frame(r, bg="#15171c")
        top.pack(fill="x", padx=16, pady=(14, 6))
        self.dots = {}
        for i, name in enumerate(("Mic", "Nhạc", "Cubase", "TikTok")):
            f = tk.Frame(top, bg="#15171c")
            f.grid(row=0, column=i, padx=8, sticky="w")
            c = tk.Canvas(f, width=18, height=18, bg="#15171c", highlightthickness=0)
            c.create_oval(2, 2, 16, 16, fill=GREY, tags="dot")
            c.pack(side="left")
            lab = ttk.Label(f, text=name)
            lab.pack(side="left", padx=4)
            self.dots[name] = (c, lab)

        row = tk.Frame(r, bg="#15171c")
        row.pack(fill="x", padx=16, pady=8)
        ttk.Button(row, text="🎤  BẮT ĐẦU HÁT", style="Big.TButton", command=self.start_singing).pack(
            side="left", expand=True, fill="x", padx=(0, 6))
        ttk.Button(row, text="💬  NÓI CHUYỆN", style="Big.TButton", command=self.talk).pack(
            side="left", expand=True, fill="x", padx=(6, 0))

        tone = tk.Frame(r, bg="#1d2027")
        tone.pack(fill="x", padx=16, pady=8)
        self.key_lbl = ttk.Label(tone, text="Tone nhạc: —", font=("Segoe UI", 18, "bold"), background="#1d2027")
        self.key_lbl.pack(anchor="w", padx=12, pady=(10, 0))
        self.key_note = ttk.Label(tone, text="", background="#1d2027", wraplength=700)
        self.key_note.pack(anchor="w", padx=12)
        tb = tk.Frame(tone, bg="#1d2027")
        tb.pack(fill="x", padx=12, pady=10)
        ttk.Button(tb, text="DÒ TONE", style="Mid.TButton", command=self.detect_key).pack(side="left", padx=(0, 8))
        self.lock_btn = ttk.Button(tb, text="🔓 KHOÁ TONE", style="Mid.TButton", command=self.toggle_lock)
        self.lock_btn.pack(side="left")

        sty = tk.Frame(r, bg="#15171c")
        sty.pack(fill="x", padx=16, pady=8)
        self.style_btns = {}
        for key, s in STYLES.items():
            b = ttk.Button(sty, text=s["label"], style="Mid.TButton", command=lambda k=key: self.choose_style(k))
            b.pack(side="left", expand=True, fill="x", padx=4)
            self.style_btns[key] = b

        sl = tk.Frame(r, bg="#15171c")
        sl.pack(fill="x", padx=16, pady=8)
        ttk.Label(sl, text="Mức chỉnh giọng (nhẹ → rõ)").grid(row=0, column=0, sticky="w")
        self.strength = tk.DoubleVar(value=self.cfg["tune_strength"])
        ttk.Scale(sl, from_=0, to=100, variable=self.strength, length=420,
                  command=lambda _=None: self._debounce("strength")).grid(row=0, column=1, padx=10, pady=6)
        ttk.Label(sl, text="Mức vang (ít → nhiều)").grid(row=1, column=0, sticky="w")
        self.reverb = tk.DoubleVar(value=self.cfg["reverb_offset_db"])
        ttk.Scale(sl, from_=-10, to=6, variable=self.reverb, length=420,
                  command=lambda _=None: self._debounce("reverb")).grid(row=1, column=1, padx=10, pady=6)
        tk.Checkbutton(sl, text="Vang thông minh (giảm vang khi đang hát)", variable=self.smart_reverb,
                       bg="#15171c", fg="#f2f3f5", selectcolor="#2a2d35", font=FONT,
                       activebackground="#15171c").grid(row=2, column=0, columnspan=2, sticky="w")

        bottom = tk.Frame(r, bg="#15171c")
        bottom.pack(fill="x", padx=16, pady=10)
        ttk.Button(bottom, text="↩  KHÔI PHỤC", style="Mid.TButton", command=self.restore).pack(side="left")
        ttk.Button(bottom, text="Lưu cấu hình đang hát tốt", command=self.save_good).pack(side="left", padx=10)
        ttk.Button(bottom, text="Nâng cao…", command=self.open_advanced).pack(side="right")

        self.msg = ttk.Label(r, text="", wraplength=720, foreground="#c9d1d9")
        self.msg.pack(fill="x", padx=16, pady=(4, 12))
        self._timers: dict = {}

    def say(self, text: str, level: str = "info") -> None:
        color = {"info": "#c9d1d9", "ok": "#5fd38d", "warn": "#f4c542", "err": "#ff7b72"}[level]
        self.root.after(0, lambda: self.msg.configure(text=text, foreground=color))
        log.info("UI: %s", text)

    def _debounce(self, what: str) -> None:
        if what in self._timers:
            self.root.after_cancel(self._timers[what])
        self._timers[what] = self.root.after(400, lambda: self._slider_changed(what))

    def _slider_changed(self, what: str) -> None:
        self.cfg["tune_strength"] = round(self.strength.get())
        self.cfg["reverb_offset_db"] = round(self.reverb.get(), 1)
        if self.ctl.mode == "sing" and self.link.status.connected:
            self._bg(lambda: self.ctl.apply_style(None), "Đã cập nhật mức chỉnh.")

    def _bg(self, fn, ok_text: str = "") -> None:
        def run():
            try:
                res = fn()
                if isinstance(res, list) and not res:
                    self.say("Chưa điều khiển được tham số nào. Mở Nâng cao → Gán & hiệu chuẩn.", "warn")
                elif ok_text:
                    self.say(ok_text + (" " + "; ".join(res) if isinstance(res, list) else ""), "ok")
            except Exception as e:
                log.exception("Lỗi thao tác")
                self.say(f"Lỗi: {e}", "err")
        threading.Thread(target=run, daemon=True).start()

    # ---------------- hành động ----------------
    def _precheck(self) -> bool:
        if not self.link.status.connected:
            self.say("Chưa kết nối Cubase. " + (self.link.status.error or
                     "Kiểm tra: Cubase đang mở, MIDI Remote đã nhận 'AI LIVE VOCAL'."), "err")
            return False
        hint = self.cfg["vocal_track_hint"]
        fader = self.link.targets[8].obj
        if hint and fader and hint.lower() not in fader.lower():
            self.say(f"Cubase đang chọn kênh '{fader}'. Hãy bấm chọn kênh giọng '{hint}' trong Cubase rồi thử lại.", "warn")
            return False
        return True

    def start_singing(self) -> None:
        if not self._precheck():
            return
        self._bg(lambda: self.ctl.apply_style(None), "Sẵn sàng hát.")
        if not self.ctl.current_key:
            self.detect_key()

    def talk(self) -> None:
        if self._precheck():
            self._bg(self.ctl.talk_mode, "Chế độ NÓI CHUYỆN: đã giảm vang và hiệu ứng.")

    def choose_style(self, key: str) -> None:
        self.strength.set(STYLES[key]["strength"])
        if self._precheck():
            self._bg(lambda: self.ctl.apply_style(key), f"Đã chọn {STYLES[key]['label']}.")

    def detect_key(self) -> None:
        self.ctl.tracker.reset()
        self.ctl.tracker.locked = False
        self.lock_btn.configure(text="🔓 KHOÁ TONE")
        self.detecting_since = time.time()
        self.say("Đang nghe NHẠC để dò tone (10–25 giây). Cứ để nhạc chạy, không cần hát.")

    def toggle_lock(self) -> None:
        locked = not self.ctl.tracker.locked
        self.ctl.set_lock(locked)
        self.lock_btn.configure(text="🔒 ĐÃ KHOÁ" if locked else "🔓 KHOÁ TONE")

    def restore(self) -> None:
        if not messagebox.askyesno("Khôi phục", "Đưa mọi tham số về trạng thái GỐC trước khi dùng ứng dụng?"):
            return
        self._bg(lambda: self.ctl.restore_baseline() or ["(chưa có bản gốc)"], "Đã khôi phục:")

    def save_good(self) -> None:
        self._bg(lambda: (self.ctl.save_last_good(), ["đã lưu"])[1], "Cấu hình hiện tại:")

    def open_advanced(self) -> None:
        from .advanced import AdvancedWindow
        AdvancedWindow(self)

    # ---------------- nền ----------------
    def _start_audio(self) -> None:
        for c in self.caps.values():
            c.stop()
        self.caps = {}
        try:
            devs = audio.list_devices()
        except Exception as e:
            self.say(f"Không mở được hệ thống âm thanh Windows: {e}", "err")
            return
        if not self.cfg["music_device"] and devs["speakers"]:
            import soundcard as sc
            self.cfg["music_device"] = sc.default_speaker().name
        if not self.cfg["mic_device"]:
            self.cfg["mic_device"] = audio.find_device(devs["mics"], ["icon", "cube", "mic"]) or ""
        if not self.cfg["mix_device"]:
            self.cfg["mix_device"] = audio.find_device(devs["mics"], ["mix 01", "mix"]) or ""
        self.cfg.save()
        for label, dev, loop in (("music", self.cfg["music_device"], True),
                                 ("mic", self.cfg["mic_device"], False),
                                 ("mix", self.cfg["mix_device"], False)):
            if dev:
                c = audio.Capture(label, dev, loop)
                c.start()
                self.caps[label] = c

    def _link_loop(self) -> None:
        while not self._stop.is_set():
            if not self.link.status.connected:
                if self.link._out is None:
                    self.link.open()
                else:
                    try:
                        self.link.request_dump()
                    except Exception:
                        self.link.open()
            try:
                self.tiktok = winsys.tiktok_status()
            except Exception:
                pass
            self._stop.wait(5.0)

    def _analysis_loop(self) -> None:
        last_key = 0.0
        while not self._stop.wait(0.2):
            mus, mic = self.caps.get("music"), self.caps.get("mic")
            try:
                if mic and self.smart_reverb.get() and self.link.status.connected:
                    noise = (self.cfg["voice_report"] or {}).get("noise_floor_db", -60.0)
                    self.ctl.update_singing(mic.rms_db, noise)
                if mus and time.time() - last_key > 2.0 and mus.silent_for() < 1.0:
                    last_key = time.time()
                    self.ctl.feed_music(mus.latest(4.0), audio.SR)
                    if self.ctl.current_key:
                        self.detecting_since = None
                if self.detecting_since and time.time() - self.detecting_since > 25 and not self.ctl.current_key:
                    self.detecting_since = None
                    self.ctl.fallback_chromatic()
                    self.say("Chưa đủ chắc chắn về tone → tạm dùng Chromatic (an toàn). Bấm DÒ TONE lại khi nhạc rõ hơn.", "warn")
            except Exception:
                log.exception("Phân tích lỗi")

    def _refresh(self) -> None:
        def dot(name, color, text=None):
            c, lab = self.dots[name]
            c.itemconfigure("dot", fill=color)
            if text:
                lab.configure(text=text)

        for name, key in (("Mic", "mic"), ("Nhạc", "music")):
            cap = self.caps.get(key)
            if not cap:
                dot(name, GREY, f"{name}: chưa chọn")
            elif cap.error:
                dot(name, RED, f"{name}: lỗi thiết bị")
            elif cap.silent_for() > 5:
                dot(name, AMBER, f"{name}: im lặng")
            else:
                dot(name, RED if cap.peak_db > -0.5 else GREEN, f"{name}: {cap.rms_db:.0f} dB")
        s = self.link.status
        dot("Cubase", GREEN if s.connected else RED, "Cubase: đã nối" if s.connected else "Cubase: chưa nối")
        dot("TikTok", GREEN if self.tiktok.get("running") else GREY,
            "TikTok: đang mở" if self.tiktok.get("running") else "TikTok: chưa mở")
        est = self.ctl.tracker.last_estimate
        if self.ctl.current_key:
            self.key_lbl.configure(text=f"Tone nhạc: {self.ctl.current_key}")
        elif est is not None and self.detecting_since:
            self.key_lbl.configure(text=f"Đang dò… ({est.name}? {est.confidence:.0%})")
        self.key_note.configure(text=self.ctl.key_note)
        for k, b in self.style_btns.items():
            b.configure(style="Sel.TButton" if k == self.cfg["style"] and self.ctl.mode == "sing" else "Mid.TButton")
        self.root.after(300, self._refresh)

    def _quit(self) -> None:
        # KHÔNG gửi gì thêm cho Cubase khi thoát: các tham số giữ nguyên, không nhảy âm lượng.
        self._stop.set()
        for c in self.caps.values():
            c.stop()
        self.link.close()
        self.cfg.save()
        self.root.destroy()


def main() -> None:
    setup_logging()
    root = tk.Tk()
    App(root)
    root.mainloop()


if __name__ == "__main__":
    main()
