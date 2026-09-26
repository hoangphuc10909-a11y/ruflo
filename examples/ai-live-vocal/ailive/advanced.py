"""Cửa sổ Nâng cao: gán & hiệu chuẩn tham số, thiết bị, hát thử, kiểm tra TikTok, project."""
from __future__ import annotations

import os
import threading
import time
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from . import audio, diagnose, store, winsys
from .midi_link import TARGET_NAMES
from .roles import ROLES, calibrate, guess_assignments
from .voice import analyze_voice

SCRIPT_SRC = Path(__file__).resolve().parent.parent / "cubase" / "ailive_vocalbridge.js"


class AdvancedWindow:
    def __init__(self, app):
        self.app, self.ctl, self.cfg, self.link = app, app.ctl, app.cfg, app.link
        w = self.win = tk.Toplevel(app.root)
        w.title("AI LIVE VOCAL — Nâng cao")
        w.geometry("900x680")
        nb = ttk.Notebook(w)
        nb.pack(fill="both", expand=True)
        for title, build in (("1. Kiểm tra máy", self._tab_check), ("2. Tham số Cubase", self._tab_params),
                             ("3. Thiết bị âm thanh", self._tab_devices), ("4. Hát thử", self._tab_voice),
                             ("5. Kiểm tra TikTok", self._tab_tiktok), ("6. Project & sao lưu", self._tab_project),
                             ("Nhật ký", self._tab_log)):
            f = ttk.Frame(nb, padding=12)
            nb.add(f, text=title)
            build(f)

    def _out(self, parent, h=14) -> tk.Text:
        t = tk.Text(parent, height=h, wrap="word", font=("Consolas", 10))
        t.pack(fill="both", expand=True, pady=6)
        return t

    def _write(self, widget: tk.Text, text: str) -> None:
        def f():
            widget.delete("1.0", "end")
            widget.insert("end", text)
        self.win.after(0, f)

    def _thread(self, fn) -> None:
        threading.Thread(target=fn, daemon=True).start()

    # ---- 1 ----
    def _tab_check(self, f) -> None:
        ttk.Button(f, text="KIỂM TRA MÁY", command=lambda: self._thread(self._run_check)).pack(anchor="w")
        ttk.Button(f, text="Cài script cầu nối vào Cubase (MIDI Remote)", command=self._install_script).pack(anchor="w", pady=4)
        self.check_out = self._out(f, 24)

    def _run_check(self) -> None:
        self._write(self.check_out, "Đang kiểm tra…")
        checks, raw = diagnose.run()
        p = diagnose.write_report(checks, raw)
        self._write(self.check_out, p.read_text(encoding="utf-8") + f"\n\nĐã lưu báo cáo: {p}")

    def _install_script(self) -> None:
        try:
            dest = winsys.install_midi_remote_script(SCRIPT_SRC)
            self.app.changes.add("install_script", path=str(dest))
            messagebox.showinfo("Đã cài", f"Đã chép script tới:\n{dest}\n\nTrong Cubase: mở MIDI Remote (thanh dưới) "
                                "→ bấm ⟳ 'Reload Scripts'. Cubase sẽ tự nhận 'AI LIVE VOCAL' khi có 2 cổng loopMIDI.")
        except Exception as e:
            messagebox.showerror("Lỗi", str(e))

    # ---- 2 ----
    def _tab_params(self, f) -> None:
        ttk.Label(f, text="Cubase báo về các tham số của KÊNH ĐANG CHỌN (Quick Control 1-8, Fader, Send 1-4).\n"
                          "Chọn kênh giọng trong Cubase trước. Gán vai trò rồi bấm Hiệu chuẩn (KHÔNG làm khi đang LIVE).",
                  wraplength=860).pack(anchor="w")
        top = ttk.Frame(f)
        top.pack(fill="x", pady=6)
        ttk.Label(top, text="Tên kênh giọng:").pack(side="left")
        self.hint = tk.StringVar(value=self.cfg["vocal_track_hint"])
        ttk.Entry(top, textvariable=self.hint, width=24).pack(side="left", padx=6)
        ttk.Button(top, text="Lấy từ kênh đang chọn", command=self._take_hint).pack(side="left")
        ttk.Button(top, text="Tự nhận diện vai trò", command=self._guess).pack(side="left", padx=6)
        ttk.Button(top, text="Hiệu chuẩn tất cả", command=lambda: self._thread(self._calibrate_all)).pack(side="left")

        grid = ttk.Frame(f)
        grid.pack(fill="x")
        self.live_lbls = []
        for i, name in enumerate(TARGET_NAMES):
            ttk.Label(grid, text=name, width=16).grid(row=i, column=0, sticky="w")
            lab = ttk.Label(grid, text="—", width=70)
            lab.grid(row=i, column=1, sticky="w")
            self.live_lbls.append(lab)
        roles = ttk.LabelFrame(f, text="Vai trò → đích", padding=6)
        roles.pack(fill="x", pady=6)
        self.role_vars = {}
        opts = ["(không dùng)"] + TARGET_NAMES
        for i, (k, r) in enumerate(ROLES.items()):
            ttk.Label(roles, text=r.label, width=38).grid(row=i // 2, column=(i % 2) * 3, sticky="w")
            cur = self.cfg["assignments"].get(k)
            v = tk.StringVar(value=TARGET_NAMES[int(cur)] if cur is not None else opts[0])
            cb = ttk.Combobox(roles, textvariable=v, values=opts, width=16, state="readonly")
            cb.grid(row=i // 2, column=(i % 2) * 3 + 1, padx=4, pady=1)
            cb.bind("<<ComboboxSelected>>", lambda _e: self._save_roles())
            self.role_vars[k] = v
        self.cal_out = self._out(f, 6)
        self._tick_params()

    def _tick_params(self) -> None:
        if not self.win.winfo_exists():
            return
        for i, lab in enumerate(self.live_lbls):
            t = self.link.targets[i]
            lab.configure(text=f"{t.label or '—'}   =   {t.display}")
        self.win.after(500, self._tick_params)

    def _take_hint(self) -> None:
        self.hint.set(self.link.targets[8].obj)
        self.cfg["vocal_track_hint"] = self.hint.get()
        self.cfg.save()

    def _guess(self) -> None:
        g = guess_assignments({i: t.label for i, t in self.link.targets.items()})
        for k, v in self.role_vars.items():
            v.set(TARGET_NAMES[g[k]] if k in g else "(không dùng)")
        self._save_roles()

    def _save_roles(self) -> None:
        a = {}
        for k, v in self.role_vars.items():
            if v.get() in TARGET_NAMES:
                idx = TARGET_NAMES.index(v.get())
                if idx not in ROLES[k].targets:
                    messagebox.showwarning("Không hợp lệ", f"{ROLES[k].label} không thể gán vào {v.get()}.")
                    v.set("(không dùng)")
                    continue
                a[k] = idx
        self.cfg["assignments"] = a
        self.cfg["vocal_track_hint"] = self.hint.get()
        self.cfg.save()
        self.app.changes.add("assignments", assignments=a)

    def _calibrate_all(self) -> None:
        if not self.link.status.connected:
            self._write(self.cal_out, "Chưa kết nối Cubase.")
            return
        self._save_roles()
        self.ctl.capture_baseline()
        log_lines = []
        for k, idx in self.cfg["assignments"].items():
            self._write(self.cal_out, "\n".join(log_lines + [f"Đang hiệu chuẩn {ROLES[k].label}…"]))
            cal = calibrate(self.link, ROLES[k], idx)
            if len(cal.points) < 2:
                log_lines.append(f"✗ {ROLES[k].label}: Cubase không trả lời (kiểm tra đã chọn đúng kênh).")
                continue
            self.cfg["calibrations"][k] = cal.to_dict()
            rng = cal.range()
            opts = list(cal.options())
            desc = f"{rng[0]}…{rng[1]}" if rng and ROLES[k].kind != "enum" else ", ".join(opts[:14])
            log_lines.append(f"✓ {ROLES[k].label} [{cal.label}]: {desc}")
            time.sleep(0.2)
        self.cfg.save()
        self.app.changes.add("calibrate", roles=list(self.cfg["calibrations"]))
        self._write(self.cal_out, "\n".join(log_lines) + "\nXong. Tham số đã được trả về giá trị ban đầu.")

    # ---- 3 ----
    def _tab_devices(self, f) -> None:
        try:
            devs = audio.list_devices()
        except Exception as e:
            ttk.Label(f, text=f"Lỗi: {e}").pack()
            return
        self.dev_vars = {}
        for key, label, values in (("music_device", "Loa đang phát NHẠC (thu loopback để dò tone)", devs["speakers"]),
                                   ("mic_device", "Mic (bản sao để phân tích giọng)", devs["mics"]),
                                   ("mix_device", "Tín hiệu ĐÃ XỬ LÝ gửi TikTok (vd Mix 01)", devs["mics"])):
            ttk.Label(f, text=label).pack(anchor="w", pady=(8, 0))
            v = tk.StringVar(value=self.cfg[key])
            ttk.Combobox(f, textvariable=v, values=values, width=80).pack(anchor="w")
            self.dev_vars[key] = v
        ttk.Button(f, text="Lưu & khởi động lại thu", command=self._save_devices).pack(anchor="w", pady=10)

    def _save_devices(self) -> None:
        for k, v in self.dev_vars.items():
            self.cfg[k] = v.get()
        self.cfg.save()
        self.app._start_audio()

    # ---- 4 ----
    def _tab_voice(self, f) -> None:
        ttk.Label(f, text="Tắt nhạc. Bấm nút, giữ IM LẶNG 3 giây, rồi HÁT một đoạn quen (15 giây) ở mức hát LIVE thật.",
                  wraplength=860).pack(anchor="w")
        ttk.Button(f, text="HÁT THỬ (18 giây)", command=lambda: self._thread(self._voice_test)).pack(anchor="w", pady=6)
        self.voice_out = self._out(f, 16)
        self.sug_btn = ttk.Button(f, text="Áp dụng đề xuất", state="disabled", command=self._apply_sug)
        self.sug_btn.pack(anchor="w")
        self._sug = []

    def _voice_test(self) -> None:
        mic = self.app.caps.get("mic")
        if not mic or not mic.running:
            self._write(self.voice_out, "Chưa thu được mic. Chọn mic ở tab 3.")
            return
        self._write(self.voice_out, "Giữ im lặng…")
        mic.start_recording()
        time.sleep(3)
        silence = mic.stop_recording()
        self._write(self.voice_out, "HÁT ĐI! (15 giây)")
        mic.start_recording()
        time.sleep(15)
        singing = mic.stop_recording()
        rep = analyze_voice(silence, singing, audio.SR)
        self.cfg["voice_report"] = rep.to_dict()
        self.cfg.save()
        audio.write_wav(store.app_dir() / "hat-thu.wav", singing)
        self._sug = self.ctl.voice_suggestions(rep)
        lines = [f"Nền ồn: {rep.noise_floor_db} dBFS | Giọng TB: {rep.sing_rms_db} dBFS | Đỉnh: {rep.peak_db} dBFS",
                 f"Biến thiên âm lượng: {rep.dynamic_range_db} dB | Quãng: {rep.low_note} → {rep.high_note} "
                 f"(giữa {rep.median_note})",
                 f"Độ gắt 's': {rep.sibilance_ratio_db} dB | Độ đục: {rep.low_mud_ratio_db} dB", ""]
        lines += ["⚠ " + w for w in rep.warnings]
        lines += ["", "ĐỀ XUẤT:"] + ([f"• {s['label']}: {s['from']} → {s['to']}  ({s['why']})" for s in self._sug]
                                    or ["(không cần chỉnh hoặc chưa gán/hiệu chuẩn tham số EQ/nén)"])
        lines += ["", "Đây là điểm xuất phát dựa trên 15 giây hát thử, chưa phải bản cân giọng hoàn chỉnh."]
        self._write(self.voice_out, "\n".join(lines))
        self.win.after(0, lambda: self.sug_btn.configure(state="normal" if self._sug else "disabled"))

    def _apply_sug(self) -> None:
        done = self.ctl.apply_suggestions(self._sug)
        messagebox.showinfo("Đã áp dụng", "\n".join(done) or "Không áp dụng được mục nào.")

    # ---- 5 ----
    def _tab_tiktok(self, f) -> None:
        ttk.Label(f, text="Bật nhạc và hát 15 giây. Ứng dụng thu đúng tín hiệu TikTok sẽ nhận (thiết bị Mix) "
                          "để kiểm tra mức, clip, tiếng đôi. Sau đó nghe lại file thu.", wraplength=860).pack(anchor="w")
        ttk.Button(f, text="THU KIỂM TRA 15 GIÂY", command=lambda: self._thread(self._tiktok_test)).pack(anchor="w", pady=6)
        ttk.Button(f, text="Nghe lại bản thu", command=lambda: self._open(store.app_dir() / "kiem-tra-tiktok.wav")).pack(anchor="w")
        self.tt_out = self._out(f, 16)

    def _tiktok_test(self) -> None:
        mix, mus = self.app.caps.get("mix"), self.app.caps.get("music")
        if not mix or not mix.running:
            self._write(self.tt_out, "Chưa thu được thiết bị Mix. Chọn ở tab 3 (vd 'Mix 01').")
            return
        mix.start_recording()
        if mus:
            mus.start_recording()
        time.sleep(15)
        x = mix.stop_recording()
        ref = mus.stop_recording() if mus else None
        path = audio.write_wav(store.app_dir() / "kiem-tra-tiktok.wav", x)
        from .voice import dbfs, peak_dbfs
        lines = [f"Mức TB: {dbfs(x):.1f} dBFS | Đỉnh: {peak_dbfs(x):.1f} dBFS"]
        if peak_dbfs(x) > -1.0:
            lines.append("⚠ Gần/bị CLIP: giảm fader Master/Mix 2-3 dB hoặc bật limiter cuối chuỗi (ceiling -1 dB).")
        elif dbfs(x) < -35:
            lines.append("⚠ Tín hiệu rất nhỏ hoặc không có: TikTok sẽ nghe nhỏ/mất tiếng. Kiểm tra định tuyến Mix.")
        else:
            lines.append("✓ Mức tín hiệu hợp lý.")
        if ref is not None and len(ref) > audio.SR:
            d = audio.detect_double(ref, x)
            if d.get("ok"):
                lines.append(f"Nhạc có trong Mix: tương quan {d['corr']}, trễ {d['lag_ms']} ms")
                if d["doubled"]:
                    lines.append(f"⚠ Nghi TIẾNG ĐÔI (bản thứ hai trễ {d['second_lag_ms']} ms): TikTok có thể đang thu "
                                 "cả âm thanh máy tính lẫn Mix. Chỉ giữ MỘT nguồn trong TikTok LIVE Studio.")
        lines += ["", "Trong TikTok LIVE Studio: nguồn mic = thiết bị Mix; TẮT khử ồn/tự cân âm lượng/khử vọng "
                  "nếu nghe giọng bị méo, đuôi vang bị cắt hay nhạc bị nhỏ dần.", f"File: {path}"]
        self._write(self.tt_out, "\n".join(lines))
        self.app.changes.add("tiktok_test", level=round(dbfs(x), 1), peak=round(peak_dbfs(x), 1))

    # ---- 6 ----
    def _tab_project(self, f) -> None:
        ttk.Label(f, text=f"Project đang mở (theo tiêu đề Cubase): {winsys.cubase_status().get('project_hint') or '?'}").pack(anchor="w")
        self.proj = tk.StringVar(value=self.cfg["project_path"])
        row = ttk.Frame(f)
        row.pack(fill="x", pady=6)
        ttk.Entry(row, textvariable=self.proj, width=80).pack(side="left")
        ttk.Button(row, text="Chọn…", command=self._pick).pack(side="left", padx=4)
        ttk.Button(row, text="Tự tìm", command=lambda: self._thread(self._find)).pack(side="left")
        for text, fn in (("Sao lưu project", self._backup), ("Tạo bản riêng để hát TikTok", self._live_copy),
                         ("Khôi phục từ bản sao lưu…", self._restore),
                         ("Xuất cấu hình ứng dụng (preset đã chỉnh)…", self._export_cfg),
                         ("Nhập cấu hình ứng dụng…", self._import_cfg)):
            ttk.Button(f, text=text, command=fn).pack(anchor="w", pady=3)
        self.proj_out = self._out(f, 12)

    def _pick(self) -> None:
        p = filedialog.askopenfilename(filetypes=[("Cubase project", "*.cpr")])
        if p:
            self.proj.set(p)
            self.cfg["project_path"] = p
            self.cfg.save()

    def _find(self) -> None:
        hint = winsys.cubase_status().get("project_hint", "")
        found = store.find_projects(hint.replace(store.LIVE_SUFFIX, ""))
        if found and not self.proj.get():
            self.win.after(0, lambda: self.proj.set(str(found[0])))
        self._write(self.proj_out, "\n".join(map(str, found)) or "Không tìm thấy — bấm Chọn…")

    def _backup(self) -> None:
        try:
            d = store.backup_project(Path(self.proj.get()))
            self.app.changes.add("backup", src=self.proj.get(), dest=str(d))
            self._write(self.proj_out, f"Đã sao lưu: {d}")
        except Exception as e:
            self._write(self.proj_out, f"Lỗi: {e}")

    def _live_copy(self) -> None:
        try:
            live = store.create_live_copy(Path(self.proj.get()))
            self.app.changes.add("live_copy", path=str(live))
            self._write(self.proj_out, f"Bản hát TikTok: {live}\nMở file này trong Cubase (File > Open) để hát; "
                                       "bản gốc giữ nguyên.")
        except Exception as e:
            self._write(self.proj_out, f"Lỗi: {e}")

    def _restore(self) -> None:
        p = filedialog.askopenfilename(initialdir=str(store.backup_dir()), filetypes=[("Bản sao lưu", "*.cpr")])
        if not p:
            return
        if not messagebox.askyesno("Khôi phục", "ĐÓNG project đó trong Cubase trước. Tiếp tục khôi phục?"):
            return
        try:
            t = store.restore_project(Path(p))
            self.app.changes.add("restore_project", backup=p, target=str(t))
            self._write(self.proj_out, f"Đã khôi phục về {t} (bản hiện tại cũng đã được sao lưu).")
        except Exception as e:
            self._write(self.proj_out, f"Lỗi: {e}")

    def _export_cfg(self) -> None:
        p = filedialog.asksaveasfilename(defaultextension=".json", initialfile="ai-live-vocal-preset.json",
                                         filetypes=[("Cấu hình", "*.json")])
        if p:
            store.export_settings(self.cfg, Path(p))
            self._write(self.proj_out, f"Đã xuất cấu hình: {p}")

    def _import_cfg(self) -> None:
        p = filedialog.askopenfilename(filetypes=[("Cấu hình", "*.json")], initialdir=str(store.backup_dir()))
        if not p:
            return
        try:
            n = store.import_settings(self.cfg, Path(p))
            self.app.changes.add("import_settings", src=p, keys=n)
            self._write(self.proj_out, f"Đã nhập {n} mục cấu hình (cấu hình cũ đã được sao lưu). "
                                       "Khởi động lại ứng dụng để áp dụng thiết bị âm thanh.")
        except Exception as e:
            self._write(self.proj_out, f"Lỗi: {e}")

    # ---- nhật ký ----
    def _tab_log(self, f) -> None:
        out = self._out(f, 30)
        rows = self.app.changes.tail(200)
        self._write(out, "\n".join(f"{r['t']}  {r['action']}  " +
                                   ", ".join(f"{k}={v}" for k, v in r.items() if k not in ('t', 'action'))
                                   for r in rows))
        ttk.Button(f, text="Mở thư mục dữ liệu", command=lambda: self._open(store.app_dir())).pack(anchor="w")

    @staticmethod
    def _open(p: Path) -> None:
        if hasattr(os, "startfile"):
            os.startfile(str(p))  # type: ignore[attr-defined]
