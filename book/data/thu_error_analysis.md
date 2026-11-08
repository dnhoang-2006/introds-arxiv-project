# Phân loại lỗi tải xuống

**Phạm vi:** 5000 bài (2505.00666–2505.05665), 8066 version
**Nguồn:** `logs/download.csv` (8240 lượt tải, bao gồm các lượt retry)
**Trạng thái cuối theo version:** ok 7505 - empty 561 - fail thực sự 0 (tổng 8066)

> Ghi chú: 119 dòng `status=fail` trong log là tính **mọi lượt**, kể cả lỗi tạm thời đã được retry thành công.
> "23 version fail" trong task chính là 23 version `http_404` bên dưới.


## Bảng 1 — Version không có source (trạng thái cuối `empty`)

| Nguyên nhân | Số version | Số bài | Giải thích | Xử lý |
|---|---:|---:|---|---|
| `pdf_only` | 538 | 408 | arXiv trả về file PDF thay vì gói LaTeX: tác giả không nộp source | Ghi `_EMPTY.json`, không retry |
| `http_404` | 23 | 21 | Endpoint `/src/` trả 404 ở cả 2 lượt chạy | Ghi `_EMPTY.json`, không retry thêm |
| **Tổng** | **561** | | | |

## Bảng 2 — Lỗi tạm thời trong quá trình tải

| Loại lỗi | Số lượt | Số version | Số bài | Trạng thái cuối của các version đó | Nguyên nhân |
|---|---:|---:|---:|---|---|
| `incomplete_read` | 78 | 78 | 68 | 69 ok · 7 empty (pdf_only) · 2 fail ở dòng cuối nhưng corpus đã đầy đủ* | Kết nối bị ngắt khi đang nhận dữ liệu |
| `http_429` | 9 | 9 | 9 | 9 ok | arXiv giới hạn tần suất request (rate limit) |
| `ChunkedEncodingError` | 9 | 9 | 7 | 9 ok | Luồng dữ liệu chunked bị gián đoạn |
| `http_404` | 23 | 23 | 21 | 23 empty (xem Bảng 1) | Không có source |
| **Tổng** | **119** | | | | |

\* `2505.04594v2` và `2505.05209v4`: đã có lượt `ok` trước đó, một lượt chạy sau bị `incomplete_read`.
Corpus vẫn có đủ `.tex`/`.bib` nên được tính là **ok** (khớp `report.txt`).


## Ghi chú về http_404

- 23 version thuộc 21 bài, trong dải `2505.00885`–`2505.05579`.
- Mỗi version bị 404 ở **2 lượt chạy** (lượt đầu ghi `fail`, lượt chạy lại ngày 31/10 ghi `empty`).
- Trên đĩa có đúng 23 file `_EMPTY.json` với `reason: http_404`.
- **Giả thuyết (chưa kiểm chứng):** bài bị rút (withdrawn) hoặc source của version đó không được công bố.
  Đây là giới hạn phía arXiv, chạy lại không thay đổi kết quả.

## Tổng kết coverage

| Chỉ số | Giá trị |
|---|---|
| Tổng version | 8066 |
| Tải được source (ok) | 7505 (93,0%) |
| Không có source (pdf_only + http_404) | 561 (7,0%) |
| Còn fail thực sự | **0** |
| Version có kết quả rõ ràng | **8066/8066 (100%)**  |
