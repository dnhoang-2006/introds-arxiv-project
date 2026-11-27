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

Không luật nào khớp → `groundtruth_arxiv_id: null`.

**Họ tác giả đầu + năm chỉ dùng để LỌC ỨNG VIÊN trước khi so tiêu đề, không tự
gán nhãn.** Sửa ngày 27/11 sau khi Hửu Duy đo trên 500 publication dải 24120177
(27.342 entry): bật luật này sinh thêm 1.160 nhãn, mà trong 730 nhãn so được tiêu
đề thì 638 nhãn (87%) có độ giống tiêu đề < 0,5. Chi tiết ở mục 9.

**So khớp tác giả gọi `clean.authors_match()`**, lọc ứng viên theo tác giả đầu gọi
`clean.first_author_matches()`. Đừng tự viết `set(a["author_keys"]) & set(b["author_keys"])`:
cách đó bỏ mất khoá phụ nên `Blümlein` (`bluemlein j`) không gặp `Blumlein`
(`blumlein j`) — xem mục 9.

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

### Vì sao bỏ luật "họ tác giả đầu + năm" khỏi matcher (27/11)

Hửu Duy đo trên 500 publication dải 24120177, 27.342 entry:

| | |
|---|---|
| Nhãn luật này sinh thêm | 1.160 |
| Trong 730 nhãn so được tiêu đề, số nhãn có độ giống < 0,5 | **638 (87%)** |
| Entry có ≥ 2 ứng viên cùng họ cùng năm | 216 |

Phản ví dụ: hai bài ATLAS khác nhau, cùng "ATLAS Collaboration", cùng năm.

Ba lý do, không chỉ một:

1. **87% là cận dưới.** 430 nhãn không so được tiêu đề vì một bên thiếu `title` —
   đúng loại entry dễ khớp bừa nhất, nên tỉ lệ thật có thể cao hơn.
2. **216 entry ≥ 2 ứng viên khiến luật không xác định**, không chỉ thiếu chính xác:
   nhãn phụ thuộc thứ tự duyệt, chạy máy khác ra khác. Trái với M3 câu 4 ý 4
   ("thuật toán mà nhóm định ra trước").
3. **Hỏng cả hai đầu.** Nhãn tự động phủ cả train lẫn test, nên 1.160 nhãn sai mỗi
   người (≈ 5.800 cả nhóm) vừa là đầu vào sai vừa là đáp án sai.

Bỏ luật này **không ảnh hưởng chỉ tiêu**: mục 4 đếm 500 *publication* gán tự động
mỗi người chứ không đếm 500 nhãn, và mục 2 đã chốt entry không khớp vẫn có dòng
với `null`. Kết quả chỉ là nhiều dòng `null` hơn.

### Chuẩn hoá tên tác giả: bốn lỗi đã vá ngày 27/11

Đo trên dải 24120053 — 1.390.019 chuỗi tác giả BibTeX, 1.352.172 chuỗi Semantic
Scholar, 217.892 khoá tác giả S2 khác nhau.

| lỗi | mức trước khi vá | cách vá |
|---|---|---|
| `\bibnamefont` bị đọc thành lệnh dấu `\b` | **76.387 (5,5%)** trên 277 publication | thêm chốt `(?![a-zA-Z])` cho lệnh dấu viết bằng chữ cái, `bib_dedup.py` |
| `et al.` nuốt họ tác giả | 8.081 (0,581%), gần như chỉ ở phía BibTeX | cắt đuôi `et al.` trước khi tách họ/tên |
| S2 ghi dấu sắc bằng nháy đơn trần (`Cr'epel`) | 3.891 | xoá nháy khi đứng trước chữ **thường** |
| Umlaut lệch hai phía (`Blümlein`/`Blumlein`) | 338 tên | thêm **khoá phụ**, giữ nguyên khoá chính |

Ba điểm cần nhớ khi đụng lại `src/matching/clean.py`:

- **Đừng xoá hết nháy đơn.** 2.935 chuỗi có nháy đơn là tên thật (`O'Brien`,
  `D'Agostino`); hai phía vốn đã ghi giống nhau nên xoá là phá chúng.
- **Đừng bỏ fold ae/oe/ue.** Đo trên 217.892 khoá S2: fold khớp 2.329 tên, chỉ bỏ
  dấu khớp 338. Fold vẫn là khoá chính, bỏ dấu chỉ là khoá phụ.
- **Nháy trong tiêu đề là sở hữu cách**, không phải dấu. Việc sửa nháy chỉ áp dụng
  cho tên tác giả, không áp dụng cho `clean_title`.

Hai điểm Hửu Duy soát lại ngày 27/11:

- **Thứ tự quan trọng.** `_QUOTE_ACCENT_RE` phải chạy khi chuỗi còn nguyên hoa
  thường. Dời xuống sau `.lower()` thì `O'Brien` đã thành `o'brien`, nháy đứng
  trước chữ thường nên bị xoá — đúng lỗi bản vá muốn tránh. Nhìn regex tưởng an
  toàn vì nó "chỉ xoá trước chữ thường", nên chỗ này rất dễ sai.
  `test_quote_accent_only_before_lowercase` chặn.
- **Thêm `Author.matches()` thôi chưa đủ**, chỗ gọi phải dùng nó. Vì vậy
  `clean.py` cung cấp sẵn `author_key_set()`, `authors_match()` và
  `first_author_matches()` — matcher gọi thẳng, không tự ghép khoá.

Ưu tiên theo số của Hửu Duy (đếm *cặp entry–reference thật sự trượt*, sát với MRR
hơn là đếm tên): umlaut chỉ chiếm ~10/70 cặp mất, nên là mục thấp nhất. Thứ tự
thi công: `\bibnamefont` → `et al.` → nháy đơn → umlaut.

Còn lại chưa xử lý:

- Nháy đơn đứng trước chữ **hoa** mà thật ra là dấu (`'Swierczewska` = `Świerczewska`)
  vẫn bị bỏ sót.
- 1.237 tên có umlaut không khớp được bằng cả hai dạng khoá.
- Tên viết họ trước không có dấu phẩy (`Nguyen Van An`, `Zhang Wei`) bị hiểu theo
  thứ tự phương Tây.

⚠️ Lỗi `\bibnamefont` nằm ở `src/parser/bib_dedup.py` nên **phải parse lại** mới
thấy kết quả. Ba lỗi còn lại ở `src/matching/clean.py`, chỉ ảnh hưởng lúc so khớp.
