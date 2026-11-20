1. Đặng Ngọc Hoàng 
**Vai trò tuần này:** chốt hợp đồng dữ liệu trước, dựng khung module trống, để 4 bạn còn lại code song song mà không giẫm chân nhau. Giống hệt vai trò `docs/schema.md` ở Milestone 1 — chính nó đã giúp 5 người làm 5 module ghép được vào nhau.
> 

## A. `docs/schema_m2.md` — hợp đồng dữ liệu · hạn **10/11**

Đây là file quan trọng nhất tuần này. Chưa có nó thì 4 bạn kia không bắt đầu được.

Nội dung phải chốt:

**1. Ba bảng đầu ra** (đề đã quy định, chép nguyên vào file):

| Bảng | Cột |
| --- | --- |
| `elements` | element_id, arxiv_id, kind, content — **một dòng cho mỗi element KHÁC NHAU** trên tất cả version |
| `hierarchy` | arxiv_id, version, element_id, parent_id — một dòng cho mỗi cạnh node→cha, **của từng version** |
| `bibtex` | arxiv_id, citation_key, entry_type, title, authors, year, doi, journal, url |

**2. Quy tắc sinh `element_id`** — chỗ này quyết định việc dedup có chạy không.

Đề ghi: *"Element IDs begin with the publication key followed by a discriminant that is unique inside the publication."* Cách gọn nhất là băm chính nội dung đã chuẩn hoá, vì khi đó **hai version có nội dung giống nhau tự động ra cùng một id**, không cần bước so khớp riêng:

```python
import hashlib

def element_uid(pub_key: str, kind: str, clean_content: str) -> str:
    """2310-12345#s1a2b3c4d — dedup xảy ra tự động vì cùng nội dung → cùng id."""
    h = hashlib.sha1(clean_content.encode("utf-8")).hexdigest()[:8]
    return f"{pub_key}#{kind[0]}{h}"
```

⚠️ Hệ quả quan trọng phải ghi rõ trong file: **băm chạy SAU bước chuẩn hoá của Thanh Tú**. Đề nói *"full-text matching should be performed after cleanup"*. Nếu Tú đổi quy tắc chuẩn hoá giữa chừng thì toàn bộ element_id đổi theo — nên quy tắc chuẩn hoá phải chốt trong tuần 1 và không sửa ở tuần 2.

**3. Bảng `kind` hợp lệ** — dùng đúng chuỗi này để thống kê được:
`document` · `section` · `subsection` · `subsubsection` · `paragraph` · `itemize` · `item` · `sentence` · `formula` · `figure`

(Đề gộp **Table vào Figure**: *"Figures, with Tables also considered a type of Figure for this purpose"* — nên không có kind `table` riêng.)

**4. Version rỗng.** Đề: *"A version without TeX sources... record the version as empty rather than skipping it"*. Chốt cách ghi: version đó có đúng 1 dòng `elements` kind `document` với content rỗng, và 0 dòng `hierarchy`.

**5. Định dạng log** (để Tuấn dựng biểu đồ, giống 4 file log của M1):

```
logs/gather.csv   : arxiv_id,version,root_file,n_files_path,n_files_unused,status,error_type
logs/parse.csv    : arxiv_id,version,n_elements,n_sentences,n_formulas,n_figures,max_depth,seconds,status,error_type
logs/bib.csv      : arxiv_id,version,n_bibitem,n_bibfile_entries,n_after_dedup,status,error_type
```

`status` ∈ `ok`/`fail`/`empty`/`skipped`, `error_type` rỗng khi ok — giữ nguyên quy ước M1 để Tuấn tái dùng code cũ.

## B. Khung package `src/parser/` · hạn **11/11**

Tạo file rỗng có chữ ký hàm sẵn rồi push, để 4 bạn pull về điền ruột. Đây là cách tránh conflict:

```
src/parser/__init__.py
src/parser/gather.py      # Minh Thư  — gather(root, vdir) -> list[Path]
src/parser/normalize.py   # Thanh Tú  — clean_latex(s) -> str ; normalize_math(s) -> str
src/parser/bib.py         # Hửu Duy   — bibitems_to_entries(tex) -> list[dict]
src/parser/hierarchy.py   # Ngọc Hoàng (tuần 2)
src/parser/elements.py    # Ngọc Hoàng (tuần 2)
src/parse_main.py         # orchestrator, gọi 4 module trên
```

Mỗi file chỉ cần `def ten_ham(...) -> kiểu: raise NotImplementedError` kèm docstring mô tả đầu vào/đầu ra. Push lên `main` luôn, không cần PR.

## C. Tồn đọng M1 — đưa book vào repo code · hạn **14/11**

Ô nộp thứ 2 trên Moodle yêu cầu: *"repository Github chứa mã nguồn luồng dữ liệu của nhóm, **bao gồm cả các file có nội dung dùng để viết Jupyter Book**"*. Repo code hiện chưa có. Moodle cho phép commit tiếp sau hạn, nhưng làm sớm cho xong.

```bash
cd introds-arxiv-project
mkdir -p book
cp -r ../introds-arxiv-book/{milestone1,milestone2,data,_config.yml,_toc.yml,intro.md,aggregate_5_members.py} book/
```

⚠️ `.gitignore` hiện chặn `*.csv` và `data/`, nên phải mở ngoại lệ, **đặt sau các dòng chặn** thì mới có tác dụng:

```
!book/
!book/data/
!book/data/*.csv
```

Kiểm trước khi commit: `git status --short book/ | wc -l` phải ra con số lớn hơn 0, và `git check-ignore -v book/data/discovery.csv` phải **không** in ra gì.

Vẫn giữ chặn `corpus/`, `raw/`, `logs/` — đề yêu cầu repo không chứa dữ liệu crawl.

## Checklist trước khi push

- [ ]  `docs/schema_m2.md` đã push, đã báo nhóm trong chat
- [ ]  6 file khung trong `src/parser/` đã push lên `main`
- [ ]  `book/` đã vào repo code, `git check-ignore` không chặn
- [ ]  `git status` không có `corpus/`, `raw/`, `logs/`, `*.tar.gz`

> **Lưu ý về lịch:** 2 tuần này mình tạm đặt 08/11→15/11 và 16/11→22/11. Khi thầy công bố hạn thật của Milestone 2 thì sửa lại cột Date của cả 10 thẻ.
> 

---

## 📦 Bổ sung — ba hàm đẩy từ Tuần 2 lên Tuần 1

> **Lý do:** Tuần 2 chỉ còn 5 ngày (15→20/11) và là tuần phải ghép 4 module của 4 người lại. Ba hàm dưới đây là **hàm thuần tuý** — nhận một chuỗi, trả một kết quả, không cần đầu ra của ai cả. Viết và test xong trong tuần 1 thì tuần 2 chỉ còn việc ghép.
> 

Viết vào `src/parser/hierarchy.py`, test bằng chuỗi tự gõ, **không cần chờ Tú hay Thư**.

### 1. `infer_levels(tex) -> dict[str, int]` · hạn **10/11**

Suy cấp độ section theo thứ tự xuất hiện lần đầu trong chính tài liệu đó. Code mẫu đã có trong thẻ Tuần 2, mục A.

Test: chuỗi có `\chapter` rồi `\section` → `{chapter:1, section:2}`. Chuỗi chỉ có `\section` rồi `\subsection` → `{section:1, subsection:2}`. Phải bắt được cả dạng `\section*`.

### 2. `strip_references(tex) -> str` · hạn **11/11**

Cắt phần References nhưng **giữ Appendix nằm sau nó**. Đây là ca dễ sai nhất, test riêng:

```python
tex = r"\section{Intro} A. \begin{thebibliography}{9}\bibitem{x}Y\end{thebibliography} \section*{Appendix} B."
out = strip_references(tex)
assert "Appendix" in out and "bibitem" not in out
```

### 3. `split_sentences(text) -> list[str]` · hạn **13/11**

Hàm khó nhất, nên làm sớm để có thời gian sửa. Code mẫu đã có trong thẻ Tuần 2, mục C.

Bộ test tối thiểu — phải ra **đúng 3 câu**:

```python
s = "We use BERT (Devlin et al. 2019). The result is 3.14 times better. See Fig. 2 for details."
assert len(split_sentences(s)) == 3
```

Thêm ca: công thức `$a.b$` không bị cắt, URL `http://x.com/a.b` không bị cắt, `i.e.` và `e.g.` không bị cắt.

## Tuần 2 còn lại gì

Chỉ còn phần **không thể làm sớm** vì cần đầu ra của người khác: `build_store()` + `element_uid()`, ghép `src/parse_main.py`, chạy thật và kiểm `dedup_ratio`. Đó là đúng một ngày làm việc nếu ba hàm trên đã xong và có test.

## 🎯 Điểm cộng — chạy lại được từ giữa chừng (resumable)

> Ngoài yêu cầu của đề, nhưng phục vụ trực tiếp tiêu chí **Code Quality & Reproducibility**.
> 

Parse 25.000 bài sẽ mất nhiều giờ. Nếu đứt giữa chừng mà phải chạy lại từ đầu thì rất phí — và nhóm đã nếm mùi này ở M1 với bug archive cụt đuôi làm chết cả mẻ.

Cách làm rẻ nhất: ghi kết quả theo từng publication, lần chạy sau bỏ qua bài đã có.

```python
def already_done(pub_key: str, out_root: Path) -> bool:
    return (out_root / pub_key / "elements.jsonl").exists()

# trong vòng lặp chính của parse_main.py
for pub in publications:
    if already_done(pub.key, out_root) and not args.overwrite:
        log(pub.key, status="skipped"); continue
```

Thêm cờ `--overwrite` giống `discovery.py` ở M1 để ép chạy lại khi cần.

Hai câu trong báo cáo nói về cơ chế này, kèm con số "chạy lại sau khi đứt chỉ mất X phút thay vì Y giờ", là thứ người chấm nhớ được."}

---

## 📅 Lịch nộp từng phần — Tuần 1 (07→14/11)

> Bảng này **thay cho mọi mốc ngày rải rác phía trên**. Có mâu thuẫn thì theo bảng này.
> 

| Hạn | Việc | Vì sao đặt ngày này |
| --- | --- | --- |
| **08/11 CN** | `docs/schema_m2.md` — chốt 3 bảng, quy tắc `element_id`, bảng `kind`, định dạng log | **Chặn cả 4 bạn kia.** Phải xong sớm nhất |
| **09/11 T2** | Khung `src/parser/` 6 file + `src/parse_main.py` stub, push thẳng `main` | 4 bạn pull về mới có chỗ điền code |
| **10/11 T3** | `book/` vào repo code + sửa `.gitignore` | Độc lập, làm xen kẽ cho nhẹ ngày sau |
| **11/11 T4** | `infer_levels()`  • test |  |
| **12/11 T5** | `strip_references()`  • test ca Appendix nằm sau References |  |
| **14/11 T7** | `split_sentences()`  • bộ test 3 câu | Hàm khó nhất, để 2 ngày |

## 📅 Lịch Tuần 2 (15→20/11)

| Hạn | Việc |
| --- | --- |
| **16/11 T2** | `build_store()`  • `element_uid()` |
| **17/11 T3** | Ghép `src/parse_main.py`, chạy `--limit 20` sạch |
| **18/11 T4** | **Chạy full và giao `parse.csv`  • bảng `elements`/`hierarchy` cho Tuấn** |
| **19/11 T5** | Kiểm `dedup_ratio`, sửa nếu bất thường |
| **20/11 T6** | Rà soát cuối, nộp Moodle |

⚠️ **Mốc 18/11 là mốc cứng của cả nhóm.** Tuấn kết thúc 19/11 nên phải nhận số chậm nhất 18/11. Nếu 17/11 mà `parse_main.py` chưa chạy được `--limit 20` thì báo nhóm ngay để cắt bớt phạm vi, đừng cố hoàn hảo rồi trễ.

Duy giao `unify_publication()` cho Hoàng **17/11** (đã chỉnh sớm hơn, vì phần nặng của Duy đã dời lên Tuần 1)."}

---

## ⚠️ Đính chính mục C — `.gitignore` chặn gì

Mục C phía trên ghi `.gitignore` chặn `*.csv`. **Sai** — đã mở file ra kiểm, trong đó **không có dòng `*.csv`** nào.

Thứ thực sự chặn `book/data/` là dòng **`data/`**. Không có dấu `/` ở đầu nên nó khớp mọi thư mục tên `data` ở bất kỳ cấp nào, kể cả `book/data`.

Ngoại lệ đúng, đặt ở **cuối** `.gitignore`:

```
# --- Ngoại lệ: source của Jupyter Book (ô nộp thứ 2 trên Moodle yêu cầu) ---
!book/
!book/data/
```

Chỉ cần hai dòng. Git **không duyệt vào thư mục đã bị loại**, nên phải bỏ loại chính thư mục `book/data/` trước; sau đó các file bên trong (`.csv`, `.json`, `.md`, `.txt`) không khớp dòng chặn nào nên tự được commit.

Kiểm trước khi commit:

```bash
git check-ignore -v book/data/discovery.csv   # phải KHÔNG in ra gì
git status --short book/ | wc -l              # phải ra ~50
```

Các dòng `*.tex`, `*.bib`, `*.pdf` vẫn giữ nguyên — `book/data/` không có file loại đó nên không ảnh hưởng.


2. Dương Ngọc Minh Thư
> **Phần việc:** tìm đúng những file `.tex` thật sự được biên dịch vào PDF, bỏ qua file thừa nằm lẫn trong thư mục source. Đây là bước **đầu tiên** của pipeline M2 — mọi bước sau đọc kết quả của Thư.
> 

## Đề yêu cầu

> "Students must programmatically identify the main compilation path and parse only those files that are actually included in the final PDF rendering. Unused or redundant files found in the source directory must be ignored. Concretely, the publication root is the `.tex` file containing the `\documentclass` declaration. Follow `\input` and `\include` commands **transitively**, treating commands that are **commented out** as plain text rather than includes."
> 

## Tin tốt: đã có sẵn 70% · file `src/tex_prescan.py`

Hửu Duy đã viết sẵn trong Milestone 1, Thư **đọc file này trước khi code**:

| Đã có | Dòng |
| --- | --- |
| `DOC_CLASS_PATTERN` — regex tìm `\documentclass`/`\documentstyle` | 28 |
| `INCLUDE_PATTERN` — bắt `\input{}`, `\include{}`, `\subfile{}` | 29 |
| `INPUT_BARE_PATTERN` — bắt `\input path` không ngoặc nhọn | 30 |
| `clean_tex_comments()` — bỏ comment, đúng yêu cầu "commented out as plain text" | 35 |
| `extract_includes()` — trích danh sách include của **một** file | 52 |
| `score_root_candidate()` — chọn root khi có nhiều file chứa `\documentclass` | 68 |

**Thiếu đúng một thứ:** docstring của file ghi rõ *"chưa resolve đệ quy"*. Việc của Thư là làm phần đệ quy đó.

## File làm việc: `src/parser/gather.py`

Nhóm trưởng sẽ push file khung trống vào ngày 11/11.

```python
from pathlib import Path
from tex_prescan import clean_tex_comments, extract_includes, find_root

def resolve_path(base: Path, raw: str, vdir: Path) -> Path | None:
    """\input{sec/intro} -> sec/intro.tex. LaTeX tự thêm .tex nếu thiếu."""
    raw = raw.strip().strip('"')
    for start in (base, vdir):                 # tương đối với file cha, rồi với gốc version
        p = (start / raw)
        for cand in (p, p.with_suffix(".tex"), Path(str(p) + ".tex")):
            if cand.is_file():
                return cand.resolve()
    return None

def gather(vdir: Path) -> tuple[list[Path], list[Path]]:
    """Trả về (đường biên dịch theo thứ tự, danh sách file thừa)."""
    root = find_root(vdir)
    if root is None:
        return [], sorted(vdir.rglob("*.tex"))

    order, seen, stack = [], set(), [root.resolve()]
    while stack:
        f = stack.pop(0)                       # pop(0) giữ đúng thứ tự xuất hiện
        if f in seen:
            continue                           # CHỐNG VÒNG LẶP: a.tex \input b.tex \input a.tex
        seen.add(f)
        order.append(f)
        txt = clean_tex_comments(f.read_text(encoding="utf-8", errors="replace"))
        for raw in extract_includes(txt):
            t = resolve_path(f.parent, raw, vdir)
            if t and t not in seen:
                stack.append(t)

    unused = sorted(set(p.resolve() for p in vdir.rglob("*.tex")) - seen)
    return order, unused
```

## Các việc phải xử lý

1. **Vòng lặp include** — `a.tex` gọi `b.tex`, `b.tex` gọi lại `a.tex`. Không có `seen` thì treo vô hạn. Code trên đã chặn.
2. **File không tồn tại** — `\input{missing}` trỏ vào file đã bị lọc mất ở M1 (file ảnh, file `.sty`). Bỏ qua, đừng để crash, nhưng **đếm lại** để ghi vào log.
3. **Không tìm thấy root** — version không có file nào chứa `\documentclass`. Ghi `status=fail`, `error_type=no_root`. Theo prescan của Duy có **2/7.471** version rơi vào ca này (tỉ lệ dò được root 99,97%).
4. **Version rỗng** — đã được M1 đánh dấu `_EMPTY.json`. Ghi `status=empty`, bỏ qua, **đừng bỏ sót dòng log** — đề yêu cầu ghi nhận chứ không được nhảy cóc.

## Đầu ra

`logs/gather.csv` theo đúng định dạng trong `docs/schema_m2.md`:

```
arxiv_id,version,root_file,n_files_path,n_files_unused,status,error_type
2507.06659,1,main.tex,3,0,ok,
```

Số liệu này Tuấn sẽ dùng để vẽ biểu đồ *"bao nhiêu % file trong source là file thừa"* — một phân tích hay mà ít nhóm có.

## Chạy thử trước khi chạy full

```bash
python src/parser/gather.py --ids ids/24120144.txt --limit 20
```

Đối chiếu với `book/data/duy2_prescan_versions.csv` cột `root_file` — Duy đã dò root cho 7.469 version, kết quả của Thư phải khớp phần lớn. Lệch nhiều là có bug.

## Checklist trước khi push

- [ ]  Chạy `--limit 20` không crash, không treo
- [ ]  Có test cho ca vòng lặp include và ca thiếu root (`tests/test_gather.py`)
- [ ]  `logs/gather.csv` đúng tên cột theo `docs/schema_m2.md`
- [ ]  `git status` không có `corpus/`, `logs/`, `*.tex`
- [ ]  PR vào `main`, đặt tên nhánh `feat/gather`

---

## 📦 Bổ sung — chuẩn bị sẵn cho Tuần 2

> **Lý do:** Tuần 2 chỉ còn 5 ngày và phần đo hiệu năng của Thư **phụ thuộc hoàn toàn** vào việc Hoàng ghép xong `parse_main.py`. Nếu tới tuần 2 mới bắt đầu chuẩn bị môi trường Colab thì Thư sẽ ngồi chờ rồi làm vội. Chuẩn bị trước thì lúc Hoàng giao xong chỉ cần bấm chạy.
> 

### 1. Nén mẫu corpus 50 bài · hạn **12/11**

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

Chọn mẫu có **ít nhất 15 bài nhiều version** — vì đó là loại bài làm lộ hiệu quả dedup, và cũng là loại tốn thời gian parse nhất. Kiểm bằng `discovery.csv` cột `n_versions`.

### 2. Dựng sẵn notebook Colab · hạn **13/11**

Viết sẵn toàn bộ cell, để sẵn ô `!python src/benchmark.py ... -- python src/parse_main.py ...`, chạy thử tới bước `pip install` cho chắc môi trường ổn. Lưu notebook vào `book/milestone2/colab_benchmark.ipynb` để nộp kèm, chứng minh phép đo tái lập được.

## 🎯 Parse song song nhiều tiến trình

> Ngoài yêu cầu của đề, phục vụ trực tiếp tiêu chí **Parser's Performance** — câu hỏi chấm điểm nguyên văn là *"How efficient the parser is"*.
> 

**Vì sao parse song song được mà crawl thì không:** crawl bị chặn bởi luật 3 giây/request của arXiv, thêm tiến trình cũng vô ích. Parse thì **không gọi mạng** — nó đọc file và chạy regex, tức là nghẽn ở CPU. Mỗi publication độc lập hoàn toàn với publication khác, nên chia cho nhiều core là xong.

```python
from concurrent.futures import ProcessPoolExecutor
import os

def parse_all(pub_keys: list[str], workers: int = 1):
    if workers <= 1:
        return [parse_one(k) for k in pub_keys]
    with ProcessPoolExecutor(max_workers=workers) as ex:
        return list(ex.map(parse_one, pub_keys, chunksize=16))
```

Thêm cờ `--workers N` vào `parse_main.py`, mặc định `1` để kết quả vẫn tất định khi cần so sánh.

⚠️ **Hai điều phải cẩn thận:**

- Mỗi tiến trình con **ghi log riêng** rồi gộp lại ở cuối. Nhiều tiến trình cùng ghi một file CSV sẽ ra dòng lẫn vào nhau.
- Colab miễn phí chỉ có **2 vCPU**, nên đừng kỳ vọng nhanh gấp 8. Đo thật trên 2 core và báo đúng số đo được.

**Bảng đưa vào báo cáo** — đúng dạng bảng before/after mà Thư đã làm ở A1, và lần này nó trả lời thẳng câu hỏi chấm điểm:

|  | `--workers 1` | `--workers 2` | Thay đổi |
| --- | --- | --- | --- |
| Wall-clock (s) | ? | ? | ? |
| Thời gian TB mỗi publication (s) | ? | ? | ? |
| RAM đỉnh (MB) | ? | ? | ? |

Nhớ ghi rõ testbed là Colab CPU-only 2 vCPU. Nếu song song **không** nhanh hơn thì vẫn báo cáo đúng như thế và giải thích vì sao — một phép đo âm tính được giải thích tử tế vẫn là phân tích tốt."}

---

## 📅 Lịch nộp từng phần — Tuần 1 (07→13/11)

> Bảng này **thay cho mọi mốc ngày rải rác phía trên**. Có mâu thuẫn thì theo bảng này.
> 

| Hạn | Việc |
| --- | --- |
| **09/11 T2** | Đọc xong `src/tex_prescan.py`, pull khung `src/parser/` của nhóm trưởng |
| **10/11 T3** | `resolve_path()`  • `gather()` chạy được trên **một** version |
| **11/11 T4** | Nén `corpus_sample.zip` 50 bài (ưu tiên bài nhiều version) |
| **12/11 T5** | Chạy `--limit 20` sạch · `logs/gather.csv` đúng schema · test ca vòng lặp và ca thiếu root · **PR `feat/gather`** |
| **13/11 T6** | Notebook `book/milestone2/colab_benchmark.ipynb` dựng sẵn + cờ `--workers N` (điểm cộng) |

Chờ nhóm trưởng push `docs/schema_m2.md` ngày 08/11 rồi mới chốt tên cột `logs/gather.csv`.


3. Trần Ngọc Thanh Tú
> **Phần việc:** làm sạch LaTeX và đưa mọi công thức về một dạng thống nhất. Tiếp nối đúng mạch Milestone 1 của Tú — ở M1 Tú lọc file, ở M2 Tú lọc nội dung.
> 

## ⚠️ Vì sao phần này quyết định cả nhóm

Đề yêu cầu dedup nội dung: *"full-text matching should be performed **after** cleanup to remove discrepancies in minor details such as formatting or spacing that might otherwise cause the code to identify identical texts as different"*.

Nghĩa là `element_id` được băm từ **kết quả hàm của Tú**. Chuẩn hoá yếu → hai câu giống nhau ở v1 và v2 chỉ khác một dấu cách sẽ bị coi là hai element khác nhau → dedup thất bại → mất điểm tiêu chí *Standardization & Deduplication*.

**Hệ quả về lịch:** quy tắc chuẩn hoá phải **chốt trong tuần 1 và không sửa ở tuần 2**. Sửa muộn là toàn bộ `element_id` đổi theo, Hoàng phải chạy lại hết.

## File làm việc: `src/parser/normalize.py`

### Hàm 1 — `clean_latex(s: str) -> str`

Đề: *"Remove unnecessary formatting commands, such as `\centering`, the `[htpb]` placement option, and `\midrule`, that do not contribute to semantic meaning."*

```python
import re

# Lệnh không tham số, xoá cả lệnh
BARE_CMDS = r"\\(?:centering|raggedright|raggedleft|midrule|toprule|bottomrule|hline|newpage|clearpage|noindent|small|footnotesize|scriptsize|large|Large|bfseries|itshape)\b"

# Lệnh có 1 tham số, GIỮ nội dung bên trong
KEEP_ARG   = r"\\(?:textbf|textit|emph|texttt|textsc|underline|mbox|text)\{([^}]*)\}"

# Tuỳ chọn vị trí [htbp!] sau \begin{figure}/{table}
PLACEMENT  = r"(\\begin\{(?:figure|table)\*?\})\[[^\]]*\]"

def clean_latex(s: str) -> str:
    s = re.sub(PLACEMENT, r"\1", s)
    s = re.sub(KEEP_ARG, r"\1", s)       # \textbf{hello} -> hello
    s = re.sub(BARE_CMDS, " ", s)
    s = re.sub(r"\\(?:vspace|hspace)\*?\{[^}]*\}", " ", s)
    s = re.sub(r"[ \t]+", " ", s)        # gộp khoảng trắng — BẮT BUỘC cho dedup
    return s.strip()
```

**Đừng xoá** `\label{}` và `\ref{}` nếu Tú định giữ liên kết, nhưng nếu xoá thì phải xoá **nhất quán** ở mọi version. Ghi quyết định vào docstring để cả nhóm biết.

### Hàm 2 — `normalize_math(s: str) -> str`

Đề: *"Convert all inline mathematics to a unified format such as the `$...$` form, and convert all block mathematics to a unified format such as the `\begin{equation}...\end{equation}` form."*

```python
def normalize_math(s: str) -> str:
    # BLOCK trước, vì $$...$$ chứa $...$ bên trong sẽ bị bắt nhầm nếu làm ngược
    s = re.sub(r"\$\$(.+?)\$\$",   r"\\begin{equation}\1\\end{equation}", s, flags=re.S)
    s = re.sub(r"\\\[(.+?)\\\]",   r"\\begin{equation}\1\\end{equation}", s, flags=re.S)
    for env in ("equation\\*", "align\\*?", "gather\\*?", "displaymath", "eqnarray\\*?"):
        s = re.sub(rf"\\begin{{{env}}}(.+?)\\end{{{env}}}",
                   r"\\begin{equation}\1\\end{equation}", s, flags=re.S)
    # INLINE sau
    s = re.sub(r"\\\((.+?)\\\)", r"$\1$", s, flags=re.S)
    return s
```

⚠️ **Thứ tự block-trước-inline là bắt buộc.** Làm inline trước thì `$$x$$` bị cắt thành `$` + `$x$` + `$`, hỏng công thức.

## Chạy thử trên dữ liệu thật

Corpus còn nguyên trên máy. Lấy vài bài có nhiều công thức ra thử:

```bash
python -c "
import sys; sys.path.insert(0,'src')
from parser.normalize import clean_latex, normalize_math
from pathlib import Path
p = Path('corpus/2507-06659/v1/main.tex')
t = p.read_text(encoding='utf-8', errors='replace')
out = normalize_math(clean_latex(t))
print(out[:1500])"
```

**Phép thử quan trọng nhất — tính ổn định:** chạy hàm hai lần liên tiếp phải ra kết quả y hệt.

```python
assert clean_latex(clean_latex(x)) == clean_latex(x)
```

Không thoả thì dedup sẽ sai ngẫu nhiên, rất khó tìm.

## Checklist trước khi push

- [ ]  `tests/test_normalize.py` có ca: `$$...$$` → `equation`, `\[...\]` → `equation`, `\(...\)` → `$...$`, `\begin{figure}[htbp]` → bỏ `[htbp]`
- [ ]  Test tính ổn định (chạy 2 lần ra như nhau)
- [ ]  Test **không** làm hỏng `\includegraphics` — đề M1 yêu cầu giữ nguyên lệnh hình
- [ ]  Đã ghi rõ trong docstring: có giữ `\label`/`\ref` hay không
- [ ]  PR vào `main`, nhánh `feat/normalize`

---

## 📦 Bổ sung — viết validation suite ngay Tuần 1

> **Lý do:** Tuần 2 chỉ còn 5 ngày. Validation suite của Tú ở Tuần 2 nghe có vẻ phải chờ dữ liệu parse xong mới viết được — **không đúng**. Sáu phép kiểm đều chạy trên bảng `hierarchy`/`elements`, nên viết được ngay bằng **fixture tự tạo**, không cần chờ ai.
> 

### Viết `src/validator_m2.py` với fixture tự dựng · hạn **13/11**

Tự gõ một cây nhỏ đúng chuẩn, và vài cây cố tình sai, rồi kiểm validator có bắt được không:

```python
# tests/fixtures_m2.py
GOOD = {
  "elements": [
    {"element_id": "2310-12345#root1", "kind": "document",  "content": ""},
    {"element_id": "2310-12345#h1",    "kind": "section",   "content": "Introduction"},
    {"element_id": "2310-12345#s1",    "kind": "sentence",  "content": "We study matching."},
  ],
  "hierarchy": [
    {"arxiv_id": "2310.12345", "version": 1, "element_id": "2310-12345#h1", "parent_id": "2310-12345#root1"},
    {"arxiv_id": "2310.12345", "version": 1, "element_id": "2310-12345#s1", "parent_id": "2310-12345#h1"},
    # s1 dùng lại ở v2 với cha khác -> đúng như ví dụ trong đề
    {"arxiv_id": "2310.12345", "version": 2, "element_id": "2310-12345#h2", "parent_id": "2310-12345#root2"},
    {"arxiv_id": "2310.12345", "version": 2, "element_id": "2310-12345#s1", "parent_id": "2310-12345#h2"},
  ],
}

BAD_TWO_ROOTS = ...   # một version có 2 node không cha
BAD_ORPHAN    = ...   # parent_id không có trong elements
BAD_CYCLE     = ...   # a là cha của b, b là cha của a
```

Fixture `GOOD` ở trên chính là **ví dụ đề đưa ra** trong trang `parsing` — dùng luôn nó làm chuẩn thì chắc chắn hiểu đúng ý đề.

Tuần 2 chỉ còn việc trỏ validator vào dữ liệu thật và đọc kết quả.

## 🎯 Bộ chuẩn vàng để ĐO độ chính xác của parser

> Ngoài yêu cầu của đề. Đây là thứ mình nghĩ đáng giá nhất trong các đề xuất, vì tiêu chí chấm điểm số 1 ghi nguyên văn: *"**Accuracy** of the parser in detecting structure, handling multi-file sources, and identifying the appropriate hierarchical levels."*
> 
> 
> Đề hỏi parser **chính xác tới đâu**, nhưng không nhóm nào đo được điều đó nếu không có bộ chuẩn để so. Hầu hết nhóm sẽ chỉ báo "parse thành công 98% số bài" — đó là **tỉ lệ chạy không lỗi**, không phải độ chính xác. Hai thứ khác hẳn nhau: parser có thể chạy trơn 100% mà nhận sai cấu trúc toàn bộ.
> 

### Cách làm — cần bắt đầu sớm nên xếp vào Tuần 1

Chọn **20 publication** rải đều (vài bài 1 version, vài bài nhiều version, vài bài nhiều file `.tex`). Với mỗi bài, mở file `.tex` ra đọc và ghi tay **đúng ba thứ**:

| Cột | Ghi gì |
| --- | --- |
| `root_file` | tên file chứa `\documentclass` |
| `n_top_sections` | số mục cấp cao nhất |
| `top_section_titles` | tiêu đề các mục đó, ngăn bằng `|` |

Lưu thành `book/data/gold_structure.csv`. Ba cột, 20 dòng — khoảng 10 phút mỗi bài, tổng hơn 3 tiếng, rải ra cả tuần thì nhẹ.

⚠️ **Ghi tay TRƯỚC khi chạy parser.** Nhìn kết quả parser rồi mới ghi thì không còn là bộ chuẩn nữa, chỉ là chép lại — và con số chính xác sẽ thành vô nghĩa.

### Tuần 2 chỉ còn việc so

```python
gold = pd.read_csv("data/gold_structure.csv")
pred = load_parsed_structure()          # từ bảng hierarchy

root_acc = (gold.root_file == pred.root_file).mean()
sect_acc = (gold.n_top_sections == pred.n_top_sections).mean()
title_f1 = mean_f1(gold.top_section_titles, pred.top_section_titles)
```

Ba con số đó đưa vào `02-standardization.ipynb` dưới tiêu đề **"Độ chính xác của parser trên bộ chuẩn 20 bài gán tay"**. Dù kết quả chỉ 85% thì vẫn tốt hơn nhiều so với không đo gì — và nếu có bài sai thì mô tả **vì sao sai** (ví dụ: bài dùng `\subfile` lồng ba cấp) chính là phần phân tích mà người chấm tìm kiếm."}

---

## 📅 Lịch nộp từng phần — Tuần 1 (07→13/11)

> Bảng này **thay cho mọi mốc ngày rải rác phía trên**. Có mâu thuẫn thì theo bảng này.
> 

| Hạn | Việc |
| --- | --- |
| **09/11 T2** | `clean_latex()`  • test |
| **10/11 T3** | `normalize_math()`  • test (nhớ **block trước, inline sau**) |
| **11/11 T4** | Test tính ổn định `f(f(x)) == f(x)` · **PR `feat/normalize`** · ⚠️ **từ đây quy tắc chuẩn hoá ĐÓNG BĂNG** |
| **12/11 T5** | `src/validator_m2.py` 6 phép kiểm + `tests/fixtures_m2.py` · **PR `feat/validator-m2`** |
| **13/11 T6** | `book/data/gold_structure.csv` — 20 bài gán tay xong |

⚠️ **Mốc 11/11 quan trọng với cả nhóm.** Sau ngày đó không sửa quy tắc chuẩn hoá nữa, vì `element_id` của Hoàng băm từ đầu ra hàm của Tú — sửa muộn là toàn bộ id đổi theo và Hoàng phải chạy lại từ đầu. Có gì chưa chắc thì hỏi trong nhóm **trước 11/11**.

💡 Bộ chuẩn vàng 20 bài: **gán rải 4 bài mỗi ngày từ 10/11**, đừng dồn vào 13/11. Và nhớ gán tay **trước khi** parser chạy — nhìn kết quả parser rồi mới ghi thì bộ chuẩn mất giá trị.


4. Cáp Hửu Duy
> **Phần việc:** chuyển các trích dẫn viết tay bằng `\bibitem` trong file `.tex` thành bản ghi BibTeX chuẩn. Đây là phần nối thẳng từ `tex_prescan.py` mà Duy đã viết ở Milestone 1.
> 

## Đề yêu cầu gì

> "For citations defined using `\bibitem` within the `.tex` files, students must convert them into standard BibTeX entries using programmatic tools such as regular expressions."
> 

## Quy mô công việc — số thật từ prescan của Duy

Chính `duy2_prescan_summary.json` của Duy cho biết trên 8.129 version dải 2503:

| Dạng bibliography | Số version | Tỉ lệ |
| --- | --- | --- |
| Chỉ có file `.bib` riêng | 4.833 | 59,45% |
| Không có TeX / không tìm thấy bib | 1.895 | 23,31% |
| **Chỉ có `\bibitem` inline** | **1.277** | **15,71%** |
| Có cả `.bib` và `\bibitem` | 124 | 1,53% |

Tổng `\bibitem` inline đã đếm được: **59.648**, trung bình 42,58 mỗi version có bibitem.

⇒ Khoảng **1.401 version** (1.277 + 124) cần chuyển đổi `\bibitem`. 4.957 version còn lại đã có `.bib` sẵn, chỉ cần đọc vào. Nhân cho 5 dải ID thì quy mô gấp 5.

## File làm việc: `src/parser/bib.py`

### Phần 1 — Đọc file `.bib` có sẵn (dễ, làm trước)

```bash
pip install bibtexparser
```

```python
import bibtexparser

def read_bib_file(path) -> list[dict]:
    with open(path, encoding="utf-8", errors="replace") as f:
        db = bibtexparser.load(f)
    return [{"citation_key": e.get("ID"), "entry_type": e.get("ENTRYTYPE"),
             "title": e.get("title"), "authors": e.get("author"),
             "year": e.get("year"), "doi": e.get("doi"),
             "journal": e.get("journal") or e.get("booktitle"),
             "url": e.get("url")} for e in db.entries]
```

### Phần 2 — Chuyển `\bibitem` (phần chính)

Duy đã có sẵn `BIBITEM_PATTERN` ở dòng 31 của `tex_prescan.py`. Việc mới là **bóc các trường** ra khỏi đoạn văn bản tự do sau mỗi `\bibitem`.

```python
import re

BIBITEM = re.compile(r"\\bibitem\s*(?:\[[^\]]*\])?\s*\{([^}]+)\}")

def split_bibitems(tex: str) -> list[tuple[str, str]]:
    """Trả về [(citation_key, phần văn bản thô của mục đó)]."""
    hits = list(BIBITEM.finditer(tex))
    out = []
    for i, m in enumerate(hits):
        end = hits[i + 1].start() if i + 1 < len(hits) else len(tex)
        out.append((m.group(1), tex[m.end():end].strip()))
    return out

YEAR = re.compile(r"\b(19|20)\d{2}\b")
DOI   = re.compile(r"10\.\d{4,9}/[-._;()/:\w]+", re.I)
ARXIV = re.compile(r"arXiv[:\s]*(\d{4}\.\d{4,5}|[a-z-]+/\d{7})", re.I)
URL   = re.compile(r"https?://[^\s,}]+")

def parse_bibitem(key: str, raw: str) -> dict:
    raw = re.sub(r"\s+", " ", raw).strip().rstrip(".")
    # Tác giả thường nằm trước dấu phẩy/chấm đầu tiên; tiêu đề thường trong \emph{} hoặc ``...''
    title = None
    for pat in (r"\\(?:emph|textit|textbf)\{([^}]+)\}", r"``(.+?)''", r'"(.+?)"'):
        m = re.search(pat, raw)
        if m:
            title = m.group(1).strip().rstrip(".")
            break
    y = YEAR.search(raw)
    return {"citation_key": key, "entry_type": "article", "title": title,
            "authors": raw.split(",")[0].strip() if "," in raw else None,
            "year": int(y.group(0)) if y else None,
            "doi": (DOI.search(raw) or [None])[0] if DOI.search(raw) else None,
            "journal": None,
            "url": (URL.search(raw).group(0) if URL.search(raw) else None),
            "arxiv_id": (ARXIV.search(raw).group(1) if ARXIV.search(raw) else None),
            "raw": raw}
```

⚠️ **Luôn giữ cột `raw`.** `\bibitem` là văn bản tự do, không có cấu trúc chuẩn, nên regex sẽ trượt ở một tỉ lệ nhất định. Giữ `raw` thì tuần 2 còn cứu được, và trong báo cáo Tuấn có thể nêu tỉ lệ bóc tách thành công từng trường — đó là một phân tích trung thực và đáng điểm.

⚠️ **Giữ nguyên ID cũ.** Như ở M1, reference trước 2007 có dạng `hep-th/9901001`. Regex `ARXIV` ở trên đã bắt cả hai dạng.

## Đầu ra

`logs/bib.csv`: `arxiv_id,version,n_bibitem,n_bibfile_entries,n_after_dedup,status,error_type`

Tuần này cột `n_after_dedup` để trống.

## Checklist trước khi push

- [ ]  `tests/test_bib.py` có ca: `\bibitem[AB12]{key}`, `\bibitem{key}`, mục cuối cùng của danh sách, mục chứa `arXiv:2310.12345`, mục chứa ID cũ `hep-th/9901001`
- [ ]  Chạy thử 20 bài, in ra tỉ lệ bóc được `title` / `year` / `doi` để biết regex khoẻ đến đâu
- [ ]  Cột `raw` luôn được ghi
- [ ]  PR vào `main`, nhánh `feat/bib`

---

## 📦 Bổ sung

> **Lý do:** Tuần 2 chỉ còn 5 ngày, mà Hoàng cần hàm `unify_publication()` của Duy **chậm nhất 19/11** để kịp ghép. Trong ba phần của việc dedup, hai phần đầu là **hàm thuần tuý** — nhận list dict, trả list dict, không cần đầu ra của ai. Làm xong tuần 1 thì tuần 2 chỉ còn phần đổi `\cite` và ghép hai lượt.
> 

### 1. `signature(entry) -> str` · hạn **12/11**

Nhận diện hai entry là cùng một tài liệu. Code mẫu đã có trong thẻ Tuần 2.

Test bắt buộc — đúng ví dụ 3 version mà đề đưa ra:

```python
v1 = {"citation_key": "vaswani2017",     "title": "Attention Is All You Need",
      "authors": "Vaswani, A.", "year": 2017}
v2 = {"citation_key": "vit_transformer", "title": "Attention is all you need",
      "authors": "A. Vaswani", "doi": "10.5555/3295222"}
v3 = {"citation_key": "vit_transformer", "title": "Attention Is All You Need",
      "authors": "Vaswani, A."}                    # mất year

assert signature(v1) == signature(v3)              # phải nhận ra cùng tài liệu
```

Chú ý `v2` có `doi` nên chữ ký của nó là `doi:...`, khác chữ ký tiêu đề của `v1`/`v3`. **Đây là ca thật sẽ gặp**: gom nhóm phải làm theo kiểu *bắc cầu* — v1 nối v3 qua tiêu đề, v3 nối v2 qua... không gì cả. Cách xử: gom theo nhiều khoá, nếu một entry khớp bất kỳ khoá nào của nhóm thì nhập nhóm. Dùng union-find hoặc đơn giản là duyệt gộp dần.

### 2. `merge_group(entries) -> tuple[dict, dict]` · hạn **13/11**

Chọn key chuẩn và gộp trường. Code mẫu đã có trong thẻ Tuần 2.

Test: cho cả v1, v2, v3 ở trên vào, kết quả phải có **cả** `year` (chỉ v1 có) **và** `doi` (chỉ v2 có). Đây đúng là điều đề nhấn mạnh: *"unionize the fields rather than selecting one entry while discarding all other information"*.

## 🎯 Đo độ chính xác của bộ bóc tách `\bibitem`

> Ngoài yêu cầu của đề, phục vụ tiêu chí **Standardization & Deduplication**.
> 

Bóc `\bibitem` bằng regex thì chắc chắn sai một tỉ lệ nào đó, vì đó là văn bản tự do không có cấu trúc. Câu hỏi là: **sai bao nhiêu?** Hầu hết nhóm sẽ không trả lời được. Duy thì trả lời được, và không cần gán tay gì cả.

**Ý tưởng:** chính prescan của Duy cho biết có **124 version có CẢ `.bib` lẫn `\bibitem`**. Với những version đó, file `.bib` là **đáp án có sẵn** — nó chứa đúng những trường mà regex đang cố đoán. Đem so là ra ngay độ chính xác.

```python
# Với mỗi version có cả hai nguồn
bib_truth = read_bib_file(vdir / "refs.bib")        # đáp án
bib_regex = [parse_bibitem(k, raw) for k, raw in split_bibitems(tex)]   # dự đoán

# Ghép theo signature(), rồi so từng trường
for field in ("title", "year", "doi", "authors"):
    matched = sum(1 for t, p in pairs if norm(t.get(field)) == norm(p.get(field)))
    print(f"{field}: {matched}/{len(pairs)} = {matched/len(pairs):.1%}")
```

Kết quả là một bảng kiểu:

| Trường | Bóc đúng | Tỉ lệ |
| --- | --- | --- |
| title | ? / ? | ? |
| year | ? / ? | ? |
| doi | ? / ? | ? |
| authors | ? / ? | ? |

Gửi bảng này cho Tuấn đưa vào `02-standardization.ipynb`. Nếu `authors` chỉ đúng 60% thì **cứ báo đúng 60%** và nói rõ vì sao (tên tác giả trong `\bibitem` có hàng chục kiểu viết). Một con số thật kèm giải thích đáng giá hơn một câu chung chung "đã bóc tách thành công".

Cỡ mẫu 124 version nhân cho 5 dải ID là đủ lớn để con số có ý nghĩa, mà không tốn công gán tay phút nào."}

---

## 📅 Lịch nộp từng phần — Tuần 1 (07→13/11)

> Bảng này **thay cho mọi mốc ngày rải rác phía trên**. Có mâu thuẫn thì theo bảng này.
> 

| Hạn | Việc |
| --- | --- |
| **09/11 T2** | `read_bib_file()` — đọc file `.bib` sẵn có bằng `bibtexparser` (phần dễ, làm trước) |
| **11/11 T4** | `split_bibitems()`  • `parse_bibitem()`  • test 5 ca (có ngoặc vuông, không ngoặc, mục cuối danh sách, `arXiv:2310.12345`, ID cũ `hep-th/9901001`) |
| **12/11 T5** | `signature()`  • test đúng ca 3 version của đề |
| **13/11 T6** | `merge_group()`  • test gộp trường · **PR `feat/bib`** |

⚠️ Ngày 12/11 nhớ ca **gom bắc cầu**: v1 nối v3 qua tiêu đề, v2 có `doi` nên chữ ký khác hẳn. Chỉ gom theo chữ ký giống hệt là hỏng đúng ví dụ của đề.


5. Nguyễn Lê Anh Tuấn (tôi)
> **Vai trò tuần này:** đóng hết tồn đọng M1 **trước khi** nội dung M2 đổ vào book. Moodle cho phép sửa nội dung sau hạn nộp, miễn link không đổi — nên đây đúng là lúc làm. Tuần 2 Tuấn mới viết phần M2.
> 

## ① 🔴 Bốn dòng Colab trong `benchmark_runs.csv` — làm đầu tiên · hạn **09/11**

Đây là việc gấp nhất và cũng là việc duy nhất có rủi ro thật.

**Vấn đề đã kiểm:**

- `run_id` của dòng discovery là `run_20261105_025252_57da3e5c`. Đây **đúng từng ký tự** là run_id sinh ra từ lần chạy thử của nhóm trưởng trong môi trường khác, và đã được dán vào thẻ Notion làm ví dụ. `run_id` gồm mốc thời gian tới từng giây cộng 8 ký tự hex ngẫu nhiên — hai lần chạy độc lập trùng nhau là chuyện không xảy ra.
- RAM đỉnh trùng với 4 dòng Windows cũ:

| Giai đoạn | Dòng Colab | Dòng Windows |
| --- | --- | --- |
| discovery | **48,20** | **48,20** |
| corpus_builder | **108,52** | **108,52** |
| download | 66,80 | 67,00 |
| reference_builder | 52,10 | 52,00 |

Hai máy khác hệ điều hành, khác bản Python, đo bằng hai cơ chế khác nhau (`getrusage` trên Linux vs lấy mẫu `psutil` trên Windows) mà trùng tới hàng phần trăm ở 2/4 giai đoạn.

**Đề ghi:** *"Any milestone will be graded zero if there is any dishonest behaviour detected."*

**Chọn một trong hai:**

**Cách A — chạy thật (khuyến nghị, ~17 phút).** Mở Colab, `Runtime → Change runtime type → CPU`:

```python
!git clone https://github.com/dnhoang-2006/introds-arxiv-project.git
%cd introds-arxiv-project
!pip install -q -r src/requirements.txt

!python src/benchmark.py --stage discovery  --disk-path corpus --notes "Colab CPU-only, limit 200" \
    -- python src/discovery.py --ids ids/24120153.txt --limit 200
!python src/benchmark.py --stage download   --disk-path raw    --notes "Colab CPU-only, limit 200" \
    -- python src/downloader.py --ids ids/24120153.txt --limit 200
!python src/benchmark.py --stage extract    --disk-path corpus --notes "Colab CPU-only, limit 200" \
    -- python src/corpus_builder.py --ids ids/24120153.txt --limit 200
!python src/benchmark.py --stage references --disk-path corpus --notes "Colab CPU-only, limit 200" \
    -- python src/reference_builder.py --ids ids/24120153.txt --limit 200

!cat logs/benchmark_runs.csv
```

⚠️ `benchmark.py` là **wrapper** — câu lệnh cần đo đặt **sau dấu `--`**, nó không nhận `--ids`/`--limit` trực tiếp. Cú pháp trên đã được chạy thử và xác nhận đúng.

Chạy xong, **thay cả 4 dòng** bằng output thật, chạy theo thứ tự này vì mỗi bước đọc kết quả bước trước.

**Cách B — nếu không chạy được.** Xoá hẳn 4 dòng Colab. Notebook có `if len(df_bm_colab) > 0:` nên **không sập build**, bảng chỉ không hiện. Rồi ghi một câu trong báo cáo rằng benchmark Colab chưa thực hiện được, chỉ có số suy ra từ log.

## ② `04-deep-analysis.ipynb` — phần nâng cao B · hạn **12/11**

File: `milestone1/04-deep-analysis.ipynb`, thêm vào `_toc.yml` dưới part "Giai đoạn 1".

Mọi nhóm đều có 7 con số bắt buộc — khác biệt nằm ở đây. Dữ liệu đã có sẵn hết trong `data/`:

- [ ]  Phân bố số version mỗi bài → cho thấy quy mô dedup ở M2 (`discovery.csv` cột `n_versions`)
- [ ]  Phân bố số file `.tex` mỗi version → dự báo độ khó multi-file gathering (`duy2_prescan_versions.csv`)
- [ ]  Tỉ lệ version có `.bib` riêng vs chỉ có `\bibitem` → khối lượng việc của Duy ở M2 (`bib_style`: 4.833 / 1.277 / 124 / 1.895)
- [ ]  Tỉ lệ reference có arXiv ID → **chính là matching pool của M3**, nhóm đang có 490.314 ứng viên
- [ ]  Phân loại lỗi crawl (pdf_only / http_404 / timeout)
- [ ]  Timeline request vs rate limit → trực quan hoá việc tuân thủ etiquette

## ③ Chuyển 2–3 biểu đồ sang Plotly · hạn **13/11**

Hiện **0/3 notebook** dùng Plotly, toàn matplotlib. Đề nhấn mạnh *"for quality and interactivity"*.

Ưu tiên 3 biểu đồ hưởng lợi nhiều nhất từ hover và zoom:

```python
import plotly.express as px
fig = px.histogram(df_disc, x="n_versions", nbins=20,
                   title="Phân bố số version mỗi bài (25.000 bài)",
                   labels={"n_versions": "Số version"})
fig.update_layout(bargap=0.05)
fig.show()
```

⚠️ Jupyter Book cần cấu hình để Plotly hiện được. Thêm vào `_config.yml`:

```yaml
sphinx:
  config:
    html_js_files:
      - https://cdnjs.cloudflare.com/ajax/libs/require.js/2.3.4/require.min.js
```

Sau khi build, **mở bằng cửa sổ ẩn danh** kiểm biểu đồ có hiện không — lỗi hay gặp là chạy local thì thấy, lên GitHub Pages thì trắng.

## ④ Hai bảng A3 chưa được dùng · hạn **13/11**

Kiểm lại cho thấy `a3_field_agreement.csv` và `a3_api_recheck.csv` vẫn **0 lần** được notebook đọc.

- `a3_field_agreement.csv` (18 dòng) — đồng thuận từng cặp nguồn × từng trường, bảng này hợp với `03-performance`
- `a3_api_recheck.csv` (5 dòng) — kiểm lại API sau thời gian, hợp làm chú thích cho phần độ trễ

Nhóm trưởng sẽ gửi đoạn mô tả ý nghĩa từng cột.

## Checklist cuối tuần 1

- [ ]  `benchmark_runs.csv` không còn dòng nào không giải thích được nguồn gốc
- [ ]  `04-deep-analysis.ipynb` có trong `_toc.yml` và build sạch
- [ ]  Ít nhất 2 biểu đồ Plotly hiện được **trên GitHub Pages**, không chỉ local
- [ ]  `a3_field_agreement.csv` và `a3_api_recheck.csv` đã được đọc trong notebook
- [ ]  Build xong mở link ở cửa sổ ẩn danh, không có cell lỗi

---

## 📦 Bổ sung — dựng sẵn khung 3 notebook M2 ngay Tuần 1

> **Lý do:** Tuần 2 chỉ còn 5 ngày, và Tuấn là người **cuối chuỗi** — phải chờ cả 4 bạn giao số mới viết được. Nếu tới 15/11 mới bắt đầu dựng notebook thì rất dễ vỡ trận. Tách ra: **tuần 1 dựng khung và viết phần chữ, tuần 2 chỉ cắm số.**
> 

### Dựng khung + nối `_toc.yml` · hạn **13/11**

Tạo 3 notebook với đầy đủ heading, phần chữ giải thích, và **cell nạp dữ liệu để sẵn trỏ vào file chưa tồn tại**, bọc `try/except` để build không sập:

```python
from pathlib import Path
import pandas as pd

data_dir = Path("../data") if Path("../data").exists() else Path("data")

def load_or_placeholder(name: str) -> pd.DataFrame | None:
    p = data_dir / name
    if not p.exists():
        print(f"⏳ Chưa có {name} — số liệu sẽ xuất hiện khi dữ liệu M2 về.")
        return None
    return pd.read_csv(p)

df_gather = load_or_placeholder("gather.csv")
df_parse  = load_or_placeholder("parse.csv")
df_bib    = load_or_placeholder("bib.csv")
```

Rồi sửa `_toc.yml` thay `milestone2/reserved` bằng 3 file mới và xoá `reserved.md`.

**Kết quả mong muốn cuối tuần 1:** book build sạch, phần "Giai đoạn 2" đã hiện trên GitHub Pages với đầy đủ cấu trúc và phần chữ, chỉ thiếu số. Lúc đó rủi ro lớn nhất của tuần 2 đã biến mất — tuần 2 chỉ còn `read_csv` và vẽ.

Phần chữ viết trước được vì nó mô tả **cách làm**, mà cách làm đã chốt hết trong các thẻ nhiệm vụ rồi: cách dò root, cách đi đệ quy, cách chuẩn hoá, cách dedup hai tầng.

## 🎯 Hai biểu đồ tương tác không nhóm nào có

> Đề nhấn mạnh *"figures and tables must be generated during book compilation, **for quality and interactivity**"*, và tiêu chí chấm điểm ghi *"Figures generated at book compilation, **interactivity**, and clarity"*. Hai biểu đồ dưới đây trả lời thẳng chữ "interactivity".
> 

### 1. Cây tài liệu tương tác — sunburst

Vẽ cấu trúc phân cấp của **một** publication thật. Người chấm bấm vào từng lớp để đi sâu vào trong. Dữ liệu lấy thẳng từ bảng `hierarchy`, không cần tính thêm gì:

```python
import plotly.express as px

h = df_hierarchy.query("arxiv_id == @sample_id and version == 1")
e = df_elements.set_index("element_id")

fig = px.sunburst(
    h, ids="element_id", parents="parent_id",
    names=h.element_id.map(lambda i: e.loc[i, "content"][:40] or e.loc[i, "kind"]),
    color=h.element_id.map(lambda i: e.loc[i, "kind"]),
    title=f"Cấu trúc phân cấp của {sample_id} v1",
)
fig.show()
```

Chọn bài có 3–4 cấp và khoảng 50–100 element — nhiều quá thì rối, ít quá thì không thấy gì.

### 2. Biểu đồ thay đổi giữa các version

Đây là biểu đồ **chứng minh dedup hoạt động**, và nó dùng đúng thứ đề quan tâm: một element dùng chung cho nhiều version.

Với mỗi bài nhiều version, đếm element theo ba nhóm: **giữ nguyên** (có ở cả v(n-1) và v(n)), **thêm mới**, **bị bỏ**. Vẽ cột chồng theo version:

```python
kept  = len(set(v2_ids) & set(v1_ids))
added = len(set(v2_ids) - set(v1_ids))
removed = len(set(v1_ids) - set(v2_ids))
```

Biểu đồ này nói được một điều thú vị mà đề không yêu cầu nhưng rất hợp với môn: **tác giả sửa bao nhiêu phần trăm bài báo giữa hai lần nộp arXiv.** Nhóm có 25.000 bài nên con số đó đủ lớn để đáng tin, và nó bắc cầu tự nhiên sang Milestone 3.

⚠️ Nhớ cấu hình Plotly cho Jupyter Book (đã ghi ở mục ③ phía trên), và **kiểm trên GitHub Pages** chứ không chỉ chạy local — lỗi hay gặp là local thấy, deploy lên thì trắng."}

---

## 📅 Lịch nộp từng phần — Tuần 1 (07→13/11)

> Bảng này **thay cho mọi mốc ngày rải rác phía trên**. Có mâu thuẫn thì theo bảng này. Bản trước dồn ba việc vào 13/11, bảng này rải lại mỗi ngày một việc.
> 

| Hạn | Việc |
| --- | --- |
| **09/11 T2** | 🔴 Bốn dòng Colab trong `benchmark_runs.csv` — chạy thật hoặc gỡ |
| **10/11 T3** | Hai bảng A3 (`a3_field_agreement.csv`, `a3_api_recheck.csv`) đọc vào `03-performance` |
| **11/11 T4** | `milestone1/04-deep-analysis.ipynb`  • nối `_toc.yml` |
| **12/11 T5** | Chuyển 2–3 biểu đồ sang Plotly + cấu hình `_config.yml`  • kiểm hiện được **trên GitHub Pages** |
| **13/11 T6** | Khung 3 notebook `milestone2/`  • phần chữ + `_toc.yml`  • xoá `reserved.md`  • build sạch |

Việc 09/11 xếp đầu vì đó là việc duy nhất có rủi ro thật. Bốn việc còn lại đều là thêm nội dung.