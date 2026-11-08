# Giai đoạn 2 — Bóc tách Cấu trúc Tài liệu (Parsing)

> **Trạng thái:** Dành sẵn (Kế hoạch triển khai sau Milestone 1)

Phần này được dành riêng cho nội dung của **Milestone 2: Document Parsing & Schema Normalization** theo tiến độ đồ án môn học.

### Nội dung trọng tâm của Milestone 2 dự kiến gồm:
1. **Phân tích cú pháp TeX và duyệt tệp đệ quy:** Nhận diện file gốc (\\documentclass), duyệt đệ quy các lệnh nhúng \\input{...} và \\include{...} để gom toàn bộ nội dung bài báo thành một cây cấu trúc phân cấp thống nhất.
2. **Bóc tách các trường thông tin văn bản:**
   - Tiêu đề (\\title), Danh sách tác giả & Đơn vị công tác (\\author, \\affiliation).
   - Tóm tắt công trình (\\begin{abstract} ... \\end{abstract}).
   - Cấu trúc các đề mục (\\section, \\subsection, \\subsubsection).
   - Khối nội dung văn bản thuần sau khi làm sạch các lệnh định dạng LaTeX.
3. **Chuẩn hóa công thức toán học và bảng mã:** Nhận diện công thức nội dòng ($...$) và công thức khối (\\begin{equation}), chuẩn hóa về dạng LaTeX thuần hoặc biểu diễn văn bản không làm rách câu.
4. **Trích xuất danh mục trích dẫn TeX:**
   - Bóc tách cấu trúc file .bib độc lập (BibTeX entries: author, title, year, journal...).
   - Bóc tách các mục trích dẫn nội dòng \\bibitem{...} (như đã khảo sát được 59.648 mục ở Milestone 1).
5. **Chuẩn hóa dữ liệu đầu ra:** Lưu trữ toàn bộ dữ liệu bóc tách vào cấu trúc bảng chuẩn theo hợp đồng dữ liệu chuẩn bị cho bài toán đối sánh ở Milestone 3.
