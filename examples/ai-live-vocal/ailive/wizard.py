"""Trợ lý cài đặt: danh sách việc còn thiếu, tự cập nhật, mỗi việc có nút làm ngay."""
from __future__ import annotations

import tkinter as tk
import webbrowser
from tkinter import messagebox, ttk

from . import winsys

LOOPMIDI_URL = "https://www.tobias-erichsen.de/software/loopmidi.html"


class SetupWizard:
    def __init__(self, app):
        self.app = app
        w = self.win = tk.Toplevel(app.root)
        w.title("Trợ lý cài đặt — AI LIVE VOCAL")
        w.geometry("720x480")
        w.configure(bg="#15171c")
        ttk.Label(w, text="Làm lần lượt từ trên xuống. Danh sách tự cập nhật khi xong mỗi bước.",
                  font=("Segoe UI", 13, "bold")).pack(anchor="w", padx=16, pady=(14, 6))
        self.box = tk.Frame(w, bg="#15171c")
        self.box.pack(fill="both", expand=True, padx=16)
        bar = tk.Frame(w, bg="#15171c")
        bar.pack(fill="x", padx=16, pady=12)
        ttk.Button(bar, text="Tải loopMIDI (miễn phí)", command=lambda: webbrowser.open(LOOPMIDI_URL)).pack(side="left")
        ttk.Button(bar, text="Cài script vào Cubase", command=self._install).pack(side="left", padx=8)
        ttk.Button(bar, text="Mở Nâng cao…", command=app.open_advanced).pack(side="left")
        self._last = None
        self._tick()

    def _install(self) -> None:
        from .advanced import SCRIPT_SRC
        try:
            dest = winsys.install_midi_remote_script(SCRIPT_SRC)
            self.app.changes.add("install_script", path=str(dest))
            messagebox.showinfo("Đã cài", "Trong Cubase: khung MIDI Remote (dưới cùng) → bấm 'Reload Scripts'.")
        except Exception as e:
            messagebox.showerror("Lỗi", str(e))

    def _tick(self) -> None:
        if not self.win.winfo_exists():
            return
        steps = self.app.pending_setup()
        if steps != self._last:
            self._last = steps
            for c in self.box.winfo_children():
                c.destroy()
            if not steps:
                ttk.Label(self.box, text="✓ Đã cài đặt xong. Đóng cửa sổ này và bấm BẮT ĐẦU HÁT.",
                          foreground="#5fd38d", font=("Segoe UI", 14, "bold")).pack(anchor="w", pady=8)
            for i, text in enumerate(steps, 1):
                ttk.Label(self.box, text=f"{i}. {text}", wraplength=680,
                          foreground="#f4c542" if i == 1 else "#c9d1d9").pack(anchor="w", pady=4)
        self.win.after(2000, self._tick)
