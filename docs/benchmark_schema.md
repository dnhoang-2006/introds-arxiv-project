# ĐỀ XUẤT HỢP ĐỒNG DỮ LIỆU: BENCHMARK LOG SCHEMA

> **Người đề xuất:** Anh Tuấn (MSSV 24120153 — Phụ trách Benchmark & Jupyter Book)  
> **Trạng thái:** Đề xuất mở (chờ Nhóm trưởng & thành viên duyệt trước khi gộp vào `docs/schema.md`)  
> **Mục tiêu:** Định dạng log chuẩn hóa để ghi nhận, tổng hợp và trực quan hóa hiệu năng của các module crawling, download, extract, và reference matching.

---

## 1. Mối quan hệ với `docs/schema.md` hiện tại

Hiện tại, `docs/schema.md` (Mục 5) định nghĩa 4 file log vi mô do từng thành viên tự ghi trong lúc chạy:
- `logs/discovery.csv` (Nhóm trưởng): đo thời gian phân giải metadata bài báo.
- `logs/download.csv` (Minh Thư): đo bytes và thời gian tải source archive.
- `logs/extract.csv` (Thanh Tú): đo dung lượng `bytes_before` và `bytes_after` sau khi lọc figure.
- `logs/references.csv` (Hữu Duy): đo số lượng reference và thời gian cào Semantic Scholar.

**Khác biệt & giá trị bổ sung của Benchmark Log:**
1. Các log trên là **log vi mô nội bộ** của từng script (chủ yếu là thời gian I/O và số lượng đối tượng).
2. `logs/benchmark_runs.csv` là **log đo lường tài nguyên cấp tiến trình/hệ thống (End-to-End Resource Benchmark)**:
   - Đo tổng thời gian thực tế (Wall-clock time) của toàn bộ tiến trình và tiến trình con.
   - Giám sát định kỳ bộ nhớ thực tế: **Peak RAM** và **Average RAM** của cả cây tiến trình.
   - Đo lường mức độ biến động dung lượng đĩa (**Disk Usage Delta**).
   - Ghi nhận trạng thái hoàn thành, exit code, và thông tin môi trường thực nghiệm (**Testbed**).
3. **Không làm thay đổi hoặc xung đột** với 4 file log hiện tại của nhóm. Thành viên không cần sửa đổi mã nguồn crawling của mình; công cụ `src/benchmark.py` đóng vai trò là wrapper bao quanh lệnh thực thi của từng thành viên.

---

## 2. Chi tiết Schema đề xuất (`logs/benchmark_runs.csv`)

File: `logs/benchmark_runs.csv` (hoặc `logs/benchmark_runs.json`)  
Encoding: `UTF-8`, có dòng header.

| Tên cột | Kiểu dữ liệu | Cho phép Null? | Đơn vị / Định dạng | Ví dụ | Giải thích mục đích |
|---|---|---|---|---|---|
| `run_id` | `string` | Không | UUID / timestamp | `run_20261025_011500_a1b2c3d4` | Khóa định danh duy nhất cho mỗi lần chạy benchmark. |
| `stage` | `string` | Không | Enum chuỗi | `discovery` | Giai đoạn thực thi: `discovery`, `download`, `extract`, `references`, `pipeline`, `test`. |
| `paper_id` | `string` | **Có** | Chuỗi arXiv ID | `2310.12345` | Mã bài báo được xử lý (nếu chạy cho từng bài) hoặc `all` / `null` nếu chạy theo mẻ. |
| `command` | `string` | Không | Chuỗi lệnh | `python src/discovery.py --ids 2310.12345` | Toàn bộ câu lệnh CLI đã được thực thi. |
| `started_at_utc` | `string` | Không | ISO 8601 UTC | `2026-10-24T18:15:00.123456+00:00` | Mốc thời gian bắt đầu tiến trình theo chuẩn UTC. |
| `ended_at_utc` | `string` | Không | ISO 8601 UTC | `2026-10-24T18:15:03.456789+00:00` | Mốc thời gian kết thúc tiến trình theo chuẩn UTC. |
| `exit_code` | `integer` | **Có** | Mã thoát hệ thống | `0` | Exit code trả về từ tiến trình (`0` là thành công, khác 0 là lỗi, `127` là không tìm thấy lệnh). |
| `status` | `string` | Không | Enum chuỗi | `success` | Trạng thái hoàn thành: `success`, `failed`, `timeout`, `error`. |
| `wall_time_seconds` | `float` | Không | Giây (`s`), 4 số thập phân | `3.3333` | Tổng thời gian wall-clock thực tế (tính bằng `time.perf_counter()`). |
| `peak_ram_mb` | `float` | **Có** | Megabytes (`MB`), 2 số thập phân | `45.80` | Lượng RAM (Resident Set Size - RSS) cao nhất đo được trên toàn bộ cây tiến trình (process tree). |
| `average_ram_mb` | `float` | **Có** | Megabytes (`MB`), 2 số thập phân | `38.25` | Lượng RAM trung bình qua các chu kỳ lấy mẫu. |
| `ram_sampling_interval_seconds` | `float` | Không | Giây (`s`) | `0.10` | Chu kỳ lấy mẫu RAM định kỳ của tiến trình giám sát. |
| `disk_usage_mb` | `float` | **Có** | Megabytes (`MB`), 4 số thập phân | `0.1843` | Độ biến thiên dung lượng đĩa (Delta = Sau - Trước) của phạm vi thư mục được cấu hình. |
| `disk_scope` | `string` | Không | Chuỗi mô tả phạm vi | `delta:corpus` | Mô tả phạm vi đo đĩa: `delta:<thư_mục>` hoặc `none` nếu không bật theo dõi đĩa. |
| `testbed` | `string` | Không | Chuỗi cấu hình hệ thống | `Windows-10-AMD64 (Python 3.11.0, RAM 16.0GB)` | Thông số môi trường phần cứng và hệ điều hành phục vụ khả năng tái lập thí nghiệm. |
| `tool_version` | `string` | Không | SemVer | `1.0.0` | Phiên bản của công cụ `benchmark.py`. |
| `notes` | `string` | **Có** | Chuỗi văn bản tự do | `Run with limit=5 on Colab` | Ghi chú thêm về tham số, lỗi ngoại lệ hoặc điều kiện thử nghiệm. |

---

## 3. Quy ước và nguyên tắc dữ liệu

1. **Chuẩn hóa Timestamp:**
   - Mọi mốc thời gian trong schema này dùng chuẩn **UTC (ISO 8601)** với hậu tố `+00:00` hoặc `Z`, đảm bảo so sánh nhất quán giữa các máy cá nhân và Google Colab.
2. **Xử lý tiến trình con (Process Tree):**
   - RAM được tính bằng tổng `RSS` của tiến trình cha và tất cả tiến trình con đang hoạt động tại thời điểm lấy mẫu thông qua `psutil`.
   - Nếu tiến trình chạy quá nhanh (< chu kỳ lấy mẫu), công cụ lấy mẫu ngay lập tức ở thời điểm khởi tạo để tránh mất dữ liệu.
3. **Phạm vi Disk Usage:**
   - Không đo dung lượng toàn bộ ổ cứng vật lý (tránh nhiễu từ OS/cache).
   - Đo dung lượng thư mục mục tiêu (ví dụ: `corpus/`, `downloads/`) tại 2 thời điểm: ngay trước khi chạy ($S_{\text{initial}}$) và ngay sau khi kết thúc ($S_{\text{final}}$).
   - $\text{disk\_usage\_mb} = \frac{S_{\text{final}} - S_{\text{initial}}}{1024 \times 1024}$.
4. **Tính toàn vẹn dữ liệu:**
   - Khi một tiến trình gặp lỗi hoặc timeout, exit code và trạng thái phải được ghi nhận trung thực; tuyệt đối không tạo số giả (fabrication).
   - Giá trị thiếu trong CSV được để trống `""`, trong JSON được biểu diễn bằng `null`. Không thay thế giá trị thiếu bằng số `0`.

---

## 4. Ví dụ bản ghi thực tế

### Dạng CSV (`logs/benchmark_runs.csv`):
```csv
run_id,stage,paper_id,command,started_at_utc,ended_at_utc,exit_code,status,wall_time_seconds,peak_ram_mb,average_ram_mb,ram_sampling_interval_seconds,disk_usage_mb,disk_scope,testbed,tool_version,notes
run_20261025_012015_e92bf18a,discovery,2310.12345,python src/discovery.py --ids 2310.12345,2026-10-24T18:20:15.102345+00:00,2026-10-24T18:20:18.452109+00:00,0,success,3.3498,42.15,36.40,0.1,0.0012,delta:corpus,Windows-10-AMD64 (Python 3.11.0, RAM 16.0GB),1.0.0,
run_20261025_012030_4a71cd90,download,2310.12345,python src/downloader.py --ids 2310.12345,2026-10-24T18:20:30.012300+00:00,2026-10-24T18:20:38.912400+00:00,0,success,8.9001,58.30,48.10,0.1,2.4510,delta:corpus,Windows-10-AMD64 (Python 3.11.0, RAM 16.0GB),1.0.0,
run_20261025_012050_9f81a7b2,discovery,invalid_id,python src/discovery.py --ids invalid_id,2026-10-24T18:20:50.111222+00:00,2026-10-24T18:20:51.222333+00:00,1,failed,1.1111,35.20,35.20,0.1,0.0,delta:corpus,Windows-10-AMD64 (Python 3.11.0, RAM 16.0GB),1.0.0,Paper not found
```

---

## 5. Các bước phối hợp đề xuất cho nhóm

1. **Bước 1 (Review & Duyệt):** Nhóm trưởng và các thành viên xem xét tên cột và đơn vị tại buổi họp tuần 1.
2. **Bước 2 (Chạy thử nghiệm):** Từng thành viên dùng `src/benchmark.py` bọc quanh lệnh chạy của mình trên dữ liệu mẫu `ids/example.txt` để kiểm tra khả năng tương thích.
3. **Bước 3 (Tổng hợp dữ liệu):** File `logs/benchmark_runs.csv` từ các máy thành viên được gom lại hoặc đưa vào repository phân tích (qua Google Drive / Git) để phục vụ cho `milestone1/02-statistics.ipynb`.
