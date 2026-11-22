# Đối chiếu reference từ `.bib` và `\bibitem`

Bộ dữ liệu gồm 124 version được prescan với `bib_style == "both"` trong dải 2503. Báo cáo ghép entry theo `citation_key` trên tập ứng viên giữa `\bibitem` thuộc compile path và toàn bộ file `.bib` có trong thư mục version.

---

## 1. Phạm vi dữ liệu

| Chỉ số | Số lượng | Ghi chú |
| :--- | :--- | :--- |
| Version được khảo sát | 124 | `prescan_versions.csv`, nhãn `both` |
| Version có thư mục trên đĩa | 124 | Đạt 100% (124/124) |
| Version có entry `.bib` parse được và có `\bibitem` trong compile path | 76 | Entry `.bib` được thu từ mọi file trong thư mục version, không chỉ file được gọi trực tiếp |
| Version có entry `.bib` parse được nhưng không có `\bibitem` được nhận diện trong compile path | 47 | Prescan vẫn gắn nhãn `both`; các entry `.bib` có thể đến từ file không được gọi trực tiếp |
| Version không có entry `.bib` parse được | 1 | Có 64 entry `\bibitem` được nhận diện trong compile path; không kết luận file `.bib` vật lý rỗng |
| Entry thô từ file `.bib` (trong 76 version có cả hai kết quả parse) | 7,158 | Trung bình ~94.2 entry thô/version (ngoài ra có 14,482 entry thô thuộc 47 version không có `\bibitem` được nhận diện trong compile path) |
| Entry từ `\bibitem` (trong 76 version có cả hai kết quả parse) | 3,630 | Trung bình ~47.8 entry/version (tổng cộng 124 version là 3,694) |
| Entry thô từ file `.bib` (toàn bộ khảo sát) | 21,640 | Tổng số entry thô đọc được (chưa khử trùng lặp key giữa các file `.bib`, ghi nhận lặp key ở 6 version; trung bình 174.5/version) |
| Entry từ `\bibitem` (toàn bộ khảo sát) | 3,694 | Trung bình 29.8 entry/version đã đánh giá |
| Cặp entry cùng `citation_key` (tập ứng viên) | 2,788 | Ghép đối ứng heuristic giữa `\bibitem` trong compile path và mọi file `.bib` trong version |

---

## 2. Mức độ khớp theo trường

Mỗi cặp gồm hai entry có cùng `citation_key`.
- **Mẫu số (cả 2 có trường)**: Chỉ xét các cặp mà cả nguồn `.bib` và `\bibitem` đều có dữ liệu trường tương ứng.
- **Tỷ lệ / Tổng cặp**: Tỷ lệ khớp tính trên toàn bộ 2,788 cặp đối ứng (độ phủ thực tế trên toàn tập).

| Trường | Số cặp khớp | Mẫu số (Cả 2 có) | Tỷ lệ / Cặp có trường | Tỷ lệ / Tổng 2,788 cặp | Ghi chú kỹ thuật |
| :--- | :--- | :--- | :--- | :--- | :--- |
| DOI (`doi`) | 904 | 906 | 99.78% | 32.42% | 906 cặp có DOI ở cả 2 nguồn |
| arXiv ID (`arxiv_id`) | 255 | 256 | 99.61% | 9.15% | 256 cặp có arXiv ID ở cả 2 nguồn |
| Năm (`year`) | 2,635 | 2,692 | 97.88% | 94.51% | 2,692 cặp có năm ở cả 2 nguồn |
| Họ tác giả đầu | 2,434 | 2,712 | 89.75% | 87.30% | 2,712 cặp có tác giả ở cả 2 nguồn |
| Tiêu đề exact | 1,511 | 1,639 | 92.19% | 54.20% | 1,149 cặp thiếu tiêu đề ở ít nhất 1 nguồn (41.2%) |
| Tiêu đề soft | 1,524 | 1,639 | 92.98% | 54.66% | Khớp chính xác hoặc chứa chuỗi tiêu đề |

---

## 3. Cách đọc kết quả

Trong 2,788 cặp cùng `citation_key`:
- **Tiêu đề**: Có 1,639 cặp (58.8%) mà bộ bóc tách (parser) trích xuất thành công tiêu đề ở cả hai nguồn (bao gồm macro `\bibinfo{title}` với thuật toán cân bằng ngoặc lồng sâu). Trên tập 1,639 cặp này, tỷ lệ khớp exact đạt 92.19% (1,511 cặp) và soft đạt 92.98% (1,524 cặp, gồm 13 cặp soft-only).
- **Phân định các cặp thiếu tiêu đề**: Có 1,149 cặp (41.2%) thiếu trường tiêu đề ở ít nhất một nguồn. Trong đó có 1,078 cặp mà file `.bib` có tiêu đề nhưng parser không bóc tách được từ `\bibitem`, 44 cặp chỉ `\bibitem` có tiêu đề, và 27 cặp cả hai nguồn đều không có. Sự chênh lệch này gồm hai nguyên nhân thực tế:
  1. *Đặc trưng định dạng nguồn*: Nhiều tạp chí (đặc biệt trong các lĩnh vực vật lý và toán học) in `\bibitem` theo quy ước rút gọn, chỉ chứa tác giả, tên tạp chí, số tập, trang và năm mà hoàn toàn không in tên bài báo.
  2. *Giới hạn trích xuất của parser*: Việc bóc tách văn bản tự do phi cấu trúc bằng heuristic/regex gặp khó khăn trước các macro định dạng tùy biến lạ của tác giả. Vì vậy, 1,639 là số cặp mà parser lấy được, phản ánh độ phủ của công cụ chứ không phải toàn bộ số tiêu đề thực tế có trong văn bản.
- **Quy tắc ưu tiên**: `collect_bib()` ưu tiên entry từ `.bib` khi hai nguồn có cùng `citation_key` vì `.bib` có đầy đủ tiêu đề và trường chuẩn hóa hơn.
- **Phân định phạm vi và tập ứng viên**: 2,788 cặp đối ứng được ghép giữa `\bibitem` (trong compile path) và toàn bộ các entry từ mọi file `.bib` có trong thư mục version (kể cả file không được lệnh `\bibliography` trực tiếp gọi). Đây là heuristic xây dựng **tập ứng viên (candidate pool)** phục vụ đo lường tương thích và chuẩn bị cho matching pool ở Milestone 3, không phải đối chiếu nghiêm ngặt giữa hai nguồn chắc chắn cùng được trình biên dịch TeX sử dụng đồng thời.
- **Đồng thuận liên nguồn (Concordance)**: Bảng này đo mức độ đồng thuận liên nguồn giữa hai biểu diễn của cùng citation key, không phải độ chính xác tuyệt đối (Ground Truth Accuracy) hay Precision/Recall của pipeline deduplication.

## 4. Phân định phạm vi file `.bib` và kiểm tra độ nhạy

- `\bibitem` được trích xuất nghiêm ngặt từ các file `.tex` thuộc `compile_path` (qua `gather_detail`, loại bỏ hoàn toàn các file mồ côi hoặc template).
- Nguồn `.bib` được khảo sát trên toàn bộ file `.bib` có trong thư mục version (158 file, 21,640 entry thô).
- **Kiểm tra độ nhạy (Sensitivity Analysis)**: Trong số 158 file `.bib` trên đĩa của 124 version khảo sát, các lệnh `\bibliography` và `\addbibresource` trong `compile_path` chứa 70 tham số gọi file. Trong đó có 1 tham số không resolve được thành file trên đĩa và 67 file `.bib` riêng biệt được xác định trực tiếp từ compile path; 91 file `.bib` còn lại trên đĩa không được các lệnh trên trực tiếp gọi. Khi nộp bài lên arXiv, nhiều tác giả đã chèn sẵn môi trường `thebibliography` (từ file `.bbl` đã biên dịch) vào mã nguồn TeX và để lại file `.bib` trong gói nộp mà không còn lệnh `\bibliography` hoạt động. Do đó, việc gom toàn bộ file `.bib` có mặt trong thư mục version là một heuristic thu thập ứng viên tối đa cho quá trình đối chiếu và phục vụ matching pool ở M3.

## 5. Block BibTeX lỗi cú pháp

Bước đánh giá ghi nhận 1,014 block lỗi trên 27 version. Parser vẫn giữ các entry hợp lệ. `logs/bib.csv` đánh dấu version có lỗi bằng `bib_syntax_error:N`.
