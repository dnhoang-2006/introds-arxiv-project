1. Đặng Ngọc Hoàng
> **Phần việc lớn nhất của M2.** Nhận đường biên dịch từ Minh Thư, nội dung đã chuẩn hoá từ Thanh Tú, dựng thành cây và sinh hai bảng `elements` + `hierarchy`.
> 

## File làm việc

`src/parser/hierarchy.py` · `src/parser/elements.py` · `src/parse_main.py`

## A. Tự xác định cấp độ — không được hardcode

Đề ghi rõ: *"Since the exact nesting order depends on the publication's specific formatting, the parser is required to **automatically identify** the appropriate hierarchical level for each such element."*

Nghĩa là không được giả định `section` luôn là cấp 1. Bài dùng `book` class có `\chapter` ở trên `\section`; bài dùng `article` thì không. Cách làm: **suy cấp độ từ thứ tự xuất hiện lần đầu** trong chính tài liệu đó.

```python
import re

SECTION_CMD = re.compile(r"\\(chapter|section|subsection|subsubsection|paragraph|subparagraph)\*?\s*\{")

def infer_levels(tex: str) -> dict[str, int]:
    """Gán cấp độ theo thứ tự lần đầu mỗi lệnh xuất hiện trong tài liệu này."""
    order, seen = [], set()
    for m in SECTION_CMD.finditer(tex):
        cmd = m.group(1)
        if cmd not in seen:
            seen.add(cmd); order.append(cmd)
    return {cmd: i + 1 for i, cmd in enumerate(order)}
```

⚠️ Dấu `*` phải bắt được. Đề ghi: *"Acknowledgements and Appendices, often unnumbered through the `\section*` form, **must** be included."*

## B. Loại trừ phần References

Đề: *"References sections should **not** be parsed into the hierarchy."*

Cắt bỏ trước khi dựng cây:

```python
STOP = re.compile(
    r"\\begin\{thebibliography\}|\\bibliography\s*\{|"
    r"\\(?:section|chapter)\*?\s*\{\s*(?:References|Bibliography|Tài liệu tham khảo)\s*\}",
    re.IGNORECASE)

def strip_references(tex: str) -> str:
    m = STOP.search(tex)
    return tex[:m.start()] if m else tex
```

⚠️ Cẩn thận: **Appendix thường nằm SAU** References trong một số bài. Cắt thẳng từ References trở đi sẽ mất luôn Appendix — mà đề bắt phải giữ. Xử: cắt đoạn từ References đến `\end{thebibliography}` hoặc đến lệnh section tiếp theo, rồi **nối lại phần sau**.

## C. Tách câu — chỗ dễ sai nhất

Đề: *"do not split inside mathematics, commands, abbreviations such as i.e. and et al. and Fig. 1, URLs, or decimal numbers, since a dot that does not end a sentence does not create a new leaf."*

Cách an toàn: **che trước, tách sau, bỏ che**.

```python
PROTECT = [
    (re.compile(r"\$[^$]+\$"),                      "MATH"),   # toán inline
    (re.compile(r"https?://\S+"),                   "URL"),
    (re.compile(r"\b\d+\.\d+\b"),                   "NUM"),    # số thập phân
    (re.compile(r"\b(?:i\.e|e\.g|et al|cf|vs|resp|approx|Fig|Eq|Sec|Tab|Ref|No|Dr|Prof|Mr|Ms|St|al)\.",
                re.I),                              "ABBR"),
]

def split_sentences(text: str) -> list[str]:
    store = []
    def mask(m):
        store.append(m.group(0))
        return f"\x00{len(store)-1}\x00"
    for pat, _ in PROTECT:
        text = pat.sub(mask, text)

    parts = re.split(r"(?<=[.!?])\s+(?=[A-Z\\(])", text)

    out = []
    for p in parts:
        p = re.sub(r"\x00(\d+)\x00", lambda m: store[int(m.group(1))], p).strip()
        if p:
            out.append(p)
    return out
```

Kiểm bằng ca thật: `"We use BERT (Devlin et al. 2019). The result is 3.14 times better. See Fig. 2 for details."` phải ra **đúng 3 câu**, không phải 6.

## D. Itemize tách thành cấp con

Đề: *"a block of `\begin{itemize}...\end{itemize}` is considered as a higher component with each point being a next-level element."*

Nên: node `kind="itemize"` làm cha, mỗi `\item` là con `kind="item"`. Nội dung dài trong một `\item` thì tách câu tiếp thành cháu.

## E. Kho element dùng chung — dedup tự động

Đây là chỗ phần `element_id` băm nội dung ở `docs/schema_m2.md` phát huy tác dụng. **Không cần bước so khớp riêng** — cùng nội dung đã chuẩn hoá thì tự ra cùng id:

```python
def build_store(pub_key, versions: dict[int, list[Node]]):
    elements, hierarchy = {}, []
    for v, nodes in versions.items():
        for n in nodes:
            eid = element_uid(pub_key, n.kind, n.clean_content)
            elements[eid] = {"element_id": eid, "arxiv_id": pub_key_to_id(pub_key),
                             "kind": n.kind, "content": n.clean_content}   # ghi đè = dedup
            if n.parent is not None:
                hierarchy.append({"arxiv_id": ..., "version": v,
                                  "element_id": eid, "parent_id": n.parent_eid})
    return list(elements.values()), hierarchy
```

Đề có ví dụ mẫu: câu `s1` xuất hiện ở cả v1 và v2 thì **chỉ 1 dòng trong `elements`**, nhưng **2 dòng trong `hierarchy`** (v1 gắn vào `h1`, v2 gắn vào `h2`). Kiểm lại bảng ví dụ trong trang `parsing` cho chắc.

## F. Orchestrator `src/parse_main.py`

Ghép 4 module lại, chạy được bằng một lệnh, có `--ids` và `--limit` giống các script M1:

```bash
python src/parse_main.py --ids ids/24120053.txt --limit 20
```

Ghi `logs/parse.csv` theo đúng định dạng đã chốt ở tuần 1.

## Checklist

- [ ]  Cây có đúng 1 root mỗi version, không node mồ côi
- [ ]  Ca thử `Fig. 2` / `et al.` / `3.14` không bị tách nhầm
- [ ]  Appendix sau References vẫn được giữ
- [ ]  Version rỗng vẫn có dòng ghi nhận, không bị nhảy cóc
- [ ]  Chạy thử 20 bài có nhiều version, kiểm `elements` < tổng số node (chứng tỏ dedup có chạy)

---

## ✅ Quy ước đã chốt — thứ tự pipeline với phần của Hữu Duy

> Ghi giống hệt trong thẻ Tuần 2 của Hửu Duy. Đây là quyết định, không phải đề xuất để bàn.
> 

### Vì sao cần quy ước này

Hai câu giống hệt nhau ở v1 và v2, nhưng v1 viết `\cite{vaswani2017}` còn v2 viết `\cite{vit_transformer}` (cùng trỏ một tài liệu), sẽ băm ra **hai `element_id` khác nhau** → dedup nội dung thất bại ngay ở đúng loại câu phổ biến nhất trong bài báo. Nên `\cite` phải được đổi về key chuẩn **trước khi** băm.

### Thứ tự bắt buộc, cho mỗi publication

| Bước | Ai | Làm gì |
| --- | --- | --- |
| 1 | Minh Thư | `gather(vdir)` → đường biên dịch của từng version |
| 2 | Thanh Tú | `clean_latex()` rồi `normalize_math()` trên toàn văn từng version |
| 3 | Hửu Duy, lượt 1 | Đọc bib của **tất cả** version → dựng `rename_map` |
| 4 | Hửu Duy, lượt 2 | `rename_cites()` trên văn bản đã chuẩn hoá |
| 5 | **Ngọc Hoàng** | Dựng cây và băm `element_uid()` **trên văn bản ra từ bước 4** |

Phải **hai lượt** vì `rename_map` chỉ dựng được sau khi đã đọc hết mọi version của bài đó.

### Code trong `src/parse_main.py` — viết đúng như sau

```python
from parser.normalize import clean_latex, normalize_math
from parser.bib_dedup import unify_publication
from parser.elements import build_store

norm_text   = {v: normalize_math(clean_latex(read_version(v))) for v in versions}
bib_entries = {v: collect_bib(v) for v in versions}

# Duy trả về văn bản đã đổi \cite + bảng bibtex đã gộp
renamed_text, bibtex_rows, rename_map = unify_publication(norm_text, bib_entries)

# CHỈ băm ở đây. Không băm norm_text.
elements, hierarchy = build_store(pub_key, renamed_text)
```

⚠️ Lỗi dễ mắc nhất: băm nhầm `norm_text` thay vì `renamed_text`. Hai biến chỉ khác nhau ở citation key nên chạy vẫn trơn, không báo lỗi gì — chỉ là tỉ lệ dedup thấp bất thường. Nếu thấy `dedup_ratio` gần 0 ở những bài nhiều version thì kiểm ngay dòng này đầu tiên.

### Hai quy tắc ảnh hưởng tới phần băm của Hoàng

**1. Key trong `\cite{}` nhiều key được sort.** `\cite{b,a}` và `\cite{a,b}` sau bước 4 đều thành `\cite{a,b}`. Hoàng không phải làm gì thêm, nhưng cần biết để không ngạc nhiên khi `content` khác bản gốc.

**2. `content` lưu bản đã đổi tên.** Cột `content` trong bảng `elements` phải là văn bản **sau bước 4**, cùng chính xác với chuỗi đã đem đi băm. Lưu bản gốc mà băm bản đổi tên là không nhất quán, và validation suite của Thanh Tú có phép kiểm bắt đúng lỗi này.

### Việc duy nhất cần trao đổi với Duy

Không phải thống nhất quy ước nữa, chỉ là **chốt ngày Duy giao hàm `unify_publication()`**. Hoàng cần nó để chạy `parse_main.py` đầu-cuối. Đề nghị: Duy đẩy bản chạy được (dù regex chưa hoàn hảo) **chậm nhất 19/11**, để Hoàng còn 3 ngày ghép và chạy thử trước 22/11.

---

## 🔁 Đã chuyển bớt sang Tuần 1

Tuần 2 chỉ còn **15→20/11 (6 ngày)** và là tuần ghép 4 module, nên ba hàm thuần tuý dưới đây đã dời lên Tuần 1:

- `infer_levels()` — suy cấp độ section · hạn 10/11
- `strip_references()` — cắt References, giữ Appendix · hạn 11/11
- `split_sentences()` — tách câu có che toán/URL/viết tắt · hạn 13/11

Mục A, B, C phía trên **vẫn giữ nguyên để tham khảo code mẫu**, nhưng việc viết chúng nằm ở thẻ Tuần 1.

### Tuần 2 chỉ còn ba việc

1. `build_store()` + `element_uid()` — kho element dùng chung, dedup tự động (mục E)
2. Ghép `src/parse_main.py` theo đúng thứ tự đã chốt ở mục "Quy ước đã chốt"
3. Chạy thật, kiểm `dedup_ratio` khác 0 ở bài nhiều version

Cộng thêm cơ chế **resumable** đã mô tả ở thẻ Tuần 1 — nếu tuần 1 chưa kịp thì làm ở đây, nó sẽ cứu Hoàng nếu lần chạy đầu đứt giữa chừng.

**Mốc cứng:** Duy giao `unify_publication()` chậm nhất **19/11**, Hoàng chạy xong và giao số cho Tuấn trước **20/11**."}

---

## 📅 Lịch chốt — Tuần 2 (15→20/11)

> **Thay cho mọi mốc ngày ghi phía trên trong thẻ này.** Chỗ nào ở trên còn ghi "Duy giao chậm nhất 19/11" là bản cũ — đã đổi thành **17/11**.
> 

| Hạn | Việc |
| --- | --- |
| **16/11 T2** | `build_store()`  • `element_uid()` |
| **17/11 T3** | Ghép `src/parse_main.py`, chạy `--limit 20` sạch · nhận `unify_publication()` từ Duy |
| **18/11 T4** | 🔴 **Chạy full và giao `parse.csv`  • `elements`/`hierarchy` cho Tuấn** |
| **19/11 T5** | Kiểm `dedup_ratio`, sửa nếu bất thường |
| **20/11 T6** | Rà soát cuối, nộp Moodle |

⚠️ **18/11 là mốc cứng của cả nhóm**, không phải 20/11. Tuấn kết thúc 19/11 nên phải nhận số chậm nhất 18/11. Nếu hết ngày 17/11 mà `--limit 20` chưa chạy sạch thì báo nhóm ngay để cắt phạm vi — thà parse 5.000 bài đúng hạn còn hơn 25.000 bài trễ."}


2. Dương Ngọc Minh Thư
> **Phần việc:** đo hiệu năng parser đúng chuẩn đề, trên Colab CPU-only. Thư là người duy nhất trong nhóm đã có phép đo thật ở M1 (`thu_runs.csv`), nên phần này giao cho Thư.
> 

## Đề yêu cầu đúng 4 con số

> "running time counts the **end-to-end wall time of the parser** and the **average time to process one publication**, while memory footprint counts the **maximum RAM used** and the **final output's storage size**. The testbed for the final benchmarking is a **Google Colab instance running on CPU-only mode**."
> 

Gọn hơn M1 nhiều — M1 đòi 7 con số, M2 chỉ đòi 4.

## ⚠️ Bài học từ M1 — đọc trước khi làm

Ở M1, 4 dòng "Colab" trong `benchmark_runs.csv` có `wall_time_seconds` **khớp đúng 1,00×** tổng cột `seconds` của log, và RAM đỉnh trùng tới hàng phần trăm với dòng Windows. Nhóm đang phải xử lại.

Wall-clock thật **luôn lớn hơn** tổng thời gian từng item, vì còn khởi động process, I/O, ghi đĩa. Nếu hai số đó bằng nhau thì chắc chắn có chỗ sai. Thư chạy thật là không dính vấn đề này.

## Cách làm

Mở Colab, `Runtime → Change runtime type → CPU`. Parser cần corpus `.tex`, mà corpus nằm trên máy cá nhân — nên phải tải một mẫu nhỏ lên Colab trước:

```python
# 1. Lấy code
!git clone https://github.com/dnhoang-2006/introds-arxiv-project.git
%cd introds-arxiv-project
!pip install -q -r src/requirements.txt

# 2. Tải mẫu corpus lên (nén 50 bài trên máy rồi upload, hoặc mount Drive)
from google.colab import files
files.upload()        # corpus_sample.zip
!unzip -q corpus_sample.zip -d .

# 3. Đo thật
!python src/benchmark.py --stage parse --disk-path parsed \
    --notes "Colab CPU-only, 50 publications" \
    -- python src/parse_main.py --ids ids/24120144.txt --limit 50

!cat logs/benchmark_runs.csv | tail -2
```

⚠️ `benchmark.py` là wrapper — câu lệnh cần đo đặt **sau dấu `--`**, không truyền `--ids` trực tiếp cho nó. Cú pháp trên đã được kiểm chứng.

**Cách nén mẫu trên máy:**

```bash
cd introds-arxiv-project
python -c "
import shutil, itertools, pathlib
src = pathlib.Path('corpus')
dst = pathlib.Path('corpus_sample/corpus'); dst.mkdir(parents=True, exist_ok=True)
for p in itertools.islice(sorted(src.iterdir()), 50):
    shutil.copytree(p, dst / p.name, dirs_exist_ok=True)
shutil.make_archive('corpus_sample', 'zip', 'corpus_sample')
print('xong')"
```

50 bài chỉ khoảng 12 MB sau khi đã bỏ figure ở M1 — upload nhanh.

## Bốn con số cần nộp cho Tuấn

| Chỉ số | Lấy từ đâu |
| --- | --- |
| Wall-clock toàn bộ parser | cột `wall_time_seconds` |
| Thời gian TB mỗi publication | `wall_time_seconds / 50` |
| RAM tối đa | cột `peak_ram_mb`, nguồn `getrusage` trên Linux |
| Dung lượng output cuối | cột `disk_usage_mb` với `--disk-path parsed` |

Ghi rõ **cỡ mẫu 50 bài** trong cột `notes`, để Tuấn viết đúng trong báo cáo. Đề ghi *"No upper limit on the running time is enforced"* nên không bắt buộc chạy cả 5.000 bài.

## Checklist

- [ ]  `run_id` có hash ngẫu nhiên do `benchmark.py` tự sinh, không gõ tay
- [ ]  `testbed` ghi đúng chuỗi Colab mà script tự nhận diện
- [ ]  `peak_ram_source` = `getrusage` (tự có trên Linux/Colab)
- [ ]  `wall_time_seconds` **lớn hơn** tổng cột `seconds` trong `logs/parse.csv`
- [ ]  Giữ lại file `logs/benchmark_runs.csv` gốc xuất từ Colab để đối chiếu

---

## 🔁 Đã chuyển bớt sang Tuần 1

Tuần 2 chỉ còn **15→19/11 (5 ngày)**, và phần của Thư phụ thuộc vào việc Hoàng ghép xong `parse_main.py`. Nên hai việc chuẩn bị đã dời lên Tuần 1:

- Nén `corpus_sample.zip` 50 bài (ưu tiên bài nhiều version) · hạn 12/11
- Dựng sẵn notebook `book/milestone2/colab_benchmark.ipynb`, chạy thử tới bước `pip install` · hạn 13/11

### Tuần 2 chỉ còn

Tải mẫu lên Colab, bấm chạy, chép 4 con số gửi Tuấn. Nửa ngày.

### Và phần điểm cộng: đo song song

Cơ chế `--workers N` viết ở Tuần 1. Tuần 2 chạy **hai lần** — `--workers 1` rồi `--workers 2` — để có bảng so sánh:

|  | `--workers 1` | `--workers 2` | Thay đổi |
| --- | --- | --- | --- |
| Wall-clock (s) | ? | ? | ? |
| TB mỗi publication (s) | ? | ? | ? |
| RAM đỉnh (MB) | ? | ? | ? |

Hai lần chạy 50 bài trên Colab tổng cộng chưa tới 20 phút, nên vẫn nhẹ. Nếu Hoàng giao `parse_main.py` muộn thì **bỏ phần song song trước**, giữ phép đo `--workers 1` — đó mới là con số đề bắt buộc."}

---

## 📅 Lịch chốt — Tuần 2 (15→19/11)

> **Thay cho mọi mốc ngày ghi phía trên trong thẻ này.**
> 

| Hạn | Việc | Chờ ai |
| --- | --- | --- |
| **16/11 T2** | Tải `corpus_sample.zip` lên Colab, chạy thử `--limit 5` cho chắc môi trường | — |
| **18/11 T4** | 🔴 Chạy `--workers 1` rồi `--workers 2`, **gửi 4 chỉ số + bảng so sánh cho Tuấn** | Hoàng giao `parse_main.py` 17/11 |
| **19/11 T5** | Dự phòng nếu Hoàng giao muộn | — |

⚠️ Nếu sáng 18/11 vẫn chưa có `parse_main.py` chạy được: **bỏ `--workers 2`, chỉ chạy `--workers 1`**. Bốn chỉ số của `--workers 1` là phần đề bắt buộc; bảng song song là điểm cộng, bỏ được mà không mất điểm nào."}


3. Trần Ngọc Thanh Tú
> **Phần việc:** kiểm tính đúng đắn của toàn bộ đầu ra M2, giống vai trò `validator.py` Tú đã làm ở M1 (phần A2). Lần này kiểm cấu trúc cây thay vì kiểm file.
> 

## Vì sao cần

`hierarchy` là danh sách cạnh node→cha. Một bug nhỏ trong `hierarchy.py` có thể sinh ra node mồ côi, vòng lặp cha-con, hoặc hai root trong một version — mà **không báo lỗi gì cả**. Đến lúc Tuấn vẽ biểu đồ mới phát hiện thì đã sát hạn. Đúng kiểu lỗi mà M1 đã dính một lần.

## File làm việc: `src/validator_m2.py`

Dùng lại khung CLI của `src/validator.py` — đã có `--ids`, `--out`, `--strict`, exit code. Chỉ thay phần kiểm tra.

## Sáu phép kiểm bắt buộc

**1. Cây hợp lệ — mỗi version đúng một root**

```python
for (aid, v), edges in hierarchy.groupby(["arxiv_id", "version"]):
    children = set(edges.element_id)
    parents  = set(edges.parent_id)
    roots = parents - children
    assert len(roots) == 1, f"{aid} v{v}: có {len(roots)} root, phải là 1"
```

**2. Không có node mồ côi** — mọi `parent_id` phải tồn tại trong bảng `elements`:

```python
missing = set(hierarchy.parent_id) - set(elements.element_id)
assert not missing, f"{len(missing)} parent_id không có trong elements"
```

**3. Không có vòng lặp** — đi ngược lên cha, phải tới root trong hữu hạn bước.

**4. `element_id` duy nhất trong `elements`** — bảng này là kho dùng chung, trùng id là sai:

```python
assert elements.element_id.is_unique
```

**5. Dedup thực sự có chạy** — phép kiểm quan trọng nhất. Với bài có nhiều version, số element duy nhất phải **nhỏ hơn** tổng số node của mọi version:

```python
for aid, grp in hierarchy.groupby("arxiv_id"):
    if grp.version.nunique() > 1:
        n_nodes  = len(grp)
        n_unique = grp.element_id.nunique()
        ratio = 1 - n_unique / n_nodes
        # bài nhiều version mà ratio = 0 → dedup không chạy, rất đáng ngờ
```

In ra phân bố `ratio` — số này chính là thống kê *"element counts before and after deduplication"* mà đề đòi, nên gửi luôn cho Tuấn.

**6. Phủ đủ version** — đề ghi *"record the version as empty rather than skipping it"*. Đối chiếu với `discovery.csv` của M1:

```python
# mỗi (arxiv_id, version) trong discovery phải xuất hiện ở parse.csv, kể cả status=empty
```

## Đầu ra

`reports/validation_m2.json`, cấu trúc giống `validation.json` của M1 để Tuấn tái dùng code đọc:

```json
{
  "n_publications": 5000,
  "n_versions": 8066,
  "checks": {"single_root": "pass", "no_orphan": "pass", "no_cycle": "pass",
              "unique_element_id": "pass", "dedup_effective": "pass", "version_coverage": "pass"},
  "dedup_ratio": {"mean": 0.0, "median": 0.0, "max": 0.0},
  "failures": []
}
```

## Lưu ý từ lần trước

Ở M1 có lần commit xóa `src/validator.py` trong khi vẫn thêm test cho nó, gây `ModuleNotFoundError`. Lần này trước khi push chạy:

```bash
python -m pytest tests/ -q && python src/validator_m2.py --ids ids/24120152.txt --limit 20
```

## Checklist

- [ ]  Cả 6 phép kiểm đều có test riêng trong `tests/test_validator_m2.py`
- [ ]  Có ca test **cố tình sai**: cây 2 root, node mồ côi, vòng lặp — validator phải bắt được
- [ ]  `reports/` vẫn nằm trong `.gitignore`, không commit file JSON kết quả
- [ ]  Gửi `dedup_ratio` cho Tuấn để đưa vào báo cáo
- [ ]  PR vào `main`, nhánh `feat/validator-m2`

---

### Tuần 2 chỉ còn

1. Trỏ validator vào dữ liệu thật, chạy, đọc kết quả
2. Gửi `dedup_ratio` cho Tuấn
3. **So bộ chuẩn vàng với kết quả parser** → ba con số độ chính xác, gửi Tuấn

Việc 3 là phần điểm cộng, và nó chỉ mất một buổi **nếu** file `gold_structure.csv` đã gán tay xong từ tuần 1. Gán tay sau khi đã thấy kết quả parser thì không còn giá trị — nên đây là việc bắt buộc phải làm sớm, không dời được."}

---

## 📅 Lịch chốt — Tuần 2 (15→19/11)

> **Thay cho mọi mốc ngày ghi phía trên trong thẻ này.**
> 

| Hạn | Việc | Chờ ai |
| --- | --- | --- |
| **16/11 T2** | Chạy validator trên fixture lần cuối, sẵn sàng nhận dữ liệu thật | — |
| **18/11 T4** | Chạy validator trên dữ liệu thật, **gửi `dedup_ratio` cho Tuấn** | Hoàng chạy full 18/11 |
| **19/11 T5** | So bộ chuẩn vàng với kết quả parser, **gửi 3 con số độ chính xác cho Tuấn** | — |

⚠️ Hai ngày 15–17/11 Tú chưa có dữ liệu thật để kiểm. Dùng quỹ thời gian đó để **hoàn tất bộ chuẩn vàng** nếu tuần 1 chưa gán đủ 20 bài — đó là phần quyết định con số độ chính xác ngày 19/11.

Nếu Hoàng chạy full muộn hơn 18/11: ưu tiên gửi `dedup_ratio` trước (Tuấn cần nó cho `02-standardization`), phần bộ chuẩn vàng gửi sau — đó là điểm cộng, bỏ được."}


4. Cáp Hửu Duy
## 🟡 Việc tồn đọng chuyển từ Tuần 1 sang

### Thiếu đúng một hàm: `collect_bib()`

```
src/parser/bib.py:307
def collect_bib(vdir: Path) -> list[dict[str, Any]]:
    """Gom toàn bộ reference của MỘT version từ cả hai nguồn (.bib và \bibitem)."""
    raise NotImplementedError
```

Ba hàm kia đã xong và chất lượng tốt — `read_bib_file`, `split_bibitems`, `parse_bibitem`, đều đã migrate sang **bibtexparser v2** đúng yêu cầu, `requirements.txt` ghi `bibtexparser>=2.0,<3`.

Nhưng `collect_bib` là hàm **ráp nối** hai nguồn lại. Không có nó thì ba hàm kia không ai gọi được, và `parse_one()` của nhóm trưởng không lấy được reference.

**Việc cần làm** (ước chừng 20–30 dòng):

1. Tìm mọi file `.bib` trong `vdir` → gọi `read_bib_file()` cho từng file
2. Tìm môi trường `thebibliography` trong các file `.tex` → gọi `split_bibitems()` rồi `parse_bibitem()` cho từng mục
3. Gộp hai danh sách, khử trùng lặp theo `citation_key`
4. Khi một key xuất hiện ở cả hai nguồn: **ưu tiên bản từ `.bib`** vì nó có cấu trúc sẵn, chính xác hơn bản parse từ `\bibitem`
5. Trả về `list[dict]` đúng schema ở `docs/schema_m2.md` mục `bibtex.jsonl`

Nhớ thêm test cho ca **một version có cả `.bib` lẫn `thebibliography`** — đó là ca dễ sinh trùng key nhất.

---

## Đề yêu cầu

> "If different citation keys, the entry names, refer to the same underlying reference content, **(1) a single citation key should be chosen**, and **(2) the `\cite{}` commands of the remaining entries must be renamed** to this chosen key. Additionally, **(3) the deduplication process should unionize the fields** of the duplicate entries rather than selecting one entry while discarding all other information."
> 

**Ví dụ chính đề đưa ra:**

| Version | Key | Trường có |
| --- | --- | --- |
| v1 | `vaswani2017` | title, author, year |
| v2 | `vit_transformer` | title, author, **doi** |
| v3 | `vit_transformer` | title, author (mất year) |

⇒ Kết quả đúng: **một** entry, giữ một key, trường = title + author + **year** + **doi**, và mọi `\cite{vaswani2017}` đổi thành key đã chọn.

Chú ý vế (3): **không được chọn một entry rồi vứt phần còn lại.** `year` chỉ có ở v1 và `doi` chỉ có ở v2 — cả hai đều phải có mặt.

## File làm việc: `src/parser/bib_dedup.py`

### Bước 1 — Chữ ký để nhận ra "cùng một tài liệu"

```python
import re, unicodedata

def norm(s: str | None) -> str:
    if not s: return ""
    s = unicodedata.normalize("NFKD", s)
    s = "".join(c for c in s if not unicodedata.combining(c))   # bỏ dấu
    s = re.sub(r"\{|\}|\\[a-zA-Z]+", " ", s)                     # bỏ lệnh LaTeX
    s = re.sub(r"[^a-z0-9 ]", " ", s.lower())
    return re.sub(r"\s+", " ", s).strip()

def signature(e: dict) -> str:
    """Hai entry cùng chữ ký = cùng một tài liệu."""
    if e.get("doi"):                      # DOI là bằng chứng mạnh nhất
        return "doi:" + e["doi"].lower()
    if e.get("arxiv_id"):
        return "arxiv:" + e["arxiv_id"].lower()
    t = norm(e.get("title"))
    a = norm(e.get("authors")).split(" ")[0] if e.get("authors") else ""
    return f"t:{t}|a:{a}"                 # year KHÔNG vào chữ ký: v3 đã mất year
```

⚠️ **Đừng đưa `year` vào chữ ký.** Chính ví dụ của đề có v3 bị mất `year` — nếu year nằm trong chữ ký thì v3 thành tài liệu khác, dedup thất bại đúng ca mà đề lấy làm ví dụ.

### Bước 2 — Chọn key và gộp trường

```python
FIELDS = ("title", "authors", "year", "doi", "journal", "url")

def merge_group(entries: list[dict]) -> tuple[dict, dict]:
    """Trả về (entry đã gộp, bản đồ đổi tên key cũ -> key được chọn)."""
    # Quy tắc chọn key: version sớm nhất trước, cùng version thì key ngắn hơn.
    # Phải TẤT ĐỊNH — chạy lại phải ra cùng kết quả, không được phụ thuộc thứ tự dict.
    chosen = sorted(entries, key=lambda e: (e["version"], len(e["citation_key"]),
                                            e["citation_key"]))[0]["citation_key"]
    merged = {"citation_key": chosen}
    for f in FIELDS:
        for e in sorted(entries, key=lambda e: e["version"]):
            if e.get(f):
                merged[f] = e[f]          # trường đầu tiên khác rỗng thắng
                break
    rename = {e["citation_key"]: chosen for e in entries
              if e["citation_key"] != chosen}
    return merged, rename
```

### Bước 3 — Đổi tên `\cite{}` trong nội dung

Đây là vế dễ bị bỏ quên nhất. Phải đổi trong **chính văn bản** trước khi nhóm trưởng băm `element_id`:

```python
CITE = re.compile(r"(\\(?:cite|citep|citet|citeyear|citealp)\*?(?:\[[^\]]*\])*\s*)\{([^}]+)\}")

def rename_cites(tex: str, rename: dict[str, str]) -> str:
    def fix(m):
        keys = [rename.get(k.strip(), k.strip()) for k in m.group(2).split(",")]
        seen, out = set(), []
        for k in keys:                     # \cite{a,b} mà a,b gộp làm một -> bỏ trùng
            if k not in seen:
                seen.add(k); out.append(k)
        return m.group(1) + "{" + ",".join(out) + "}"
    return CITE.sub(fix, tex)
```

⚠️ **Thứ tự chạy rất quan trọng:** đổi tên `\cite` phải xảy ra **trước** khi Hoàng băm nội dung thành `element_id`. Hai câu giống hệt nhau nhưng một câu ghi `\cite{vaswani2017}` còn câu kia ghi `\cite{vit_transformer}` sẽ ra hai id khác nhau, làm hỏng dedup nội dung của Hoàng. **Thứ tự này ĐÃ ĐƯỢC CHỐT — xem mục "Quy ước đã chốt" ở cuối thẻ, không cần bàn lại.**

## Đầu ra

- Bảng `bibtex` hoàn chỉnh theo đúng 9 cột đề quy định
- `reports/cite_rename_map.json` — để kiểm tra và để Tuấn thống kê số lượng key bị gộp
- Cột `n_after_dedup` trong `logs/bib.csv` (tuần 1 để trống, giờ điền)

Số *"entry counts before and after deduplication"* là thống kê đề đòi — gửi cho Tuấn.

## Checklist

- [ ]  Test đúng ví dụ 3 version của đề (`vaswani2017` / `vit_transformer`), kết quả phải có **cả** `year` và `doi`
- [ ]  Test `\cite{a,b}` khi a và b gộp làm một → ra `\cite{a}`, không ra `\cite{a,a}`
- [ ]  Test tính tất định: chạy 2 lần trên cùng đầu vào ra cùng key được chọn
- [ ]  Đã đọc mục "Quy ước đã chốt" ở cuối thẻ và làm đúng thứ tự đổi `\cite` trước khi băm
- [ ]  PR vào `main`, nhánh `feat/bib-dedup`

---

## ✅ Quy ước đã chốt — thứ tự pipeline

> Nhóm trưởng đã quyết, **không cần bàn lại**. Quy ước này ghi giống hệt trong thẻ Tuần 2 của Ngọc Hoàng và sẽ được chép vào `docs/schema_m2.md`.
> 

### Thứ tự bắt buộc, cho mỗi publication

| Bước | Ai | Làm gì |
| --- | --- | --- |
| 1 | Minh Thư | `gather(vdir)` → đường biên dịch của từng version |
| 2 | Thanh Tú | `clean_latex()` rồi `normalize_math()` trên toàn văn từng version |
| 3 | **Hửu Duy, lượt 1** | Đọc bib của **tất cả** version → dựng `rename_map` |
| 4 | **Hửu Duy, lượt 2** | `rename_cites()` trên văn bản đã chuẩn hoá của từng version |
| 5 | Ngọc Hoàng | Dựng cây và băm `element_uid()` **trên văn bản ra từ bước 4** |

Vì sao phải **hai lượt**: `rename_map` chỉ dựng được khi đã đọc hết mọi version của bài đó, nên không thể vừa đọc vừa đổi tên trong một lượt.

### Giao diện hàm — Duy viết, Hoàng gọi

```python
# src/parser/bib_dedup.py
def unify_publication(
    norm_text: dict[int, str],           # {version: toàn văn đã chuẩn hoá (bước 2)}
    bib_entries: dict[int, list[dict]],  # {version: entries từ .bib và \bibitem}
) -> tuple[dict[int, str], list[dict], dict[str, str]]:
    """
    Trả về:
      renamed_text : {version: văn bản đã đổi \cite sang key chuẩn}
      bibtex_rows  : bảng bibtex đã gộp trường, mỗi tài liệu một dòng
      rename_map   : {key_cũ: key_chuẩn}, ghi ra reports/cite_rename_map.json
    """
```

Trong `src/parse_main.py` của nhóm trưởng sẽ gọi đúng như sau:

```python
norm_text    = {v: normalize_math(clean_latex(read_version(v))) for v in versions}
bib_entries  = {v: collect_bib(v) for v in versions}

renamed_text, bibtex_rows, rename_map = unify_publication(norm_text, bib_entries)

elements, hierarchy = build_store(pub_key, renamed_text)   # CHỈ băm ở đây, sau bước 4
```

### Ba quy tắc đã chốt

**1. Chọn key chuẩn — tất định.** Version nhỏ nhất trước → key ngắn hơn → thứ tự chữ cái. Chạy lại phải ra cùng kết quả, không được phụ thuộc thứ tự duyệt `dict`.

**2. Sắp xếp key trong `\cite{}` nhiều key.** `\cite{b,a}` ở v1 và `\cite{a,b}` ở v2 là cùng một nội dung. Sau khi đổi tên thì **sort rồi bỏ trùng**:

```python
keys = sorted({rename.get(k.strip(), k.strip()) for k in m.group(2).split(",")})
return m.group(1) + "{" + ",".join(keys) + "}"
```

Lý do chọn cách này: cột `content` là bản **đã chuẩn hoá**, không phải bản sao nguyên văn của tác giả. Mục đích của cả bước này là làm cho hai đoạn cùng nghĩa băm ra cùng một id — giữ nguyên thứ tự trích dẫn sẽ làm hỏng chính mục đích đó.

**3. `\cite` trỏ vào key không tồn tại** (dangling cite, thường do tác giả xoá bibitem mà quên xoá cite): **giữ nguyên**, không bỏ, không báo lỗi. Nhưng **đếm lại** và gửi số cho Tuấn — đó là một chỉ số chất lượng dữ liệu đáng đưa vào báo cáo.

### Điểm dễ sai nhất

**Văn bản đã đổi tên là văn bản được lưu.** Cột `content` trong bảng `elements` lưu bản **sau bước 4**, không phải bản gốc. Nếu lưu bản gốc mà băm bản đã đổi tên thì `element_id` và `content` không khớp nhau, và validation suite của Thanh Tú sẽ bắt lỗi này.

---

## 📅 Lịch chốt — Tuần 2 (15→19/11)

> **Thay cho mọi mốc ngày ghi phía trên trong thẻ này.** Chỗ nào ở trên còn ghi "giao hàm chậm nhất 19/11" là bản cũ — đã đổi thành **17/11**.
> 

| Hạn | Việc |
| --- | --- |
| **16/11 T2** | `rename_cites()`  • test ca `\cite{a,b}` khi a và b gộp làm một |
| **17/11 T3** | 🔴 Ghép `unify_publication()` hai lượt · **GIAO HÀM CHO HOÀNG** |
| **18/11 T4** | Đo độ chính xác bóc `\bibitem` trên 124 version có cả `.bib`, gửi bảng cho Tuấn |
| **19/11 T5** | Số entry trước/sau dedup + `cite_rename_map.json`, gửi Tuấn |


5. Nguyễn Lê Anh Tuấn (Tôi)
## 🔴 Việc tồn đọng chuyển từ Tuần 1 sang

### 1. Sửa lỗi `shell=True` trong `benchmark.py` — ưu tiên cao nhất

Chạy test suite trên main: **227 pass, 1 fail**, và đây là test fail duy nhất.

```
tests/test_benchmark.py::test_shell_command_execution  FAILED
/bin/sh: 1: Syntax error: "(" unexpected
```

**Nguyên nhân:** commit `e6fefc1` thêm hỗ trợ `shell=True` nhưng nối danh sách lệnh thành chuỗi mà không quote. Lệnh trong test là:

```python
cmd = [sys.executable, "-c", "print('step1')", "&&", sys.executable, "-c", "print('step2')"]
run_benchmark(command=cmd, shell=True, stage="test_shell")
```

Khi nối không quote, shell nhận `python -c print('step1') && ...` — dấu `(` trở thành cú pháp shell và vỡ.

**Vì sao đáng ưu tiên:** lỗi này **chỉ xảy ra trên Linux**. Windows dùng `cmd.exe` xử lý khác nên máy Tuấn không thấy. Mà **Colab là Linux** — đúng nơi cả 5 người đang chạy benchmark. Công cụ đo của nhóm đang có một đường code hỏng trên chính môi trường đo.

**Hướng sửa:** dùng `shlex.join()` (hoặc `subprocess.list2cmdline` trên Windows) khi `shell=True`, thay vì nối bằng `" ".join()`. Hoặc đơn giản hơn: khi `shell=True` thì yêu cầu `command` phải là **một chuỗi** chứ không phải list, và raise lỗi rõ ràng nếu nhận list.

Sửa xong nhớ chạy `python -m pytest tests/test_benchmark.py -q` trên Linux hoặc Colab để xác nhận, đừng chỉ test trên Windows.

### 2. Chuyển 2–3 biểu đồ sang Plotly — tồn đọng từ Milestone 1

Đếm trên main ngày 15/11:

| Notebook | plotly | matplotlib |
| --- | --- | --- |
| `01-methodology.ipynb` | 0 | 0 |
| `02-statistics.ipynb` | **0** | 24 |
| `03-performance.ipynb` | **0** | 25 |
| `04-deep-analysis.ipynb` | **0** | 27 |
| `01-parsing.ipynb` | 0 | 1 |
| `02-standardization.ipynb` | 0 | 1 |
| `03-evaluation.ipynb` | 0 | 1 |

`_config.yml` khai báo `plotly` trong `sphinx.extra_extensions` và `requirements.txt` có `plotly>=5.18.0`, nhưng **không notebook nào dùng**. Đây là điều đã nêu từ Milestone 1 và vẫn chưa xử lý.

Không cần chuyển hết — chọn **2–3 biểu đồ có lợi nhất khi tương tác**, ví dụ:

- Phân bố thời gian tải theo version (`download.csv` có `seconds` + `bytes` cho từng version) — hover xem được bài nào chậm
- So sánh hiệu năng 4 giai đoạn giữa 5 thành viên — chọn/ẩn từng người
- Phân bố số version/bài

Giữ matplotlib cho các biểu đồ còn lại, không cần làm đồng loạt.

**Dữ liệu mới có sẵn:** nhóm trưởng đã cào lại trên Colab và có `download.csv` đủ **7.875 dòng** với `seconds`/`bytes` từng version, cùng 4 dòng `benchmark_runs.csv` đo trên Colab CPU-only. Thư mục Drive `introds_crawl_24120053/logs`.

---

> **Phần việc:** thêm một phần mới vào **chính book hiện tại**, không tạo book mới. Đề ghi rõ: *"the same book repository introduced in Milestone 1... adding a parsing-and-standardization section to that book rather than creating a new one"*. Link `github.io` **không được đổi** vì đã nộp trên Moodle.
> 

## Cấu trúc cần tạo

`_toc.yml` đã có sẵn part "Giai đoạn 2 — Bóc tách Dữ liệu" trỏ vào `milestone2/reserved`. Thay chỗ giữ chỗ đó:

```yaml
  - caption: "Giai đoạn 2 — Bóc tách Dữ liệu"
    chapters:
      - file: milestone2/01-parsing
      - file: milestone2/02-standardization
      - file: milestone2/03-parser-performance
```

Rồi xoá `milestone2/reserved.md`.

## ① `01-parsing.ipynb` — Hierarchical Parsing

Đề đòi: *"Explanation of the logic used to detect file structure, parse the LaTeX hierarchy, and handle multi-file inputs."*

Nội dung lấy từ Minh Thư và nhóm trưởng:

- Cách dò root file (`\documentclass`) và cách chấm điểm khi có nhiều ứng viên
- Cách đi đệ quy `\input`/`\include`/`\subfile`, cách chống vòng lặp
- **Biểu đồ đáng giá:** phân bố số file trong đường biên dịch vs số file thừa — dữ liệu từ `logs/gather.csv` cột `n_files_path` và `n_files_unused`. Ít nhóm làm được phần này.
- Cách tự suy cấp độ section, kèm ví dụ một bài dùng `\chapter` và một bài không
- Cách tách câu và cách tránh cắt nhầm `Fig. 2`, `et al.`, `3.14` — nên đưa một ví dụ cụ thể trước/sau

## ② `02-standardization.ipynb` — Chuẩn hoá & Dedup

Đề đòi: *"Details on how data cleaning, math normalization, and reference deduplication were implemented."*

Nội dung từ Thanh Tú và Hửu Duy:

- Bảng trước/sau của `clean_latex()` trên một đoạn thật
- Bảng quy đổi công thức: `$$..$$`, `\[..\]`, `align*`, `eqnarray` → `equation`
- **Số element trước và sau dedup** — đề đòi đích danh *"element/entry counts before and after deduplication"*. Lấy `dedup_ratio` từ `reports/validation_m2.json` của Tú.
- **Số entry BibTeX trước và sau dedup** + số `\cite` đã đổi tên, từ `reports/cite_rename_map.json` của Duy
- Tỉ lệ bóc tách thành công từng trường từ `\bibitem` (title / year / doi) — số này trung thực và đáng điểm hơn là gấp lại

## ③ `03-parser-performance.ipynb` — Hiệu năng

Đề chỉ đòi **4 con số**, gọn hơn M1 nhiều:

| Chỉ số | Nguồn |
| --- | --- |
| Wall-clock toàn bộ parser | `benchmark_runs.csv`, dòng `stage=parse` |
| Thời gian TB mỗi publication | wall / số bài |
| RAM tối đa | `peak_ram_mb` |
| Dung lượng output cuối | `disk_usage_mb` |

Minh Thư gửi số đo thật trên Colab CPU-only. **Ghi rõ cỡ mẫu** (50 bài) trong báo cáo — đề ghi *"No upper limit on the running time is enforced"* nên mẫu nhỏ là hợp lệ, miễn nói thật.

## Ba nguyên tắc rút ra từ M1

**1. Mọi con số phải tính từ file, không gõ tay.** Đề lặp lại yêu cầu này ở M2: *"figures and tables must be generated during book compilation"*. Ở M1 đã có cell gõ tay `ver_counts = [7505, 538, 23]` phải sửa lại — lần này làm đúng từ đầu.

**2. Ghi rõ nguồn từng con số.** Mỗi bảng nên có một dòng chú thích nói lấy từ file nào, cỡ mẫu bao nhiêu.

**3. Dùng Plotly ngay từ đầu** cho phần M2, đừng để phải chuyển sau như M1.

## Checklist

- [ ]  `_toc.yml` đã thay `reserved` bằng 3 notebook mới, đã xoá `reserved.md`
- [ ]  Build sạch, không cell nào lỗi, `execute_notebooks: force` vẫn bật
- [ ]  Không có số nào gõ tay — toàn bộ `read_csv` từ `data/`
- [ ]  Mở link `github.io` ở cửa sổ ẩn danh, phần Giai đoạn 2 hiện đầy đủ
- [ ]  Link `github.io` **y nguyên như đã nộp Moodle**, không đổi tên repo hay org

---

## 📅 Lịch chốt — Tuần 2 (15→19/11)

> **Thay cho mọi mốc ngày ghi phía trên trong thẻ này.**
> 

| Hạn | Việc | Nhận số từ |
| --- | --- | --- |
| **16/11 T2** | Hoàn thiện phần chữ 3 notebook M2 | — |
| **17/11 T3** | Cắm số `gather.csv` vào `01-parsing` | Thư (có từ tuần 1) |
| **18/11 T4** | Cắm `parse.csv`  • `elements`/`hierarchy`  • bảng bóc `\bibitem`  • 4 chỉ số hiệu năng | Hoàng · Duy · Thư |
| **19/11 T5** | `dedup_ratio`  • độ chính xác parser + 2 biểu đồ tương tác + build cuối, kiểm cửa sổ ẩn danh | Tú |

⚠️ **19/11 vừa là ngày nhận nhiều số nhất vừa là ngày cuối.** Nên 16/11 và 17/11 phải xong hẳn phần chữ và cấu trúc, để 19/11 chỉ còn dán số vào chỗ đã chừa sẵn.

### Ai giao số cho Tuấn, ngày nào

| Người | Giao gì | Hạn |
| --- | --- | --- |
| Minh Thư | `gather.csv` (tuần 1) · 4 chỉ số + bảng `--workers` | 18/11 |
| Ngọc Hoàng | `parse.csv`, bảng `elements`/`hierarchy` | 18/11 |
| Hửu Duy | Bảng độ chính xác `\bibitem` · số entry trước/sau dedup | 18–19/11 |
| Thanh Tú | `dedup_ratio` · 3 con số độ chính xác parser | 18–19/11 |

Ai trễ thì nhắc nhóm trưởng ngay trong ngày, đừng đợi tới 19/11."}