1. Các file đính kèm (trong thư mục reports/):
   - references_clean.csv: Log crawl đã lọc sạch 100% các ID cũ 2502.*, chỉ gồm dữ liệu sạch của 5,000 bài dải 2503.11914 -> 2503.16913.
   - prescan_summary.json: File JSON tổng hợp 4 phân tích TeX cho book.
   - prescan_versions.csv: Bảng thống kê chi tiết 8,129 versions để vẽ biểu đồ phân phối.
   - prescan_corpus.zip: Chứa đầy đủ 13,128 file prescan.json (cấp paper và version).
2. Con số Matching Pool:
   - Tổng kích thước matching pool (ứng viên có arXiv ID): 106,352 ứng viên.
   - Trung bình mỗi bài: 21.27 bài (Trung vị: 13, Min: 0, Max: 4,331).
3. 4 phân tích prescan cho Book:
   - Số file .tex mỗi version:
     + Tính trên toàn bộ 8,129 versions: Trung bình 4.23 file/version (Trung vị: 1, Max: 134).
     + Tính trên 7,471 versions có TeX: Trung bình 4.60 file/version.
     + Tổng số file .tex quét được: 34,361 files.
   - Phân bố định dạng Bibliography (8,129 versions):
     + Chỉ có file .bib riêng: 4,833 versions (59.45%)
     + Không có TeX / không tìm thấy bib: 1,895 versions (23.31%)
     + Chỉ có \bibitem inline: 1,277 versions (15.71%)
     + Có cả file .bib và \bibitem: 124 versions (1.53%)
   - Số \bibitem mỗi version:
     + Trung bình toàn bộ: 7.34 bibitems/version (Trung vị: 0 do 59.45% bài dùng file .bib riêng, Max: 540).
     + Trung bình trên các version có \bibitem: 42.58 bibitems/version (Trung vị: 36).
     + Tổng số \bibitem inline: 59,648 bibitems.
   - Tỷ lệ xác định root TeX file: 99.97% (7,469 / 7,471 versions có TeX source).
4. Về 30 dòng "fail" trong references.csv cũ:
   Các dòng fail đó thuộc về đợt crawl nhầm ID 2502.* ban đầu. Với 5,000 bài dải chuẩn 2503.*, sau khi retry đã crawl thành công 4,999 bài "ok" (100%) và đúng 1 bài "not_indexed" do tác giả rút bài. Tỷ lệ thành công thực tế là 100%, không còn bài nào bị fail.