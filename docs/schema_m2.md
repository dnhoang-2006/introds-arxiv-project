# HỢP ĐỒNG DỮ LIỆU — Milestone 2 (Hierarchical Parsing & Standardization)

> **Đây là file quan trọng nhất của Milestone 2.** Mọi module của 5 thành viên đọc/ghi theo đúng
> quy ước dưới đây. Ai muốn đổi một trường nào đó → báo nhóm, cả nhóm duyệt, rồi mới sửa file này.
>
> Chốt ngày: **08/11/2026** · Người giữ file: Nhóm trưởng (24120053)
>
> File này nối tiếp `docs/schema.md` của Milestone 1. Mọi quy ước ở M1 còn hiệu lực:
> `arxiv_id` là bản gốc không có version, `pub_key` là tên thư mục, `config.pub_key()` là hàm
> duy nhất được dùng để chuyển đổi.

---

## 1. Ba bảng đầu ra

Đề đã quy định sẵn. Chép lại nguyên văn để không ai phải mở lại đề:

### 1.1. Bảng `elements`

Một dòng cho mỗi element **khác nhau** trên toàn bộ các version của một publication.

| Cột | Kiểu | Null? | Ghi chú |
|---|---|---|---|
| `element_id` | string | không | Xem mục 2 |
| `arxiv_id` | string | không | Bản gốc, chưa đổi dấu |
| `kind` | string | không | Chỉ nhận giá trị ở mục 3 |
| `content` | string | không | **Nội dung đã chuẩn hoá**, xem mục 4 |

> Nội dung khớp nhau giữa các version — khớp toàn văn **sau khi chuẩn hoá** — chiếm **một dòng duy nhất**.

### 1.2. Bảng `hierarchy`

Một dòng cho mỗi cạnh node → cha, **của từng version**.

| Cột | Kiểu | Null? | Ghi chú |
|---|---|---|---|
| `arxiv_id` | string | không | |
| `version` | int | không | 1, 2, 3… |
| `element_id` | string | không | Node con |
| `parent_id` | string | không | Node cha |

**`[QUYẾT ĐỊNH]` Node gốc không có dòng trong `hierarchy`.** Đề ghi *"one row per node-parent edge"* —
gốc không có cha nên không có cạnh. Nó chỉ xuất hiện ở cột `parent_id` của các con.
Hệ quả: tìm gốc của một version = `set(parent_id) - set(element_id)`, và tập đó phải có **đúng một**
phần tử. Đây chính là phép kiểm số 1 của validation suite.

### 1.3. Bảng `bibtex`

Các entry BibTeX **sau khi đã gộp và khử trùng lặp**.

| Cột | Kiểu | Null? |
|---|---|---|
| `arxiv_id` | string | không |
| `citation_key` | string | không |
| `entry_type` | string | không |
| `title` | string | có |
| `authors` | list[string] | có |
| `year` | int | **có** |
| `doi` | string | có |
| `journal` | string | có |
| `url` | string | có |

---

## 2. Quy tắc sinh `element_id`

Đề ghi: *"Element IDs begin with the publication key followed by a discriminant that is unique
inside the publication."*

**`[QUYẾT ĐỊNH]` Discriminant là mã băm của chính nội dung đã chuẩn hoá.**

```python
import hashlib

KIND_CODE = {
    "document": "doc", "section": "sec", "subsection": "sub",
    "subsubsection": "ssb", "paragraph": "par", "itemize": "itz",
    "item": "itm", "sentence": "snt", "formula": "eqn", "figure": "fig",
}

def element_uid(pub_key: str, kind: str, clean_content: str) -> str:
    """2310-12345#snt_a3f9c201

    Băm CẢ kind lẫn nội dung: hai element khác loại mà trùng chữ vẫn ra id khác nhau.
    """
    payload = f"{kind}\x00{clean_content}".encode("utf-8")
    h = hashlib.sha1(payload).hexdigest()[:8]
    return f"{pub_key}#{KIND_CODE[kind]}_{h}"
```

Hàm thật nằm ở `src/parser/elements.py`. **Không ai tự nối chuỗi id** — luôn gọi `element_uid()`.

**Vì sao băm nội dung thay vì đánh số tăng dần:** dedup xảy ra **tự động**. Hai version có cùng một
câu thì tự ra cùng một id, không cần bước so khớp riêng. Đây đúng là yêu cầu của đề:
*"If an element's text content matches exactly across different versions… it should be represented
by a single identifier."*

### ⚠️ Hai hệ quả bắt buộc nhớ

**(a) Băm chạy SAU khi chuẩn hoá.** Đề: *"full-text matching should be performed **after** cleanup"*.
Đầu vào của hàm băm là đầu ra của `normalize.py`. Nên **quy tắc chuẩn hoá đóng băng từ 11/11**,
sau ngày đó không sửa nữa — sửa là toàn bộ id đổi theo và phải parse lại từ đầu.

**(b) Băm chạy SAU khi đổi tên `\cite`.** Xem mục 5.

### Node gốc của mỗi version

**`[QUYẾT ĐỊNH]` `content` của node gốc là `f"{arxiv_id}v{version}"`.**

Lý do: nếu để rỗng thì gốc của v1 và v2 băm ra cùng một id và bị gộp làm một, trong khi ví dụ của đề
cho thấy rõ hai gốc riêng (`#root1` và `#root2`). Gắn version vào nội dung làm chúng tự tách ra.

```python
root_content = f"{arxiv_id}v{version}"     # ví dụ: "2310.12345v2"
root_id = element_uid(pub_key, "document", root_content)
```

---

## 3. Giá trị hợp lệ của `kind`

Dùng **đúng** các chuỗi này, không thêm không bớt — để thống kê gộp được:

`document` · `section` · `subsection` · `subsubsection` · `paragraph` · `itemize` · `item` ·
`sentence` · `formula` · `figure`

**Không có `table`.** Đề gộp bảng vào hình: *"Figures, with **Tables** also considered a type of
Figure for this purpose"* → `\begin{table}` cũng ghi `kind = "figure"`.

**Cấp độ section không cố định.** Đề: *"the parser is required to **automatically identify** the
appropriate hierarchical level"*. Bài dùng lớp `book` có `\chapter` trên `\section`; bài dùng lớp
`article` thì không. Cấp độ được suy **từ chính tài liệu đó** — xem `hierarchy.infer_levels()`.

---

## 4. Chuẩn hoá nội dung

Hai hàm trong `src/parser/normalize.py`, chạy theo đúng thứ tự:

```python
clean = normalize_math(clean_latex(raw))
```

**`clean_latex`** — bỏ lệnh định dạng không mang nghĩa (`\centering`, `\midrule`, `[htbp]`…),
giữ nội dung bên trong các lệnh như `\textbf{...}`, gộp khoảng trắng về một dấu cách.

**`normalize_math`** — mọi công thức inline về dạng `$...$`, mọi công thức khối về dạng
`\begin{equation}...\end{equation}`. **Xử lý khối trước, inline sau** — làm ngược thì `$$x$$`
bị cắt sai.

**Giữ nguyên `\includegraphics` và môi trường `figure`.** Đề M1 đã yêu cầu điều này và M2 không đổi.

**Tính ổn định là bắt buộc:** `f(f(x)) == f(x)`. Không thoả thì dedup sai ngẫu nhiên, rất khó tìm.

---

## 5. Thứ tự chạy pipeline

**`[QUYẾT ĐỊNH]` Thứ tự này là bắt buộc, cho mỗi publication:**

| Bước | Ai | Hàm | Làm gì |
|---|---|---|---|
| 1 | Minh Thư | `gather.gather()` | Tìm đường biên dịch của từng version |
| 2 | Thanh Tú | `normalize.clean_latex` + `normalize_math` | Chuẩn hoá toàn văn từng version |
| 3 | Hửu Duy | `bib_dedup.unify_publication()` lượt 1 | Đọc bib **tất cả** version → dựng `rename_map` |
| 4 | Hửu Duy | `bib_dedup.unify_publication()` lượt 2 | Đổi `\cite` trên văn bản đã chuẩn hoá |
| 5 | Nhóm trưởng | `hierarchy` + `elements` | Dựng cây và **băm** trên văn bản ra từ bước 4 |

**Vì sao bước 3–4 phải hai lượt:** `rename_map` chỉ dựng được khi đã đọc hết mọi version của bài đó,
nên không thể vừa đọc vừa đổi tên trong một lượt.

**Vì sao đổi `\cite` phải trước khi băm:** hai câu giống hệt nhau ở v1 và v2, nhưng v1 viết
`\cite{vaswani2017}` còn v2 viết `\cite{vit_transformer}` (cùng trỏ một tài liệu), sẽ băm ra hai
`element_id` khác nhau → dedup thất bại ngay ở loại câu phổ biến nhất trong bài báo.

### Ba quy tắc con

**`[QUYẾT ĐỊNH]` Chọn citation key chuẩn — tất định:** version nhỏ nhất trước → key ngắn hơn →
thứ tự chữ cái. Chạy lại phải ra cùng kết quả, không phụ thuộc thứ tự duyệt `dict`.

**`[QUYẾT ĐỊNH]` Key trong `\cite{}` nhiều key được sort và bỏ trùng.** `\cite{b,a}` ở v1 và
`\cite{a,b}` ở v2 là cùng nội dung; không sort thì vẫn băm ra hai id khác nhau. Cột `content` là bản
**đã chuẩn hoá**, không phải bản sao nguyên văn của tác giả, nên sắp lại thứ tự là chấp nhận được.

**`[QUYẾT ĐỊNH]` `\cite` trỏ vào key không tồn tại (dangling): giữ nguyên**, không bỏ, không báo lỗi.
Nhưng **đếm lại** và đưa vào báo cáo — đó là một chỉ số chất lượng dữ liệu.

---

## 6. Version rỗng

Đề: *"A version without TeX sources, kept as an empty record by Milestone 1, yields no parsed
elements: **record the version as empty rather than skipping it**."*

**`[QUYẾT ĐỊNH]` Cách ghi:**

- Bảng `elements`: đúng **một** dòng, `kind = "document"`, `content = f"{arxiv_id}v{version}"`
- Bảng `hierarchy`: **không có dòng nào**
- `logs/parse.csv`: một dòng `status = empty`, `n_elements = 1`, các cột đếm còn lại = 0

Nhận biết version rỗng: thư mục version có `_EMPTY.json` (do M1 ghi), hoặc `gather()` trả về
đường biên dịch rỗng.

---

## 7. Nơi lưu kết quả

```
parsed/
└── 2310-12345/                 ← pub_key
    ├── elements.jsonl          ← một element mỗi dòng
    ├── hierarchy.jsonl         ← một cạnh mỗi dòng
    └── bibtex.jsonl            ← một entry mỗi dòng
```

Dùng JSON Lines thay vì CSV vì `authors` là danh sách và `content` chứa dấu phẩy, ngoặc kép,
xuống dòng — CSV sẽ rất dễ hỏng.

`parsed/` **phải nằm trong `.gitignore`** như `corpus/` và `logs/`.

**`[QUYẾT ĐỊNH]` Ghi theo từng publication để chạy lại được từ giữa chừng.** Parse 25.000 bài mất
nhiều giờ; đứt giữa chừng mà phải làm lại từ đầu là rất phí.

```python
def already_done(pub_key: str, out_root: Path) -> bool:
    return (out_root / pub_key / "elements.jsonl").exists()
```

Thêm cờ `--overwrite` để ép chạy lại, giống `discovery.py` ở M1.

---

## 8. Định dạng file log

Đặt trong `logs/`, có header, UTF-8. Giữ nguyên quy ước M1:
`status` ∈ `ok` · `fail` · `empty` · `skipped`; `error_type` **để rỗng** khi `status = ok`;
`seconds` là số thực 2 chữ số thập phân; một dòng = một lần thử.

### `logs/gather.csv` — Minh Thư ghi

```
arxiv_id,version,root_file,n_files_path,n_files_unused,n_missing_includes,seconds,status,error_type
2507.06659,1,main.tex,3,0,0,0.04,ok,
2507.06660,1,,0,2,0,0.01,fail,no_root
```

`error_type` dùng: `no_root` · `empty_version` · `read_error`

### `logs/parse.csv` — nhóm trưởng ghi

```
arxiv_id,version,n_elements,n_sentences,n_formulas,n_figures,max_depth,seconds,status,error_type
2507.06659,1,312,254,11,6,4,1.82,ok,
2507.06661,3,1,0,0,0,0,0.00,empty,
```

### `logs/bib.csv` — Hửu Duy ghi (theo từng version)

```
arxiv_id,version,n_bibitem,n_bibfile_entries,seconds,status,error_type
2507.06659,1,0,42,0.07,ok,
```

### `logs/bib_dedup.csv` — Hửu Duy ghi (theo từng publication)

```
arxiv_id,n_before,n_after,n_cite_renamed,seconds,status,error_type
2507.06659,87,61,14,0.12,ok,
```

**`[QUYẾT ĐỊNH]` Tách `bib_dedup.csv` riêng** vì dedup chạy trên **cả publication**, không phải
trên từng version — nhét con số đó vào bảng theo version sẽ gây hiểu nhầm.

---

## 9. Checklist trước khi commit

- [ ] `git status` không có `corpus/`, `raw/`, `logs/`, `parsed/`, `*.tex`, `*.bib`, `*.tar.gz`
- [ ] Mọi `arxiv_id` là bản gốc, chưa đổi dấu (`2310.12345`, không phải `2310-12345`)
- [ ] `element_id` sinh bằng `element_uid()`, không ai tự nối chuỗi
- [ ] `kind` chỉ dùng 10 giá trị ở mục 3
- [ ] Trường nullable ghi `null`, không ghi `""` hay `"None"`
