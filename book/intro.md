# Đồ án Nhập môn Khoa học Dữ liệu — Thu thập và Xử lý Dữ liệu arXiv

Chào mừng bạn đến với tài liệu kỹ thuật chính thức của đồ án **Thu thập, bóc tách và đối sánh dữ liệu arXiv** thuộc môn học **Nhập môn Khoa học Dữ liệu** tại Trường Đại học Khoa học Tự nhiên, Đại học Quốc gia Thành phố Hồ Chí Minh.

---

## 1. Tổng quan đồ án

Đồ án tập trung vào việc nghiên cứu, thiết kế và hiện thực hóa một quy trình hoàn chỉnh, có khả năng tái lập cao nhằm thu thập, chuẩn hóa và liên kết dữ liệu bài báo khoa học từ các nguồn học thuật: **arXiv**, **OAI-PMH**, và **Semantic Scholar**.

Quy mô thực nghiệm của đồ án được triển khai trên **25.000 bài báo khoa học** duy nhất (mỗi thành viên trong nhóm 5 người đảm nhiệm thu thập độc lập 5.000 bài theo dải định danh được phân công, đảm bảo tính phân tán và không trùng lặp).

Quy trình được chia thành ba giai đoạn chính:

1. **Giai đoạn 1 — Thu thập dữ liệu và đo lường hiệu năng:**
   - Thu thập có kiểm soát siêu dữ liệu và mã nguồn TeX từ arXiv (tuân thủ giới hạn tốc độ tối thiểu 3 giây giữa hai yêu cầu liên tiếp).
   - Khai thác đồ thị trích dẫn từ Semantic Scholar API.
   - Xây dựng hạ tầng đo lường hiệu năng hệ thống (thời gian thực thi, bộ nhớ đỉnh, bộ nhớ trung bình, dung lượng đĩa) và phát hành tài liệu tương tác qua Jupyter Book.
2. **Giai đoạn 2 — Bóc tách cấu trúc tài liệu và chuẩn hóa dữ liệu:**
   - Xác định đường biên dịch chính, bóc tách đệ quy mã nguồn TeX đa tệp và loại bỏ tệp thừa.
   - Chuẩn hóa văn bản, quy chuẩn công thức toán học và khử trùng lặp tự động liên phiên bản bằng hàm băm SHA-1.
   - Bóc tách trích dẫn BibTeX và bibitem tự do, hợp nhất trích dẫn đa phiên bản bằng thuật toán gom cụm bắc cầu.
3. **Giai đoạn 3 — Đối sánh bài báo và đồ thị trích dẫn:**
   - Xây dựng giải thuật đối sánh bài báo giữa các nguồn dữ liệu khác nhau.
   - Tái lập đồ thị mạng lưới trích dẫn khoa học.

---

## 2. Thông tin nhóm thực hiện (Nhóm 04)

| Mã số sinh viên | Họ và tên | Trách nhiệm chính trong đồ án | Phân hệ nâng cao phụ trách |
| :--- | :--- | :--- | :--- |
| **24120053** | Đặng Ngọc Hoàng | Nhóm trưởng, điều phối quy trình và thu thập siêu dữ liệu | **Phân hệ A3:** Đối sánh chéo ba nguồn siêu dữ liệu và khảo sát mã tiếp tục OAI-PMH |
| **24120144** | Dương Ngọc Minh Thư | Tải toàn văn mã nguồn bài báo | **Phân hệ A1:** Tối ưu hóa tải luồng nhị phân và phân loại lỗi tải trên 8.066 phiên bản |
| **24120152** | Trần Ngọc Thanh Tú | Trích xuất và tối ưu kho lưu trữ mã nguồn | **Phân hệ A2:** Bộ kiểm định chất lượng dữ liệu trên 7.606 phiên bản |
| **24120177** | Cáp Hửu Duy | Thu thập dữ liệu trích dẫn Semantic Scholar | **Phân hệ C:** Khảo sát trích dẫn và tiền xử lý cấu trúc TeX trên 8.129 phiên bản |
| **24120153** | Nguyễn Lê Anh Tuấn | Đo lường hiệu năng và hạ tầng báo cáo Jupyter Book | **Phân hệ B:** Đo lường bộ nhớ đỉnh qua nhân hệ điều hành so với lấy mẫu định kỳ |

---

## 3. Cấu trúc tài liệu báo cáo

Tài liệu được biên soạn dưới dạng sách tương tác (Jupyter Book), kết hợp giữa cơ sở lý thuyết kỹ thuật và mã nguồn phân tích thực tế:

- **Giai đoạn 1 — Thu thập dữ liệu:**
  - [01. Phương pháp thu thập dữ liệu](milestone1/01-methodology.ipynb): Khảo sát chi tiết bốn nguồn dữ liệu (arXiv API, OAI-PMH, Kaggle, Semantic Scholar), phân tích giới hạn tốc độ mạng, giải thuật chờ lũy thừa kết hợp nhiễu ngẫu nhiên, và quy tắc chuẩn hóa lược đồ dữ liệu.
  - [02. Báo cáo thống kê dữ liệu thực nghiệm](milestone1/02-statistics.ipynb): Phân tích bốn chỉ số tài nguyên, bảng tổng hợp 11 chỉ số bắt buộc trên 25.000 bài báo của cả năm thành viên, đánh giá tính nhất quán của quy trình trên năm dải dữ liệu độc lập và phân loại chi tiết các trường hợp lỗi tải.
  - [03. Phân tích hiệu năng chuyên sâu và kiểm định](milestone1/03-performance.ipynb): Đo lường bộ nhớ đỉnh qua nhân POSIX, tối ưu truyền luồng nhị phân, kiểm định chất lượng dữ liệu, đối sánh chéo ba nguồn siêu dữ liệu và khảo sát đặc tính mã nguồn TeX.
  - [04. Phân tích chuyên sâu dữ liệu](milestone1/04-deep-analysis.ipynb): Nghiên cứu sáu bài toán cấu trúc then chốt gồm phân bố phiên bản, cấu trúc đa tệp, định dạng thư mục trích dẫn, mật độ định danh arXiv phục vụ giai đoạn 3, phân loại lỗi và phân tích độ trễ mạng.
- **Giai đoạn 2 — Bóc tách dữ liệu:**
  - [01. Thu thập đa tệp và bóc tách cấu trúc phân cấp](milestone2/01-parsing.ipynb): Dò tìm tệp gốc, duyệt đệ quy cây nhúng mã nguồn TeX đa tệp, loại bỏ tệp thừa, và suy luận tự động cấp bậc phân mục.
  - [02. Chuẩn hóa văn bản, công thức toán học và khử trùng lặp dữ liệu](milestone2/02-standardization.ipynb): Chuẩn hóa cú pháp LaTeX, quy chuẩn công thức toán học nội dòng và khối, sinh định danh phần tử phục vụ khử trùng lặp tự động, và đánh giá trên tập dữ liệu kiểm định gán nhãn thủ công.
  - [03. Bóc tách trích dẫn BibTeX, hợp nhất đa phiên bản và đánh giá chất lượng](milestone2/03-evaluation.ipynb): Bóc tách trích dẫn BibTeX, chuyển đổi bibitem tự do bằng biểu thức chính quy, hợp nhất trích dẫn liên phiên bản bằng kỹ thuật gom cụm bắc cầu, và đánh giá khách quan trên tập đối sánh tự nhiên.

---

## 4. Hệ thống lưu trữ mã nguồn

Dự án duy trì hai kho lưu trữ tách biệt theo nguyên tắc phân tách trách nhiệm:
- **Kho lưu trữ mã nguồn (Code Repository):** Chứa mã nguồn quy trình thu thập, công cụ đo kiểm hiệu năng, kịch bản bóc tách và các ca kiểm thử tự động.
- **Kho lưu trữ tài liệu (Documentation Repository):** Chứa cấu hình Jupyter Book, các sổ tay phân tích thực nghiệm, dữ liệu đối soát và kịch bản tự động xuất bản lên GitHub Pages.

---

## 5. Nguồn gốc và giới hạn của dữ liệu

### 5.1 Thời điểm thu thập

arXiv liên tục nhận phiên bản mới, nên mọi số liệu trong báo cáo này là ảnh chụp
tại thời điểm thu thập chứ không phải trạng thái hiện tại của kho.

| Dải ID | Siêu dữ liệu và mã nguồn | Trích dẫn (Semantic Scholar) |
|---|---|---|
| 2507.06659 – 2507.11658 | 25/10/2026 – 02/11/2026 | 29/10/2026 (4.875 bài), 02/11/2026 (125 bài chạy lại) |

> Bốn thành viên còn lại bổ sung dòng của mình vào bảng trên, lấy từ trường
> `crawled_at` trong `corpus/<pub>/references.json` của dải mình.

### 5.2 Tệp `.bbl` và các trường hợp không chuyển đổi được

Một số phiên bản không kèm `.bib` lẫn `\bibitem` trong `.tex`, chỉ còn `.bbl` —
là bản đã dàn trang, sinh ra từ `.bib` lúc biên dịch. Nhóm giữ lại `.bbl` trong
kho dữ liệu và bóc trực tiếp các mục `\bibitem` từ đó.

Kết quả: số publication không có mục trích dẫn nào giảm từ **1.190 (23,8%)**
xuống **449 (9,0%)**, khôi phục được 741 bài.

Trong 449 bài còn lại:

| Nguyên nhân | Tỉ lệ |
|---|---|
| Phiên bản không có mã nguồn TeX (`_EMPTY`) | 76% |
| Bài không có mục tài liệu tham khảo | 11% |
| `.bbl` sinh bởi **biber**, dùng cú pháp `\entry` thay cho `\bibitem` | 12% |

Nhóm **chưa xử lý được** nhóm thứ ba, khoảng 1,1% toàn bộ kho. Cú pháp `\entry`
của biber lồng nhiều cấp và tách trường theo cách khác hẳn `\bibitem`, nên bộ bóc
tách hiện tại không dùng lại được. Hai hướng đã thử và lý do dừng:

1. **Chuyển ngược `.bbl` về `.bib`** — không khả thi vì `.bbl` đã mất cấu trúc
   trường gốc, chỉ còn chuỗi đã định dạng để in.
2. **Viết bộ bóc tách riêng cho cú pháp `\entry`** — khả thi nhưng chi phí không
   tương xứng với 1,1% dữ liệu, nên nhóm ghi nhận thay vì làm.

Mục trích dẫn bóc từ `.bbl` kém chính xác hơn bóc từ `.bib`, vì `.bbl` không còn
ranh giới trường. Trường `title` và `authors` dễ thiếu hoặc lẫn vào nhau.

### 5.3 Bài không bóc tách được

Bốn publication không dựng được cây cấu trúc:

| arXiv ID | Nguyên nhân |
|---|---|
| `2507.10483` | plain TeX, không có `\documentclass` lẫn `\begin{document}` |
| `2507.08666` | tệp `main.tex` thực chất là một trang HTML |
| `2507.08667` | tệp `main.tex` thực chất là một trang HTML |
| `2507.09585` | tệp `main.tex` thực chất là một trang HTML |
