# A3 — So sánh 3 nguồn metadata arXiv

Dữ liệu là khoảng ID của nhóm trưởng (`ids/24120053.txt`, 5000 bài `2507.06659`–`2507.11658`).
Chạy ngày 02/11/2026. Cách chạy lại nằm ở mục "Phần nâng cao A3" trong `README.md`.

| Nguồn | Lấy từ | Thời điểm | Số bài |
|---|---|---|---|
| **API** | `paper_meta.json` của `discovery.py` | chạy lại 02/11/2026 (lần đầu 26–27/10) | 5000 |
| **OAI** | `oaipmh.arxiv.org`, định dạng `arXivRaw`, `GetRecord` | 02/11/2026 | 500 (mẫu ngẫu nhiên, seed 42) |
| **Kaggle** | Cornell snapshot | snapshot 01/11/2026 | 5000 |

OAI chỉ lấy mẫu vì 5000 bài cần hơn 4 giờ với pacing 3 giây, và đề không yêu cầu harvest rộng.
Mẫu có 11% bài từ 3 version trở lên, so với 12% trên cả 5000 bài của Kaggle.

## Kết luận

1. **Không nguồn nào thiếu bài.** API và Kaggle có đủ 5000/5000, OAI có đủ 500/500 ID trong mẫu.
2. **OAI và Kaggle khớp hoàn toàn** ở cả 6 trường trên 500 bài, kể cả chuỗi gốc của title và tác giả.
3. **Ngày nộp v1 khớp 100%** giữa cả 3 nguồn.
4. **Chỉ OAI và Kaggle cho biết ngày của từng version.** API chỉ có ngày v1 và ngày bản mới nhất,
   nên 600 bài từ 3 version trở lên trong corpus thiếu ngày các version trung gian.
5. **API có lỗi dữ liệu thật ở 2 trường:** làm sai tên tác giả ở 17 bài và thiếu venue ở 3 bài.
6. **Lệch version là do thời điểm lấy dữ liệu:** chạy lại discovery ngày 02/11 thì 7 bài có thêm
   version mới; còn 1 bài (`2507.10961`) API mới hơn snapshot Kaggle.

## Bảng 1 — Khớp cả 3 nguồn (500 bài chung)

| Trường | Khớp nguyên văn | Khớp sau chuẩn hóa | Lệch thật |
|---|---:|---:|---:|
| title | 491 (98,2%) | 500 (100%) | 0 |
| authors | 482 (96,4%) | 497 (99,4%) | 3 |
| venue (`journal-ref`) | 499 (99,8%) | 499 (99,8%) | 1 |
| ngày nộp v1 | 500 (100%) | 500 (100%) | 0 |
| ngày bản mới nhất | 500 (100%) | 500 (100%) | 0 |
| số version | 500 (100%) | 500 (100%) | 0 |

- **Khớp nguyên văn:** giống nhau sau khi gộp khoảng trắng. Với tác giả, chuỗi của OAI và Kaggle
  được tách thành danh sách và đổi LaTeX sang Unicode trước, vì API trả sẵn danh sách Unicode.
- **Khớp sau chuẩn hóa:** giống nhau sau khi bỏ thêm dấu, hoa/thường, khoảng trắng và dấu câu.
- Venue tính cả 434 bài mà cả 3 nguồn đều không có; 66 bài có venue ở OAI và Kaggle, API có 65.

## Bảng 2 — Khớp theo từng cặp nguồn

| Cặp | Số bài | Trường | Nguyên văn | Chỉ sau chuẩn hóa | Lệch | Chỉ nguồn phải có | Cả hai trống |
|---|---:|---|---:|---:|---:|---:|---:|
| API – OAI | 500 | title | 491 | 9 | 0 | 0 | 0 |
| | | authors | 482 | 15 | 3 | 0 | 0 |
| | | venue | 65 | 0 | 0 | 1 | 434 |
| | | ngày nộp v1 | 500 | 0 | 0 | 0 | 0 |
| | | ngày mới nhất | 500 | 0 | 0 | 0 | 0 |
| | | số version | 500 | 0 | 0 | 0 | 0 |
| API – Kaggle | 5000 | title | 4892 | 107 | 1 | 0 | 0 |
| | | authors | 4850 | 132 | 18 | 0 | 0 |
| | | venue | 727 | 1 | 0 | 3 | 4269 |
| | | ngày nộp v1 | 5000 | 0 | 0 | 0 | 0 |
| | | ngày mới nhất | 4999 | 0 | 1 | 0 | 0 |
| | | số version | 4999 | 0 | 1 | 0 | 0 |
| OAI – Kaggle | 500 | title | 500 | 0 | 0 | 0 | 0 |
| | | authors | 500 | 0 | 0 | 0 | 0 |
| | | venue | 66 | 0 | 0 | 0 | 434 |
| | | ngày nộp v1 | 500 | 0 | 0 | 0 | 0 |
| | | ngày mới nhất | 500 | 0 | 0 | 0 | 0 |
| | | số version | 500 | 0 | 0 | 0 | 0 |

## Bảng 3 — Mỗi nguồn cho biết gì

| | API | OAI (`arXivRaw`) | Kaggle |
|---|---|---|---|
| Số version | Suy từ hậu tố `vN` của ID | Liệt kê từng version | Liệt kê từng version |
| Ngày từng version | Chỉ v1 và bản mới nhất | Có | Có |
| Dung lượng từng version | Không | Có | Không |
| Bài ≥ 3 version có đủ ngày | 0/600 | 55/55 | 600/600 |
| Tên tác giả | Danh sách Unicode, đã qua bộ tách của arXiv | Chuỗi gốc có LaTeX | Chuỗi gốc có LaTeX, kèm `authors_parsed` |
| Title | Macro Hy Lạp và dấu đổi sang Unicode | Chuỗi gốc có LaTeX | Chuỗi gốc có LaTeX |
| Độ mới | Theo lúc gọi | Theo lúc gọi | Theo ngày snapshot |
| Cách lấy một bài | `id_list`, tối đa 100 ID một lần | `GetRecord` từng ID | Quét cả file, khoảng 1 phút |

## Vì sao các nguồn lệch nhau

**Title (107 bài, API – Kaggle):** cùng nội dung, khác cách mã hóa. Ví dụ `$Ω^{-}(2012)$` và
`$\Omega^{-}(2012)$`, `Grünbaum` và `Gr\"unbaum`. Sau chuẩn hóa chỉ còn `2507.10961` lệch vì bản
v5 đổi "Policy" thành "Framework" trong tiêu đề, mà snapshot Kaggle chưa có bản này.

**Tác giả (18 bài, API – Kaggle):**

| Nguyên nhân | Số bài | Ví dụ: API → chuỗi gốc | Nguồn sai |
|---|---:|---|---|
| Làm rơi hậu tố tên | 12 | `Timothy Chase` → `Timothy Chase Jr` | API |
| Tách đôi tên có biệt danh trong ngoặc | 5 | `' Chun-Fu'`, `' Chen'` → `Chun-Fu (Richard) Chen` | API |
| Chuỗi gốc không có dấu phân cách | 1 | 11 tên → một chuỗi, ngăn bằng ngoặc đơn vị | Bộ tách của nhóm |

`authors_parsed` của Kaggle cũng tách đôi tên như API (9 mục cho 8 người ở bài `2507.07149`),
nên muốn đếm tác giả chính xác thì dùng chuỗi `authors`.

**Số version và ngày mới nhất (1 bài):** `2507.10961` có v5 ngày 30/10/2026; API đã có bản này còn
snapshot Kaggle vẫn dừng ở v4. Trước đó, discovery ngày 26–27/10 lệch 6 bài so với Kaggle. Chạy lại
ngày 02/11 thì cả 6 đều khớp; tổng cộng 7 bài có thêm version mới, corpus tăng từ 7844 lên 7851 version.

**Venue (3 bài):**

| Bài | API lúc discovery | API chạy lại 02/11 | OAI, Kaggle | Kết luận |
|---|---|---|---|---|
| `2507.08633`, `2507.10190`, `2507.11208` | trống | trống | `A&A 701, ...` | API thiếu thật |

Hai bài `2507.07164` và `2507.08578` từng lệch venue ở lần discovery đầu, nay API đã có và khớp Kaggle.

Với 3 bài `A&A`, phản hồi Atom gốc của API không có `journal_ref` lẫn `doi`, nên lỗi không nằm ở
thư viện `arxiv` hay `discovery.py`. Nguyên nhân phía arXiv thì chưa rõ.

## Hành vi OAI-PMH sau đợt viết lại 3/2025

Nguồn tài liệu: [arXiv OAI help](https://info.arxiv.org/help/oa/index.html). Phần dưới là quan sát
trực tiếp ngày 02/11/2026, khoảng 16:00–17:00 giờ Việt Nam. Log: `logs/oai_requests.csv`,
`logs/oai_token_checks.csv`.

**Resumption token**

| Câu hỏi | Quan sát |
|---|---|
| Thuộc tính | Chỉ có `expirationDate`, không có `cursor` và `completeListSize` |
| Hạn ghi trên token | `2026-11-03T00:00:00Z`, tức 00:00 UTC hôm sau (07:00 giờ VN) |
| Cỡ trang | 1300 record |
| Nội dung token | Truy vấn gốc đã URL-encode cộng `skip`, ví dụ `...set%3Dphysics%253Ahep-lat%26skip%3D1300`; không chứa ngày |
| Server có lưu token không | Không: token tự sửa `skip` chưa từng được cấp vẫn được chấp nhận, số record trả về đúng bằng `1677 − skip` |
| Token giả | HTTP 200 kèm `badResumptionToken`: "Token decoding failed or format is invalid" |
| Tiếp tục bằng `--resume` | Chạy được: trang 1 có 1300 record, phần tiếp theo có 377 record |
| Thứ tự | Mỗi trang sắp theo ID, nhưng các trang không nối thành một dãy tăng dần |

Hai hệ quả khi harvest:

- Phân trang theo offset nên danh sách có thể xê dịch nếu dữ liệu đổi giữa hai trang. Tài liệu
  arXiv ghi metadata cập nhật mỗi đêm, nên nên harvest xong một cửa sổ trong cùng ngày.
- Replay token có thể do CDN trả từ cache (`X-Cache: HIT`), nên token "còn dùng được" chưa chứng
  minh server còn chấp nhận nó. `recheck-tokens` vì thế gửi thêm một bản đổi `skip`.

**Chưa kiểm chứng:** token có thật sự bị từ chối sau 00:00 UTC hay không. Tài liệu arXiv ghi
"expires daily" và token ghi hạn như trên, nhưng token không chứa ngày nên server khó tự phân biệt
token cũ. `oai_harvester.py` xử lý theo tài liệu: gặp `badResumptionToken` thì harvest lại cửa sổ.

**Datestamp là ngày sửa cuối, không phải ngày nộp.** Cửa sổ `q-bio` 10–11/07/2025 có cả bài
`2309.*` và `2410.*`, còn bài `2507.06659` có datestamp `2025-12-17`. Vì vậy `ListRecords` không
lấy được một khoảng arXiv ID, và muốn so đúng tập ID được giao thì phải dùng `GetRecord`.

**Thời gian phản hồi của `ListRecords` chênh lệch rất lớn.** CDN cắt request sau khoảng 183 giây
bằng `503 first byte timeout` kèm `Retry-After: 0`, trong khi `GetRecord` mất khoảng 0,5 giây.

| Truy vấn | Kết quả |
|---|---|
| Không có set, 1–2 ngày hoặc không lọc ngày | 503 |
| `cs:cs:AI`, 1 ngày hoặc không lọc ngày | 503 |
| `stat`, 7 ngày | 503 |
| `q-bio`, 7 ngày, 123 record | 200 sau 105 giây |
| `q-fin`, 7 ngày, 66 record | 200 sau 26 giây |
| `econ`, 7 ngày, 69 record | 200 sau 23 giây |
| `physics:hep-lat`, 1 ngày, 1677 record | 200 sau 8 giây |

Set nhỏ trả về nhanh dù nhiều record, nên thời gian có vẻ phụ thuộc vào cỡ set hơn là số record
trả về. Đây là suy đoán từ một buổi đo, chưa kiểm chứng ở giờ khác.

**Hai điểm phải xử lý khi dùng Sickle:**

- `text/xml` không khai charset, nên `requests` giải mã bằng ISO-8859-1 và làm hỏng ký tự ngoài
  ASCII. Phải truyền `encoding="utf-8"`.
- Retry có sẵn của Sickle gọi lại ngay khi gặp `Retry-After: 0`. `PoliteSickle` dùng backoff riêng.

## Giới hạn

- So 3 nguồn chỉ trên 500 bài, nên tỉ lệ ở Bảng 1 mang tính ước lượng. API – Kaggle là trên cả 5000 bài.
- Tất cả 5000 bài đều nộp trong tháng 7/2025. Bài cũ hơn, đặc biệt ID kiểu `hep-th/9901001`, chưa được kiểm tra.

## File kết quả

Trong `reports/` (không commit): `a3_coverage.csv`, `a3_three_way.csv`, `a3_field_agreement.csv`,
`a3_versions.csv`, `a3_author_causes.csv`, `a3_api_recheck.csv`, `a3_disagreements.csv`.
