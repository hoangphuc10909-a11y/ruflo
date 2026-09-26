# AI LIVE VOCAL — trợ lý điều khiển Cubase Pro 15 để hát LIVE TikTok

> Trạng thái: **v0.3 — đã kiểm thử tự động (Linux + máy Windows của GitHub), CHƯA chạy với Cubase thật trên máy bạn.**
> Mọi preset là **điểm xuất phát**, chưa phải bản cân giọng hoàn chỉnh cho tới khi hát thử và nghe lại.

## 1. Kiến trúc (vì sao chọn cách này)

```
 Nhạc (YouTube/Player) ──► Loa Windows ──(bản sao loopback)──► [AI LIVE VOCAL] dò tone, BPM
 Mic ──► iCON Cube2Nano ──ASIO──► CUBASE (Auto-Tune, EQ, Nén, Vang…) ──► Mix 01 ──► TikTok LIVE Studio
                                     ▲                                        │
                    MIDI (loopMIDI) ─┘  ◄── tên + giá trị tham số (SysEx) ────┘ (bản sao để kiểm tra)
```

* **Âm thanh không đi qua ứng dụng.** Cubase vẫn xử lý giọng thời gian thực; ứng dụng chỉ nghe
  *bản sao* để phân tích. Ứng dụng tắt/treo → giọng vẫn chạy bình thường, không nhảy âm lượng.
* **Điều khiển bằng MIDI Remote (tính năng chính thức của Cubase 12+), không bấm chuột giả.**
  Lỗi cũ “không bấm được Cubase” là do Windows chặn tiến trình quyền thường gửi thao tác vào
  cửa sổ quyền Administrator (UIPI). MIDI không bị chặn → không cần chạy app bằng quyền Admin.
* **Không đoán thông số.** Cubase gửi ngược *tên plugin, tên tham số, giá trị hiển thị*
  (“Auto-Tune Artist · Retune Speed = 25”). Ứng dụng quét và đọc lại để lập bảng tra (hiệu chuẩn),
  và **từ chối điều khiển** nếu tên tham số khác lúc hiệu chuẩn (ví dụ đang chọn nhầm track).
* Không sửa Cubase, không đụng bản quyền, không đọc/sửa nhị phân `.cpr` (chỉ sao chép nguyên file).

## 2. Cài đặt một lần (khoảng 15 phút)

1. **loopMIDI** (miễn phí, tobias-erichsen.de): tạo đúng 2 cổng
   `AILive To Cubase` và `AILive From Cubase`. Bật “Autostart loopMIDI”.
2. **Tải bản dựng sẵn (không cần Python):** GitHub → repo → tab *Actions* → *AI Live Vocal (Windows build)*
   → lần chạy mới nhất (dấu ✓ xanh) → mục *Artifacts* → tải **AI-LIVE-VOCAL-windows** → giải nén →
   chạy `AI LIVE VOCAL.exe`. (Tự build: cài Python 3.11 64-bit rồi chạy `build.bat`.)
   Chạy `kiem_tra_may.bat` (hoặc `AI LIVE VOCAL.exe --kiem-tra`) để tạo báo cáo kiểm tra máy.
3. Lần đầu mở app, **Trợ lý cài đặt** tự hiện danh sách việc còn thiếu (tự cập nhật, có nút làm ngay).
   Hoặc: **Nâng cao → 1. Kiểm tra máy** → bấm **Cài script cầu nối vào Cubase**.
   Trong Cubase: mở khung **MIDI Remote** (dưới cùng) → nút **Reload Scripts**.
   Cubase tự nhận thiết bị “AI LIVE VOCAL”.
4. Trong Cubase, **chọn kênh giọng**, gán **Quick Controls** của kênh (Inspector → Quick Controls):
   QC1 = Auto-Tune *Key*, QC2 = *Scale*, QC3 = *Retune Speed*, QC4 = *Humanize*;
   (tuỳ chọn) QC5–QC8 = Delay Time / EQ vùng đục / EQ độ sáng / De-esser hoặc Compressor threshold.
   Send 1 = kênh vang, Send 2 = kênh delay. **Lưu project** (Quick Controls được lưu trong project).
5. **Nâng cao → 2. Tham số Cubase**: bấm *Lấy từ kênh đang chọn* → *Tự nhận diện vai trò* →
   kiểm tra lại → **Hiệu chuẩn tất cả** (tắt nhạc, không LIVE; fader/send chỉ quét tăng dần và
   dừng ngay khi chạm ngưỡng an toàn; xong tự trả tham số về như cũ).
6. **3. Thiết bị âm thanh**: chọn loa đang phát nhạc, mic, và thiết bị *Mix 01* (tín hiệu gửi TikTok).
7. **4. Hát thử** (18 giây) → xem đề xuất → *Áp dụng đề xuất* nếu đồng ý.
8. **5. Kiểm tra TikTok**: bật nhạc, hát 15 giây → xem mức/clip/tiếng đôi → **nghe lại file thu**.

## 3. Dùng hằng ngày

| Nút | Việc làm |
|---|---|
| **BẮT ĐẦU HÁT** | Áp dụng phong cách đang chọn, tự dò tone nếu chưa có |
| **NÓI CHUYỆN** | Giảm vang/delay, Auto-Tune về Chromatic + chỉnh chậm (giọng nói tự nhiên) |
| **DÒ TONE** | Nghe *nhạc* 10–25 s, chỉ đặt Key/Scale khi đủ tin cậy; không chắc → Chromatic |
| **KHOÁ TONE** | Không đổi tone nữa; nếu nhạc chuyển giọng, chỉ hiện cảnh báo |
| TỰ NHIÊN / BAY / RÕ | 3 mức chỉnh cao độ + vang có sẵn |
| 2 thanh trượt | Mức chỉnh giọng, mức vang (có giới hạn) |
| **KHÔI PHỤC** | Trả mọi tham số về trạng thái gốc trước khi dùng app |
| Lưu cấu hình đang hát tốt | Ghi lại để lần sau khôi phục |

Đèn trạng thái: xanh = tốt, vàng = im lặng, đỏ = lỗi/clip, xám = chưa chọn.

Tự động khi đang chạy (chỉ trong giới hạn an toàn):
* **Mở app → tự khôi phục cấu hình hát tốt lần trước**, nhưng chỉ khi mọi tham số vẫn trỏ đúng
  plugin như lúc hiệu chuẩn (chọn nhầm kênh thì app báo, không ghi).
* **Chống clip đầu ra TikTok:** tín hiệu Mix chạm gần 0 dBFS liên tục → hạ fader giọng 1 dB/lần,
  tối đa 6 dB mỗi phiên. App **không bao giờ tự tăng** âm lượng.
* **Delay theo nhịp:** ước lượng BPM từ nhạc; chỉ đặt Delay Time (1 phách, hoặc ½ phách nếu > 600 ms)
  khi đủ tin cậy, lệch < 5% thì giữ nguyên; khi KHOÁ TONE thì cũng không đổi delay.
* **Báo mất tín hiệu:** mic im lặng khi đang hát có nhạc, Mix không có tiếng dù mic có tiếng,
  mất kết nối Cubase (giọng vẫn chạy bình thường).
* Mở app lần đầu: dòng thông báo cho biết **bước cài đặt tiếp theo** còn thiếu.

## 4. Sao lưu & khôi phục

* Dữ liệu: `%APPDATA%\AILiveVocal\` (config, nhật ký `changes.jsonl`, `ailive.log`, bản thu, báo cáo).
* **Project**: Nâng cao → 6 → *Sao lưu* (chép `.cpr` vào `backups\` có dấu thời gian, không bao giờ
  ghi đè bản cũ) → *Tạo bản riêng để hát TikTok* (`PROJECT-TIKTOK-LIVE.cpr`, cùng thư mục nên audio
  vẫn đúng đường dẫn; bản gốc giữ nguyên).
* *Khôi phục từ bản sao lưu*: đóng project trong Cubase trước; bản hiện tại cũng được sao lưu thêm.
* Tham số: **KHÔI PHỤC** (về bản gốc) hoặc cấu hình tốt đã lưu.
* **Preset của app** (gán vai trò + hiệu chuẩn + cấu hình hát tốt): Nâng cao → 6 → *Xuất / Nhập cấu hình*.
  Mỗi lần bấm *Lưu cấu hình đang hát tốt* và trước mỗi lần nhập, app tự lưu một bản vào `backups\cau-hinh__*.json`.

## 5. Đã kiểm chứng gì

`python -m pytest -q tests` — 24 bài, đều đạt trên Linux và trên máy Windows của GitHub Actions
(kèm chạy thử giao diện từ mã nguồn và từ file `.exe` đã đóng gói). Nội dung kiểm thử:
dò tone trên hoà âm tổng hợp (G, Am, E), một nốt đơn **không** cho kết quả tin cậy, khoá tone,
YIN cao độ (sai < 0.15 cung), phân tích giọng, giao thức MIDI với Cubase giả lập (tên, giá trị,
tiếng Việt), ramp mượt và đơn điệu, hiệu chuẩn + fader không vượt ngưỡng, chặn khi chọn nhầm
track, áp phong cách/tone/nói chuyện rồi khôi phục đúng gốc, sao lưu–khôi phục project,
BPM và phát hiện tiếng đôi, delay theo nhịp, chống clip chỉ hạ và có giới hạn, cảnh báo mất tín hiệu,
điều kiện tự khôi phục, và **chạy thật script Cubase bằng Node** với API giả lập để kiểm tra
định dạng SysEx.

## 6. Chưa kiểm chứng / giới hạn còn lại

* Chưa chạy trên Windows + Cubase Pro 15 + iCON Cube2Nano thật. Cần chạy `kiem_tra_may.bat` và
  gửi lại `%APPDATA%\AILiveVocal\bao-cao-kiem-tra.txt`.
* Script cầu nối đã được đối chiếu với script mẫu chính thức của Steinberg (`steinbergmedia/midiremote-userscripts`)
  và một dự án cộng đồng lớn (`bjoluc/cubase-mcu-midiremote`): dạng callback, `sendMidi` gửi SysEx, binding
  Quick Control/Fader/Send đều khớp. Riêng việc *nhận* SysEx (`mOnSysex`) không có trong mã mẫu nào, nên
  ping/xin trạng thái chạy qua CC118/119 (chỉ dùng API đã xác nhận); SysEx chỉ là dự phòng. Nếu Cubase báo lỗi
  script (*MIDI Remote → Script Console*), đó là điểm cần sửa đầu tiên.
* Auto-Tune Artist phải cho phép tự động hoá *Key/Scale* qua Quick Control. Nếu không, lựa chọn:
  dùng tone hiển thị trong app để chỉnh tay 1 lần/bài, hoặc Antares Auto-Key (trả phí, ~49 USD).
* Không đọc được sample rate/buffer ASIO từ ngoài Cubase — xem Studio Setup (khuyến nghị 48 kHz,
  buffer 128–256). Độ trễ và tiếng rè phải đo trên máy thật.
* Mic phân tích qua WDM: một số driver không cho dùng song song với ASIO → tab Hát thử sẽ báo.
* Delay theo nhịp cần plugin delay cho điều khiển *Delay Time* theo ms qua Quick Control; nếu plugin chỉ có
  chế độ *Sync* theo tempo Cubase thì bật Sync và bỏ qua vai trò này.
* “Vang thông minh” do app điều khiển có trễ ~0,2–0,5 s. Cách chuẩn hơn (thời gian thực): sidechain
  compressor trên kênh vang, key từ kênh giọng — làm trong Cubase.
* Không cài đặt TikTok LIVE Studio thay bạn; app kiểm tra tín hiệu thực tế TikTok sẽ nhận và hướng dẫn.
* App không bao giờ tự bắt đầu phát LIVE.
