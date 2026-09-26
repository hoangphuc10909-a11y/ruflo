"""Điểm khởi chạy (PyInstaller và chạy trực tiếp).

  python run_app.py              -> mở ứng dụng
  python run_app.py --kiem-tra   -> chỉ kiểm tra máy, ghi & mở báo cáo (không thay đổi gì)
"""
import os
import sys

if __name__ == "__main__":
    if "--kiem-tra" in sys.argv:
        from ailive import diagnose
        checks, raw = diagnose.run()
        path = diagnose.write_report(checks, raw)
        if hasattr(os, "startfile") and not os.environ.get("AILIVE_SMOKE"):
            os.startfile(str(path))
    else:
        from ailive.app import main
        main()
