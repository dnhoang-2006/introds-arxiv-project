# Đồ án Nhập môn Khoa học Dữ liệu — arXiv Crawling & Matching

Repo mã nguồn dùng chung cho cả 3 milestone. Lịch sử commit được tích lũy xuyên suốt.

---

## 1. Yêu cầu môi trường

- **Python ≥ 3.10** (thư viện `arxiv` 4.x bắt buộc)
- Kết nối internet tới `export.arxiv.org` và `api.semanticscholar.org`

Kiểm tra phiên bản:

```bash
python --version          # phải là 3.10 trở lên
```

## 2. Cài đặt

### Dùng venv (khuyến nghị khi chạy máy cá nhân)

```bash
git clone <link-repo>
cd <ten-repo>

python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate

pip install -r src/requirements.txt
```

### Dùng conda

```bash
conda create -n introds python=3.11 -y
conda activate introds
pip install -r src/requirements.txt
```

### Chạy trên Google Colab (testbed chính thức của môn)

```python
!git clone <link-repo> && cd <ten-repo> && pip install -q -r src/requirements.txt
```

## 3. Cấu hình trước khi chạy

Mở `src/config.py`, sửa 2 dòng đầu cho đúng nhóm mình:

```python
GROUP_NAME    = "IntroDS-Group-04"
CONTACT_EMAIL = "24120053@student.hcmus.edu.vn"
```

Hai giá trị này ghép thành header `User-Agent`. arXiv yêu cầu User-Agent mô tả rõ
danh tính; để nguyên giá trị mặc định có thể bị chặn.

Đường dẫn ghi dữ liệu có thể đổi bằng biến môi trường (tiện khi chạy Colab, muốn ghi
thẳng lên Google Drive):

```bash
export CORPUS_ROOT=/content/drive/MyDrive/introds/corpus
export LOGS_ROOT=/content/drive/MyDrive/introds/logs
```

Bước crawl reference chạy được khi không có key nhưng dễ bị giới hạn tốc độ (HTTP 429).
Nên xin API key miễn phí của Semantic Scholar rồi đặt vào biến môi trường
(chỉ đặt trong phiên làm việc, **không commit key vào repo**):

```bash
export SEMANTIC_SCHOLAR_API_KEY=<key-cua-ban>       # Linux, macOS, Git Bash
$env:SEMANTIC_SCHOLAR_API_KEY = "<key-cua-ban>"     # Windows PowerShell
```

Trên Colab: `import os; os.environ["SEMANTIC_SCHOLAR_API_KEY"] = "<key-cua-ban>"`.

## 4. Chuẩn bị danh sách ID

Mỗi thành viên có khoảng ID riêng (cột H–K trên sheet đăng ký). Đặt file của mình
trong `ids/`, tên theo MSSV, một ID mỗi dòng:

```
ids/24120053.txt
```

```
2310.12345
2310.12346
# dòng bắt đầu bằng # là comment
hep-th/9901001
```

Không kèm hậu tố version — `discovery.py` sẽ tự xác định số version.

## 5. Chạy

### Bước 1 — Entry Discovery

```bash
# Chạy thử 5 ID đầu trước khi chạy full
python src/discovery.py --ids ids/24120053.txt --limit 5

# Chạy toàn bộ khoảng ID
python src/discovery.py --ids ids/24120053.txt

# Truyền thẳng vài ID để kiểm tra nhanh
python src/discovery.py --ids 1706.03762,2310.06825
```

Kết quả:
- `corpus/<pub_key>/paper_meta.json` cho mỗi bài
- `logs/discovery.csv` ghi lại mọi lần thử

Tùy chọn:

| Cờ | Tác dụng |
|---|---|
| `--limit N` | Chỉ xử lý N ID đầu |
| `--overwrite` | Ghi đè `paper_meta.json` đã có (mặc định bỏ qua) |
| `--quiet` | Không in từng dòng tiến trình |

### Bước 2 trở đi

| Bước | Lệnh | Người phụ trách |
|---|---|---|
| 2. Tải source mọi version | `python src/downloader.py --ids ids/<mssv>.txt` | Minh Thư |
| 3. Giải nén + dựng corpus | `python src/corpus_builder.py --ids ids/<mssv>.txt` | Thanh Tú |
| 4. Crawl reference | `python src/semantic_scholar.py --ids ids/<mssv>.txt` | Hữu Duy |
| 5. Đo hiệu năng | `python src/benchmark.py` | Anh Tuấn |
| 6. Chạy cả pipeline | `python src/main.py --ids ids/<mssv>.txt` | Nhóm trưởng (tuần 2) |

Corpus builder gọi extractor để tự tìm archive trong `raw/`, chỉ dựng các
version chưa có output, và ghi kết quả vào `logs/extract.csv`.

Có thể chạy thử một phần trước:

```bash
python src/corpus_builder.py --ids ids/<mssv>.txt --limit 5
```

Chạy lại lệnh không giải nén lại version đã dựng; dùng `--force` nếu cần dựng lại.

### Phần nâng cao A3 — so 3 nguồn metadata

Cần chạy discovery trước, vì nguồn API lấy từ `corpus/<pub_key>/paper_meta.json`.

```bash
# 1. Tải Cornell snapshot một lần (khoảng 1,9 GB, không cần tài khoản Kaggle)
mkdir -p data/kaggle_snapshot
curl -L -o data/kaggle_snapshot/arxiv.zip \
    https://www.kaggle.com/api/v1/datasets/download/Cornell-University/arxiv

# 2. Lọc snapshot theo ID được giao
python src/kaggle_loader.py --ids ids/<mssv>.txt

# 3. OAI-PMH: mẫu ngẫu nhiên để so sánh (500 ID, khoảng 25 phút)
python src/oai_harvester.py get --ids ids/<mssv>.txt --sample 500

# 4. So 3 nguồn, kết quả nằm trong reports/a3_*
python src/cross_validate.py --ids ids/<mssv>.txt --oai-sample 500 --recheck-api
```

Minh họa ListRecords và resumption token, phạm vi hẹp (tối đa 7 ngày, mặc định 5 trang):

```bash
python src/oai_harvester.py list --from 2008-11-26 --until 2008-11-26 \
    --set physics:hep-lat --max-pages 1 --probe-token
python src/oai_harvester.py list --from 2008-11-26 --until 2008-11-26 \
    --set physics:hep-lat --resume
python src/oai_harvester.py recheck-tokens   # chạy sau 00:00 UTC (07:00 giờ VN)
```

Kết quả và hành vi của endpoint: [`docs/a3_cross_validation.md`](docs/a3_cross_validation.md).

### Kiểm tra corpus (A2)

`src/validator.py` chạy 7 nhóm kiểm tra: đủ thư mục version, version có `.tex` hoặc
`_EMPTY.json` hợp lệ, không có file lạ, lệnh figure còn nguyên, đúng cấu trúc
`paper_meta.json` và `references.json`, ID không bị biến dạng.

```bash
python src/validator.py --ids-file ids/<mssv>.txt                 # kiểm tra cả bài còn thiếu
python src/validator.py --ids-file ids/<mssv>.txt --no-reextract  # không so với archive trong raw/, nhanh hơn
python src/validator.py --corpus corpus_a corpus_b --ids-dir ids  # gộp corpus của cả nhóm
```

Kết quả nằm trong `reports/validation.json`. Lệnh trả exit code 1 nếu có lỗi;
thêm `--strict` để tính cả cảnh báo là lỗi.

### Tiền xử lý TeX cho Milestone 2/3 (phần C)

`src/tex_prescan.py` tìm file gốc của từng version, liệt kê `\input` / `\include`,
đếm `\bibitem`, tỉ lệ version có `.bib` riêng và số reference có arXiv ID (matching pool M3).

```bash
python src/tex_prescan.py --ids ids/<mssv>.txt            # thêm --force để quét lại
```

Kết quả nằm trong `prescan.json` của từng bài và từng version, cùng bản tổng hợp
`reports/prescan_summary.json`.

### Chạy test

```bash
pip install pytest
python -m pytest tests -q
```

## 6. Ước lượng thời gian chạy

arXiv yêu cầu chờ **≥ 3 giây** giữa 2 request và chỉ 1 connection tại một thời điểm.
Semantic Scholar giới hạn **1 request/giây**. Đây là ràng buộc cứng, không được phá.

Với N bài, mỗi bài trung bình V version:

| Bước | Số request | Thời gian tối thiểu |
|---|---|---|
| Discovery | N | N × 3 giây |
| Download | N × V | N × V × 3 giây |
| References | N | N × 1 giây |

Ví dụ 200 bài, trung bình 2 version: discovery 10 phút, download 40 phút,
reference 4 phút. **Cộng thêm thời gian retry — hãy bắt đầu sớm.**

## 7. Hợp đồng dữ liệu

Định dạng thư mục, tên file, tên cột và quy ước log được chốt trong
[`docs/schema.md`](docs/schema.md). Mọi module đọc/ghi theo đúng file đó.
Muốn đổi một trường → mở issue, cả nhóm duyệt, rồi mới sửa.

## 8. Cấu trúc repo

```
├── README.md                 # file này
├── .gitignore
├── docs/
│   ├── schema.md             # HỢP ĐỒNG DỮ LIỆU — đọc trước khi code
│   └── a3_cross_validation.md  # A3: kết quả so 3 nguồn, hành vi OAI-PMH
├── ids/                      # danh sách ID của từng người (được commit)
├── tests/                    # test tự động (pytest)
└── src/
    ├── requirements.txt
    ├── config.py             # hằng số + tiện ích dùng chung
    ├── http_utils.py         # tiện ích gọi HTTP dùng chung
    ├── discovery.py          # bước 1
    ├── downloader.py         # bước 2
    ├── extractor.py          # bước 3
    ├── corpus_builder.py     # bước 3
    ├── semantic_scholar.py   # bước 4
    ├── reference_builder.py  # bước 4
    ├── benchmark.py          # đo hiệu năng
    ├── main.py               # orchestrator (tuần 2)
    ├── validator.py          # A2: kiểm tra corpus
    ├── tex_prescan.py        # C: tiền xử lý TeX
    ├── oai_harvester.py      # A3: OAI-PMH
    ├── kaggle_loader.py      # A3: Cornell snapshot
    └── cross_validate.py     # A3: so 3 nguồn
```

Thư mục sinh ra lúc chạy (**không commit**): `corpus/`, `logs/`, `reports/`, `data/`

## 9. Quy ước làm việc chung

- Mỗi người làm trên nhánh riêng `feat/<ten-module>`, mở PR vào `main`.
- Nhóm trưởng review và merge. Không push thẳng vào `main`.
- Commit message tiếng Việt hoặc tiếng Anh đều được, nhưng phải mô tả được việc đã làm.
- **Trước mỗi lần commit, chạy `git status` và xác nhận không có file `.tex`,
  `.tar.gz` hay thư mục `corpus/` nào lọt vào.**

---

## Thành viên

| MSSV | Họ tên | Module lõi | Nhóm việc nâng cao |
|---|---|---|---|
| 24120053 | Đặng Ngọc Hoàng (nhóm trưởng) | Entry Discovery + Tích hợp | A3 — OAI-PMH + Kaggle Cross-Validation |
| 24120144 | Dương Ngọc Minh Thư | Full-text Source Download | A1 — Tối ưu hiệu năng |
| 24120152 | Trần Ngọc Thanh Tú | Extract + Corpus Builder | A2 — Data Validation Suite |
| 24120177 | Cáp Hửu Duy | Semantic Scholar References | C — Tiền xử lý bắc cầu M2/M3 |
| 24120153 | Nguyễn Lê Anh Tuấn | Benchmark + Jupyter Book | B — Phân tích mở rộng |
