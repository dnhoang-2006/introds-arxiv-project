# HỢP ĐỒNG DỮ LIỆU — Milestone 1

> **Đây là file quan trọng nhất của tuần 1.** Mọi module của 5 thành viên đọc/ghi theo đúng
> quy ước dưới đây. Ai muốn đổi một trường nào đó → mở issue, cả nhóm duyệt, rồi mới sửa file này.
>
> Chốt ngày: **21/10/2026** · Người giữ file: Nhóm trưởng

---

## 1. Khóa định danh publication

| Khái niệm | Ví dụ | Dùng ở đâu |
|---|---|---|
| `arxiv_id` (base, **không** có version) | `2310.12345` | Giá trị lưu trong mọi file JSON, cột `arxiv_id` của bảng `papers` / `references` |
| `version` (số nguyên) | `1`, `2`, `3` | Tên thư mục version, cột `version` |
| `versioned_id` | `2310.12345v2` | Chỉ dùng khi gọi endpoint `/src/` |
| `pub_key` (tên thư mục) | `2310-12345` | Tên thư mục trên đĩa |

**ID kiểu cũ (trước 2007)** có dạng `hep-th/9901001`. Dấu `/` không đặt tên thư mục được:

```
hep-th/9901001  →  pub_key = "hep-th_9901001"
```

Quy tắc chuyển: `.` → `-`, `/` → `_`. Hàm `config.pub_key()` làm việc này, **mọi người gọi hàm
đó chứ không tự viết lại**. Giá trị `arxiv_id` bên trong file JSON thì **giữ nguyên bản gốc**
(`hep-th/9901001`), chỉ tên thư mục mới bị đổi.

---

## 2. Cây thư mục corpus

```
corpus/
└── 2310-12345/                  ← pub_key
    ├── paper_meta.json          ← Thanh Tú ghi (từ discovery.py)
    ├── references.json          ← Hữu Duy ghi
    ├── prescan.json             ← Hữu Duy ghi (tuần 2)
    ├── v1/
    │   ├── main.tex
    │   ├── sections/intro.tex   ← giữ nguyên cấu trúc thư mục con trong archive
    │   └── refs.bib
    ├── v2/
    │   └── ...
    └── v3/
        └── _EMPTY.json          ← version không có TeX source
```

**Quy tắc thư mục version:**
- Tên là `v` + số, không zero-pad: `v1`, `v2`, … `v10`.
- Chỉ chứa file `.tex` và `.bib`. Không `.bbl`, không `.sty`, không ảnh.
- Giữ nguyên đường dẫn tương đối bên trong archive (file trong thư mục con thì vẫn nằm trong thư mục con).
- Version không có TeX source **vẫn phải có thư mục**, bên trong đặt `_EMPTY.json`.

**`_EMPTY.json`** (bắt buộc khi version rỗng):

```json
{
  "arxiv_id": "2310.12345",
  "version": 3,
  "reason": "pdf_only",
  "detail": "Archive chứa 1 file PDF, không có .tex",
  "http_status": 200,
  "fetched_at": "2026-10-22T09:14:02+07:00"
}
```

`reason` chỉ được nhận 1 trong các giá trị sau (dùng đúng chuỗi này để thống kê được):
`pdf_only` · `docx_only` · `no_tex_in_archive` · `http_403` · `http_404` · `timeout` · `corrupt_archive` · `other`

---

## 3. `paper_meta.json` — một file mỗi publication

Đủ 6 trường của bảng `papers` (Requirement của đề) + 3 trường phục vụ nội bộ.

```json
{
  "arxiv_id": "2310.12345",
  "title": "Attention Is All You Need Again",
  "authors": ["Jane Doe", "John Smith"],
  "submission_date": "2023-10-19T05:12:33+00:00",
  "revised_dates": ["2023-11-02T11:00:00+00:00"],
  "venue": "NeurIPS 2023",

  "n_versions": 3,
  "latest_versioned_id": "2310.12345v3",
  "discovered_at": "2026-10-21T20:05:11+07:00"
}
```

| Trường | Kiểu | Null? | Ghi chú |
|---|---|---|---|
| `arxiv_id` | string | không | Bản gốc, chưa đổi dấu |
| `title` | string | không | Đã gộp xuống 1 dòng, bỏ xuống dòng thừa |
| `authors` | list[string] | không | Rỗng `[]` nếu API không trả |
| `submission_date` | string ISO 8601 | không | Ngày nộp **v1** (`Result.published`) |
| `revised_dates` | list[string] | không | Xem cảnh báo bên dưới |
| `venue` | string | **có** | `journal_ref`; `null` nếu chưa công bố |
| `n_versions` | int | không | Suy từ suffix của `entry_id` |
| `latest_versioned_id` | string | không | vd `2310.12345v3` |
| `discovered_at` | string ISO | không | Giờ local (+07:00) |

### ⚠️ Cảnh báo về `revised_dates`

arXiv API (Atom) **chỉ trả 2 mốc thời gian**: `published` (v1) và `updated` (bản mới nhất).
Nó **không** trả ngày của từng version trung gian. Vì vậy:

- Bài 1 version → `revised_dates = []`
- Bài N ≥ 2 version → `revised_dates = [updated]`, tức **chỉ có ngày của version cuối**

`discovery.py` ghi thêm cờ `"revised_dates_complete": false` khi `n_versions > 2` để
Thành viên E biết mà ghi chú trong báo cáo. Ai muốn lấy đủ ngày mọi version thì phải
cào trang `abs/` hoặc dùng OAI-PMH — việc đó thuộc phần nâng cao A3, **không bắt buộc** ở tuần 1.

---

## 4. `references.json` — một file mỗi publication

Lưu **TẤT CẢ** reference, kể cả loại không có arXiv ID. Việc lọc chỉ xảy ra khi xuất bảng
`references` ở Milestone 3.

```json
{
  "arxiv_id": "2310.12345",
  "crawled_at": "2026-10-23T10:00:00+07:00",
  "status": "ok",
  "n_total": 42,
  "n_with_arxiv": 17,
  "references": [
    {
      "ref_s2_id": "649def34f8be52c8b66281af98ae884c09aef38b",
      "ref_title": "BERT: Pre-training of Deep Bidirectional Transformers",
      "ref_authors": ["Jacob Devlin", "Ming-Wei Chang"],
      "ref_submission_date": "2018-10-11",
      "ref_arxiv_id": "1810.04805",
      "has_arxiv_id": true,
      "ref_venue": "NAACL",
      "ref_year": 2019
    }
  ]
}
```

- `status` ∈ `ok` · `not_indexed` · `rate_limited` · `error`
- `ref_arxiv_id` = `null` khi không có → `has_arxiv_id = false`
- **Giữ nguyên** ID cũ `hep-th/9901001`, không ép về dạng số
- `ref_submission_date` lấy `publicationDate`; nếu thiếu thì `null` (đừng chế từ `year`)

---

## 5. File log (định dạng CSV, Thành viên E là người tiêu thụ)

Tất cả log đặt trong `logs/`, có header, encoding UTF-8.

### `logs/discovery.csv` — nhóm trưởng ghi
```
arxiv_id,n_versions,status,seconds,error_type
2310.12345,3,ok,1.84,
2310.99999,0,fail,0.52,not_found
```

### `logs/download.csv` — Minh Thư ghi
```
arxiv_id,version,bytes,seconds,status,error_type
2310.12345,1,184320,2.91,ok,
2310.12345,3,0,1.20,empty,pdf_only
```

### `logs/extract.csv` — Thanh Tú ghi
```
arxiv_id,version,bytes_before,bytes_after,n_tex,n_bib,status,error_type
2310.12345,1,184320,41230,3,1,ok,
```
> `bytes_before` = dung lượng archive gốc, `bytes_after` = tổng dung lượng `.tex` + `.bib` giữ lại.
> Hai cột này là nguồn của số liệu **"dung lượng trung bình trước/sau khi bỏ figure"** trong báo cáo.

### `logs/references.csv` — Hữu Duy ghi
```
arxiv_id,n_total,n_with_arxiv,seconds,status,error_type
2310.12345,42,17,1.05,ok,
```

**Quy ước chung cho mọi log:**
- `status` ∈ `ok` · `fail` · `empty` · `skipped`
- `error_type` để **rỗng** khi `status = ok`
- `seconds` là số thực, 2 chữ số thập phân
- Một dòng = một lần thử. Retry thì ghi thêm dòng mới, không sửa dòng cũ.

---

## 6. Danh sách ID đầu vào

Mỗi người có khoảng ID riêng (cột H–K trên sheet đăng ký). Đặt file của mình tại:

```
ids/24120053.txt      ← một ID mỗi dòng, không version suffix
```

Thư mục `ids/` **được commit** (đây là input, không phải data crawl).

---

## 7. Checklist trước khi commit

- [ ] `git status` không hiện file `.tex`, `.tar.gz`, `corpus/`, `logs/`
- [ ] Mọi `arxiv_id` trong JSON là bản gốc, chưa đổi dấu
- [ ] Mọi ngày tháng là chuỗi ISO 8601
- [ ] Trường nullable thì ghi `null`, không ghi `""` hay `"None"`
