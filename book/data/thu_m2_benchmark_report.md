# Benchmark parser Milestone 2 - Google Colab CPU-only

**Người đo:** Dương Ngọc Minh Thư
**Testbed:** Google Colab CPU-only, `Linux-6.6.159+-x86_64`, Python 3.13.18, RAM 12.7 GB
**Mẫu:** 50 publication đầu của `ids/24120144.txt` = 86 version (84 `ok`, 2 `empty`, 0 `fail`)
**Notebook:** `book/milestone2/colab_benchmark.ipynb`

## Bốn chỉ số bắt buộc (`--workers 1`)

| Chỉ số | Giá trị |
|---|---|
| Wall-clock toàn bộ parser | **27,52 s** |
| Thời gian trung bình mỗi publication | **0,55 s** |
| RAM tối đa | **35,69 MB** |
| Dung lượng output cuối | **13,92 MB** |

## So sánh song song

|  | `--workers 1` | `--workers 2` | Thay đổi |
|---|---|---|---|
| Wall-clock (s) | 27,52 | 23,01 | −16,4% |
| Trung bình mỗi publication (s) | 0,55 | 0,46 | −16,4% |
| RAM đỉnh (MB) | 35,69 | 84,59 | +137% |
| Dung lượng output (MB) | 13,92 | 13,92 | 0% |

## Kiểm định tính hợp lệ

- Wall-clock (27,52 s) **lớn hơn** tổng cột `seconds` của `parse.csv` (17,37 s) - phần chênh là khởi động tiến trình, import và I/O.
- Đủ 50/50 publication ở cả hai chế độ, không version nào `fail`.
- Output của hai chế độ giống hệt nhau (cùng 13,9157 MB, cùng số element từng version) - song song không làm sai kết quả.
- `run_id` do `benchmark.py` tự sinh; log gốc đầy đủ trong `thu_m2_benchmark_runs_raw.csv`.

## Ghi chú cho báo cáo

- **Song song chỉ nhanh 1,20×:** khoảng 10,2 s (37% wall-clock) là chi phí cố định không chia được cho worker; Colab chỉ có 2 vCPU dùng chung nên thời gian mỗi version tăng từ 0,20 s lên 0,30 s.
- **RAM tăng 2,4×** vì mỗi worker là một tiến trình Python riêng nạp lại thư viện. Ở quy mô này `--workers 1` là lựa chọn cân bằng hơn.
- **`peak_ram_source = sampling`** (không phải `getrusage`): `benchmark.py` lấy giá trị lớn hơn giữa hai cách đo; psutil cộng dồn cả cây tiến trình nên cao hơn. Đây là hành vi đúng, không phải lỗi.

## Tệp đi kèm (chép vào `book/data/`)

| Tệp | Nội dung |
|---|---|
| `thu_m2_benchmark_runs.csv` | 2 lần đo chính thức (workers 1 và 2) |
| `thu_m2_benchmark_runs_raw.csv` | Log gốc đầy đủ, gồm cả lần chạy thử 5 bài |
| `thu_m2_parse_w1.csv`, `thu_m2_parse_w2.csv` | `parse.csv` từng version của mỗi lần đo |
