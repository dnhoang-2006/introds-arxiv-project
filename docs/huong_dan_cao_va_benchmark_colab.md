# QUY TRÌNH CÀO DỮ LIỆU VÀ ĐO HIỆU NĂNG TRÊN GOOGLE COLAB

Tài liệu này hướng dẫn chi tiết từng bước để 5 thành viên trong nhóm thực hiện cào lại toàn bộ dữ liệu từ đầu và tự động đo đạc đầy đủ các thông số hiệu năng trên Google Colab CPU-only.

---

## 1. Nguyên tắc hoạt động và Phân công dải ID

Mỗi thành viên được phân công đúng 5.000 bài báo trong dải ID riêng biệt, lưu tại thư mục `ids/`. Do mỗi bài báo có thể có nhiều phiên bản (v1, v2, v3,...), tổng số phiên bản thực tế của mỗi người sẽ dao động từ 7.000 đến 8.500 bản.

| Thành viên | MSSV | Tệp danh sách ID | Vai trò chính trong đồ án |
| :--- | :---: | :--- | :--- |
| Đặng Ngọc Hoàng | 24120053 | `ids/24120053.txt` | Nhóm trưởng, Entry Discovery |
| Dương Ngọc Minh Thư | 24120144 | `ids/24120144.txt` | Source Download, Tối ưu I/O |
| Trần Ngọc Thanh Tú | 24120152 | `ids/24120152.txt` | Corpus Builder, Kiểm thử dữ liệu |
| Nguyễn Lê Anh Tuấn | 24120153 | `ids/24120153.txt` | Benchmark Tool, Jupyter Book |
| Cáp Hửu Duy | 24120177 | `ids/24120177.txt` | Semantic Scholar References |

Mọi câu lệnh cào đều được bao bọc bởi `src/benchmark.py`. Công cụ này chạy song song để đo 4 thông số:
- Thời gian chạy thực tế (Wall-clock time).
- Bộ nhớ RAM đỉnh (Peak RAM).
- Bộ nhớ RAM trung bình (Average RAM).
- Mức tăng dung lượng đĩa (Disk usage delta).

Kết quả đo đạc tài nguyên hệ thống sẽ tự động ghi nối tiếp vào tệp `logs/benchmark_runs.csv`. Đồng thời, các script cào vẫn tự động ghi nhật ký vi mô từng bài báo vào các tệp log riêng (`discovery.csv`, `download.csv`, `extract.csv`, `references.csv`).

---

## 2. Chuẩn bị môi trường trên Google Colab

Trước khi chạy các lệnh cào, mỗi thành viên mở một sổ tay Google Colab mới, chọn phần cứng **chỉ dùng CPU (CPU-only)** và thực hiện các ô lệnh chuẩn bị:

### Bước 2.1: Gắn kết Google Drive để chống mất dữ liệu
Do việc cào 5.000 bài qua mạng mất từ 6 đến 10 tiếng, nếu phiên Colab bị ngắt kết nối mà chưa lưu vào Drive thì toàn bộ tệp đã tải sẽ bị xóa sạch.

```python
from google.colab import drive
drive.mount('/content/drive')
```

Tạo một thư mục làm việc riêng trên Drive của bạn và di chuyển vào đó:

```bash
%cd /content/drive/MyDrive
!mkdir -p arxiv_project
%cd arxiv_project
```

### Bước 2.2: Tải mã nguồn nhóm và cài đặt thư viện

```bash
# Clone repo nếu chưa có, hoặc git pull nếu đã clone
!git clone https://github.com/<duong-dan-repo>/introds-arxiv-project.git .
# Hoặc nếu thư mục đã có sẵn code:
# !git pull origin feat/book

# Cài đặt đúng các thư viện bắt buộc
!pip install -r src/requirements.txt
```

Kiểm tra đảm bảo thư mục `logs`, `raw`, `corpus` đã sẵn sàng:
```bash
!mkdir -p logs raw corpus
```

---

## 3. Thứ tự 4 công đoạn thực thi

Quá trình cào phải tuân thủ đúng thứ tự phụ thuộc dữ liệu:
1. **Giai đoạn 1 (`discovery`)**: Quét thông tin 5.000 bài từ arXiv API, xác định danh sách các phiên bản thực tế của từng bài, tạo `paper_meta.json` trong `corpus/` và ghi nhật ký `logs/discovery.csv`.
2. **Giai đoạn 2 (`download`)**: Tải tệp nén mã nguồn `.tar.gz` của từng phiên bản về thư mục `raw/`, ghi nhật ký `logs/download.csv`.
3. **Giai đoạn 3 (`corpus_builder`)**: Giải nén các tệp nén từ `raw/` sang `corpus/`, loại bỏ tệp hình ảnh không cần thiết, ghi nhật ký `logs/extract.csv`.
4. **Giai đoạn 4 (`reference_builder`)**: Gọi API Semantic Scholar để lấy danh sách tài liệu tham khảo cho từng bài, lưu `references.json` và ghi nhật ký `logs/references.csv`.

*Lưu ý về tham số:*
- Luôn truyền `--interval 1.0` cho `benchmark.py` để lấy mẫu RAM định kỳ mỗi giây 1 lần, tránh lãng phí CPU cho phiên chạy dài.
- Nếu phiên chạy bị ngắt giữa chừng vì sự cố mạng, các script cào đều có cơ chế tự động bỏ qua các bài đã hoàn thành trước đó. Chỉ cần chạy lại đúng câu lệnh cũ, hệ thống sẽ tiếp tục cào từ bài đang dang dở mà không cào lại bài cũ.

---

## 4. Các câu lệnh thực thi chi tiết cho từng thành viên

Mỗi thành viên chỉ cần sao chép chính xác khối lệnh tương ứng với MSSV của mình vào Google Colab và bấm chạy tuần tự từ Giai đoạn 1 đến Giai đoạn 4.

---

### Dành cho Đặng Ngọc Hoàng (MSSV: 24120053)

```bash
# Giai đoạn 1: Discovery
!python src/benchmark.py --stage discovery --paper-id 24120053_full --interval 1.0 --csv logs/benchmark_runs.csv --disk-path corpus -- python src/discovery.py --ids ids/24120053.txt

# Giai đoạn 2: Download
!python src/benchmark.py --stage download --paper-id 24120053_full --interval 1.0 --csv logs/benchmark_runs.csv --disk-path raw -- python src/downloader.py --ids ids/24120053.txt

# Giai đoạn 3: Corpus Builder
!python src/benchmark.py --stage corpus_builder --paper-id 24120053_full --interval 1.0 --csv logs/benchmark_runs.csv --disk-path corpus -- python src/corpus_builder.py --ids ids/24120053.txt

# Giai đoạn 4: Reference Builder
!python src/benchmark.py --stage reference_builder --paper-id 24120053_full --interval 1.0 --csv logs/benchmark_runs.csv --disk-path corpus -- python src/reference_builder.py --ids ids/24120053.txt
```

---

### Dành cho Dương Ngọc Minh Thư (MSSV: 24120144)

```bash
# Giai đoạn 1: Discovery
!python src/benchmark.py --stage discovery --paper-id 24120144_full --interval 1.0 --csv logs/benchmark_runs.csv --disk-path corpus -- python src/discovery.py --ids ids/24120144.txt

# Giai đoạn 2: Download
!python src/benchmark.py --stage download --paper-id 24120144_full --interval 1.0 --csv logs/benchmark_runs.csv --disk-path raw -- python src/downloader.py --ids ids/24120144.txt

# Giai đoạn 3: Corpus Builder
!python src/benchmark.py --stage corpus_builder --paper-id 24120144_full --interval 1.0 --csv logs/benchmark_runs.csv --disk-path corpus -- python src/corpus_builder.py --ids ids/24120144.txt

# Giai đoạn 4: Reference Builder
!python src/benchmark.py --stage reference_builder --paper-id 24120144_full --interval 1.0 --csv logs/benchmark_runs.csv --disk-path corpus -- python src/reference_builder.py --ids ids/24120144.txt
```

---

### Dành cho Trần Ngọc Thanh Tú (MSSV: 24120152)

```bash
# Giai đoạn 1: Discovery
!python src/benchmark.py --stage discovery --paper-id 24120152_full --interval 1.0 --csv logs/benchmark_runs.csv --disk-path corpus -- python src/discovery.py --ids ids/24120152.txt

# Giai đoạn 2: Download
!python src/benchmark.py --stage download --paper-id 24120152_full --interval 1.0 --csv logs/benchmark_runs.csv --disk-path raw -- python src/downloader.py --ids ids/24120152.txt

# Giai đoạn 3: Corpus Builder
!python src/benchmark.py --stage corpus_builder --paper-id 24120152_full --interval 1.0 --csv logs/benchmark_runs.csv --disk-path corpus -- python src/corpus_builder.py --ids ids/24120152.txt

# Giai đoạn 4: Reference Builder
!python src/benchmark.py --stage reference_builder --paper-id 24120152_full --interval 1.0 --csv logs/benchmark_runs.csv --disk-path corpus -- python src/reference_builder.py --ids ids/24120152.txt
```

---

### Dành cho Nguyễn Lê Anh Tuấn (MSSV: 24120153)

```bash
# Giai đoạn 1: Discovery
!python src/benchmark.py --stage discovery --paper-id 24120153_full --interval 1.0 --csv logs/benchmark_runs.csv --disk-path corpus -- python src/discovery.py --ids ids/24120153.txt

# Giai đoạn 2: Download
!python src/benchmark.py --stage download --paper-id 24120153_full --interval 1.0 --csv logs/benchmark_runs.csv --disk-path raw -- python src/downloader.py --ids ids/24120153.txt

# Giai đoạn 3: Corpus Builder
!python src/benchmark.py --stage corpus_builder --paper-id 24120153_full --interval 1.0 --csv logs/benchmark_runs.csv --disk-path corpus -- python src/corpus_builder.py --ids ids/24120153.txt

# Giai đoạn 4: Reference Builder
!python src/benchmark.py --stage reference_builder --paper-id 24120153_full --interval 1.0 --csv logs/benchmark_runs.csv --disk-path corpus -- python src/reference_builder.py --ids ids/24120153.txt
```

---

### Dành cho Cáp Hửu Duy (MSSV: 24120177)

```bash
# Giai đoạn 1: Discovery
!python src/benchmark.py --stage discovery --paper-id 24120177_full --interval 1.0 --csv logs/benchmark_runs.csv --disk-path corpus -- python src/discovery.py --ids ids/24120177.txt

# Giai đoạn 2: Download
!python src/benchmark.py --stage download --paper-id 24120177_full --interval 1.0 --csv logs/benchmark_runs.csv --disk-path raw -- python src/downloader.py --ids ids/24120177.txt

# Giai đoạn 3: Corpus Builder
!python src/benchmark.py --stage corpus_builder --paper-id 24120177_full --interval 1.0 --csv logs/benchmark_runs.csv --disk-path corpus -- python src/corpus_builder.py --ids ids/24120177.txt

# Giai đoạn 4: Reference Builder
!python src/benchmark.py --stage reference_builder --paper-id 24120177_full --interval 1.0 --csv logs/benchmark_runs.csv --disk-path corpus -- python src/reference_builder.py --ids ids/24120177.txt
```

---

## 5. Kiểm tra và Thu thập kết quả sau khi hoàn thành

Khi cả 4 giai đoạn đã chạy xong, mỗi thành viên kiểm tra thư mục `logs/` trên Google Drive của mình. Một kết quả hợp lệ bắt buộc phải có đầy đủ 5 tệp:

1. `logs/discovery.csv`: Đủ 5.000 dòng ghi nhận kết quả tìm kiếm của 5.000 bài báo.
2. `logs/download.csv`: Ghi nhận toàn bộ các phiên bản đã tải về.
3. `logs/extract.csv`: Ghi nhận toàn bộ các phiên bản đã giải nén sang thư mục `corpus/`.
4. `logs/references.csv`: Ghi nhận dữ liệu tham chiếu từ Semantic Scholar.
5. `logs/benchmark_runs.csv`: Chứa đúng 4 dòng tương ứng với 4 giai đoạn (`discovery`, `download`, `corpus_builder`, `reference_builder`) kèm đầy đủ số liệu `wall_time_seconds`, `peak_ram_mb`, `average_ram_mb`, `disk_usage_mb` và định danh môi trường Colab CPU.

### Đóng gói nộp cho Nhóm trưởng:
Mỗi thành viên nén thư mục `logs/` và thư mục `corpus/` của mình thành tệp zip để gộp vào kho lưu trữ chung phục vụ biên dịch báo cáo và làm sạch ở Milestone 2:

```bash
!zip -r logs_<MSSV>.zip logs/
# Lưu ý kiểm tra dung lượng trước khi nén corpus
!zip -r corpus_<MSSV>.zip corpus/
```
