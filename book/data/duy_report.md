# BÁO CÁO CÔNG VIỆC MILESTONE 1 — PHÂN HỆ CRAWL REFERENCES & TIỀN XỬ LÝ TEX
**Người thực hiện:** Cáp Hửu Duy (MSSV: 24120177)  
**Phân bổ tập ID:** 5 000 bài arXiv tháng 2025-03 (`2503.11914` → `2503.16913`)

---

## 1. BA THỐNG KÊ BẮT BUỘC

Dữ liệu được trích xuất từ `logs/references.csv` và `corpus/` sau khi hoàn tất crawl toàn bộ 5 000 arXiv ID được giao:

| Chỉ số | Giá trị | Cách tính & Diễn giải |
|---|:---:|---|
| **1. Số reference trung bình mỗi bài** | **44.41** refs/bài | Tính trên 4 999 bài thành công: $\frac{222\,029}{4\,999} \approx 44.41$ refs/bài. Phù hợp với đặc thù trung bình của các bài báo khoa học trên arXiv (30–60 refs). |
| **2. Tỉ lệ thành công khi crawl reference metadata** | **99.98%** | $4\,999 / 5\,000$ bài lấy được danh sách trích dẫn đầy đủ qua Semantic Scholar API. Chỉ duy nhất 1 bài (`2503.14889`) trả về `not_indexed` (bài bị rút hoặc chưa lập chỉ mục), 0 bài gặp lỗi (`fail: 0`). |
| **3. Tỉ lệ reference có mã arXiv ID** | **47.92%** | $\frac{106\,401}{222\,029} \times 100\% = 47.92\%$ (106 401 refs có arXiv / 222 029 tổng refs). Gần một nửa trích dẫn liên kết được trực tiếp về bài báo trên arXiv. |

### Bảng số liệu chi tiết:
* **Tổng số bài được phân công:** 5 000 bài
* **Số bài crawl thành công (`ok`):** 4 999 bài (99.98%)
* **Số bài không có trên S2 (`not_indexed`):** 1 bài (0.02%)
* **Số bài lỗi cần xem lại (`fail`):** 0 bài (0.00%)
* **Tổng số trích dẫn (References) thu được:** 222 029 references
* **Số trích dẫn có mã arXiv:** 106 401 references (47.92%)
* **Số trích dẫn không có mã arXiv (vẫn lưu đầy đủ):** 115 628 references (52.08%)

---

## 2. BÁO CÁO CÁC HẠN CHẾ CỦA DỮ LIỆU & HỆ THỐNG 

*(Đoạn văn hoàn chỉnh để đưa vào mục Limitations trong báo cáo đồ án của nhóm)*

> **Hạn chế kỹ thuật trong quá trình thu thập Reference Metadata:**
> 
> 1. **Độ trễ lập chỉ mục (Index Lag):** Semantic Scholar có độ trễ lập chỉ mục từ 1 đến 7 ngày đối với các bản thảo (preprint) mới tải lên arXiv. Đối với các bài vừa được công bố sát ngày thu thập dữ liệu (tháng 03/2025), một số bài báo có thể chưa được hệ thống trích xuất danh sách trích dẫn đầy đủ hoặc chưa được lập chỉ mục (như trường hợp bài `2503.14889`).
> 
> 2. **Không phân biệt phiên bản chỉnh sửa (Version-agnostic API):** Semantic Scholar quản lý đồ thị học thuật ở cấp độ bài báo tổng quát (`paperId`), do đó API chỉ cung cấp danh sách trích dẫn của phiên bản mới nhất được lập chỉ mục mà không phân biệt lịch sử trích dẫn giữa các phiên bản sửa đổi (v1, v2, v3). Do đó, danh sách `references.json` sẽ đóng vai trò là matching pool chung cho mọi phiên bản của bài báo đó trong Milestone 2 và 3.
> 
> 3. **Độ bao phủ mã arXiv không đồng đều giữa các chuyên ngành (ArXiv Coverage Disparity):** Tỉ lệ trích dẫn liên kết được về mã arXiv đạt xấp xỉ 47.92%. Con số này phản ánh đúng thực tế cơ cấu ngành: các bài báo thuộc lĩnh vực Khoa học Máy tính (cs.*), Toán học (math.*) và Vật lý Năng lượng cao (hep-th) có tỉ lệ trích dẫn arXiv rất cao (60–80%); trong khi các bài thuộc chuyên ngành Sinh học tính toán, Y sinh, hoặc trích dẫn sách giáo khoa và tài liệu hội thảo truyền thống thì chỉ có định danh DOI hoặc tên venue mà không có mã arXiv.

---

## 3. SỐ LIỆU BỔ SUNG — TIỀN XỬ LÝ BẮC CẦU M2/M3 (Mục B6)

Để hỗ trợ Milestone 2 và Milestone 3, script `src/tex_prescan.py` đã duyệt 8 129 version và xuất file `prescan.json` với các chỉ số:

* **Tỉ lệ phát hiện file gốc TeX (Root file):** **99.97%** (7 469 / 7 471 versions có mã nguồn TeX xác định được file `.tex` chứa lệnh `\documentclass`).
* **Phong cách Bibliography của tác giả:**
  - Sử dụng file `.bib` riêng: **59.5%** (4 833 versions)
  - Sử dụng trích dẫn trực tiếp inline (`\bibitem`): **15.7%** (1 277 versions)
  - Sử dụng đồng thời cả hai: **1.5%** (124 versions)
  - Không có trích dẫn TeX (hoặc bản chỉ PDF): **23.3%** (1 895 versions)
* **Tổng số trích dẫn inline (`\bibitem`):** 59 648 mục.
* **Kích thước matching pool trung bình:** 21.27 candidates/bài (tương ứng kích thước cột $n$ cho ma trận đối sánh $m \times n$ ở M3).

