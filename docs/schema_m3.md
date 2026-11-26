# Schema Milestone 3 — Reference Matching

Chốt ngày 25/11. Mọi quy ước ở đây là **quyết định của nhóm**, không phải đề xuất.
Nguồn: đề `matching.md` và bảng hỏi đáp Milestone 3 của thầy.

---

## 1. Định dạng nhãn

Một dòng JSON mỗi nhãn, file `.jsonl`, mã hoá UTF-8 không BOM.

```json
{"arxiv_id": "2507.06659", "citation_key": "vaswani2017", "groundtruth_arxiv_id": "1706.03762", "labeler": "24120053", "method": "manual"}
```

| Trường | Kiểu | Ghi chú |
|---|---|---|
| `arxiv_id` | string | Publication chứa entry, **không kèm version** |
| `citation_key` | string | Khoá BibTeX, lấy đúng từ bảng `bibtex` của M2 |
| `groundtruth_arxiv_id` | string hoặc `null` | arXiv ID của reference đúng; `null` khi không khớp được |
| `labeler` | string | MSSV người gán |
| `method` | string | `manual` hoặc `auto` |

**Đường dẫn:**

- `labels/manual/<MSSV>.jsonl` — gán tay
- `labels/auto/<MSSV>.jsonl` — matcher tự động

---

## 2. `[QUYẾT ĐỊNH]` Entry không khớp vẫn có nhãn, giá trị `null`

Đề ghi ở phần Requirement: *"The table contains **one row per BibTeX entry** of each publication"*,
và `groundtruth_arxiv_id` là **nullable**.

Vậy publication nào đã chọn thì **mọi entry** của nó đều có một dòng. Entry không tìm
được reference tương ứng ghi `groundtruth_arxiv_id: null`, không bỏ dòng.

⚠️ Khác với cách đếm nhãn: khi kiểm chỉ tiêu *"ít nhất 20 nhãn mỗi publication gán tay"*
thì **chỉ đếm dòng có `groundtruth_arxiv_id` khác null**. Thầy chốt ở M3 câu 4 ý 1:
*"không tồn tại trường hợp entry đã gán nhãn nhưng không có references. Số nhãn bằng với
số cặp entry - references mà nhóm match được."*

---

## 3. `[QUYẾT ĐỊNH]` Tập Q khi tính MRR@5 loại entry `null`

Thầy chốt ở M3 câu 4 ý 2: *"entry không có reference không phải là một sample hợp lệ,
do đó không có trường hợp tính điểm cho các entry này. **Tập Q chỉ tính các nhãn matching**."*

```python
Q = [r for r in test_rows if r["groundtruth_arxiv_id"] is not None]
mrr = sum(1 / rank(r) if rank(r) else 0 for r in Q) / len(Q)
```

Entry `null` **vẫn có hàng** trong bảng `predictions` và **vẫn điền** `cand_1`…`cand_5`,
chỉ là không vào mẫu số.

Đây là chỗ dễ lệch số nhất giữa `match_main.py` và `validator_m3.py` — hai bên phải
dùng đúng định nghĩa này.

---

## 4. `[QUYẾT ĐỊNH]` Hai tập nhãn không giao nhau

Publication đã gán tay thì **không** đưa qua matcher tự động.
Thầy, M3 câu 4 ý 1: *"Paper nào đã dùng để gán nhãn thủ công thì không được đưa qua
pipeline gán nhãn tự động."*

**Số lượng, tính theo đầu người** (M3 câu 1 và câu 4 ý 5):

| | Mỗi người | Cả nhóm 5 người |
|---|---|---|
| Publication gán tay | 5 | 25 |
| Nhãn gán tay tối thiểu | 100 | 500 |
| Nhãn tối thiểu mỗi publication gán tay | 20 | — |
| Publication gán tự động | 500 | 2.500 |

Con số 500 là 10% của 5.000 bài mỗi người. Thầy: *"10% của mỗi thành viên 5000 thì 500,
10% của toàn nhóm 5000x5 là 2500 = 500x5."*

---

## 5. `[QUYẾT ĐỊNH]` Matcher tự động là luật, không phải model

Thầy, M3 câu 4 ý 4: *"Thuật toán matching dùng để gắn nhãn tự động là thuật toán mà nhóm
định ra trước, không phải mô hình matching mà nhóm huấn luyện."*

Lý do: nhãn tự động phủ cả train, val lẫn test. Nếu dùng model đã huấn luyện để sinh nhãn
thì nhãn train lấy đâu ra.

Thứ tự ưu tiên trong matcher, dừng ở luật đầu tiên khớp:

1. `doi` trùng
2. arXiv ID xuất hiện trong trường `url`
3. Độ tương đồng tiêu đề vượt ngưỡng
4. Họ tác giả đầu trùng **và** năm trùng

---

## 6. Chia tập

Thầy, M3 câu 4 ý 3: *"Việc chia tập được thực hiện trên toàn nhóm."*

| Tập | Gán tay | Tự động |
|---|---|---|
| Test | 5 publication | 5 publication |
| Validation | 5 publication | 5 publication |
| Train | 15 còn lại | 2.490 còn lại |

Nhóm chốt `partition` trước, mỗi người ghi đúng nhãn đó vào phần dữ liệu của mình.

---

## 7. Bảng `predictions`

Đúng 8 cột theo đề. Chỉ publication thuộc train/valid/test mới có hàng.

| Cột | Kiểu | Ghi chú |
|---|---|---|
| `arxiv_id` | string, không null | |
| `partition` | string | `train`, `valid`, `test` |
| `citation_key` | string, không null | |
| `groundtruth_arxiv_id` | string, nullable | |
| `cand_1` … `cand_5` | string, nullable | Xếp hạng giảm dần |

Candidate **phải nằm trong danh sách references của chính publication đó**
(M3 câu 4 ý 5). Dưới 5 candidate thì điền `null` vào ô thiếu.

---

## 8. External knowledge

Thầy, M3 câu 4 ý 6: gọi API ngoài, hoặc tải pretrained model về chạy, đều tính là
external knowledge — và **sinh viên dùng external bị chấm tách riêng**.

Nhóm chốt **không dùng external**:

- ✅ TF-IDF, Word2Vec, n-gram **tự huấn luyện trên corpus của nhóm**
- ✅ LightGBM, LogisticRegression, Random Forest — thư viện thuật toán
- ❌ Pretrained language model tải về
- ❌ Gọi API bên ngoài khi chạy

---

## 9. Giới hạn đã biết

Ghi vào đây để đưa lên poster, đừng giấu.

- **4 publication không parse được ở M2**: `2507.10483` là plain TeX không có
  `\documentclass` lẫn `\begin{document}`; `2507.08666`, `2507.08667`, `2507.09585`
  có `main.tex` thực chất là trang HTML.
- **449/4.996 publication không có entry BibTeX** sau khi khôi phục `.bbl` (9,0%,
  giảm từ 23,8%). Trong đó 76% vốn không có source TeX, 11% không có mục tham khảo,
  12% dùng `.bbl` sinh bởi biber với cú pháp `\entry` thay vì `\bibitem`.
- **Entry bóc từ `.bbl` kém chính xác hơn từ `.bib`**, vì `.bbl` là bản đã dàn trang,
  không còn cấu trúc trường. Trường `title` và `authors` dễ thiếu hoặc lẫn.
- **Bộ tách câu cắt nhầm** chữ ký tên tác giả (`J. A. Aguilar` thành ba câu) và hàng
  ma trận.
