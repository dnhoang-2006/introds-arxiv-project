# ĐẶC TẢ TOÀN DIỆN ĐỒ ÁN ARXIV — NHẬP MÔN KHOA HỌC DỮ LIỆU (HCMUS)

> **Tài liệu tham chiếu chuẩn xác và đầy đủ nhất dành cho toàn bộ dự án**  
> **Áp dụng cho:** Tất cả các thành viên Nhóm 04 và các AI Coding Agent làm việc trên dự án  
> **Căn cứ nguồn gốc:** Đề bài chính thức từ Lab Book môn học (`https://hcmus-cs-ta.github.io/lab-book/intro-ds/statement/`)  
> **Mục tiêu:** Lưu trữ vĩnh viễn ngữ cảnh, đặc tả kỹ thuật, ràng buộc dữ liệu, quy chuẩn đánh giá và hướng dẫn thực thi Google Colab xuyên suốt 3 Milestone.

---

## MỤC LỤC
1. [Quy chế và thông tin vận hành chung](#1-quy-chế-và-thông-tin-vận-hành-chung)
2. [Chi tiết Milestone 1 — Thu thập dữ liệu (Data Crawling)](#2-chi-tiết-milestone-1--thu-thập-dữ-liệu-data-crawling)
3. [Chi tiết Milestone 2 — Bóc tách cấu trúc và chuẩn hóa (Hierarchical Parsing & Standardization)](#3-chi-tiết-milestone-2--bóc-tách-cấu-trúc-và-chuẩn-hóa-hierarchical-parsing--standardization)
4. [Chi tiết Milestone 3 — Quy trình đối sánh trích dẫn (Reference Matching Pipeline)](#4-chi-tiết-milestone-3--quy-trình-đối-sánh-trích-dẫn-reference-matching-pipeline)
5. [Đặc tả 6 bảng dữ liệu xuất bản cuối cùng trên Hugging Face](#5-đặc-tả-6-bảng-dữ-liệu-xuất-bản-cuối-cùng-trên-hugging-face)
6. [Phân tích chuyên sâu về Google Colab: Yêu cầu, bản chất và cách thực hiện](#6-phân-tích-chuyên-sâu-về-google-colab-yêu-cầu-bản-chất-và-cách-thực-hiện)

---

## 1. QUY CHẾ VÀ THÔNG TIN VẬN HÀNH CHUNG

### 1.1. Các kênh nộp bài và thành phần sản phẩm
Đồ án làm việc theo nhóm 5 sinh viên. Toàn bộ quá trình thực hiện xoay quanh 4 kênh nộp sản phẩm chính:

1. **Kho mã nguồn chung (Shared Code Repository - GitHub):**
   - Duy nhất **1 kho lưu trữ mã nguồn công khai** dùng cho toàn bộ đồ án (`dnhoang-2006/introds-arxiv-project`).
   - Mã nguồn của từng Milestone được commit tích lũy liên tục để lịch sử commit phản ánh chân thực tiến độ làm việc của cả nhóm.
   - Quy định nghiêm ngặt: Repo **chỉ chứa mã nguồn** (`.py`, `.ipynb`, `requirements.txt`, `README.md`), **tuyệt đối không chứa tệp dữ liệu cào, gói nén `.tar.gz`, tệp nhị phân**.
   - Nộp link repo trên Moodle ở cả 3 Milestone.
2. **Báo cáo tương tác (Jupyter Book):**
   - Toàn bộ báo cáo của Milestone 1 và Milestone 2 nằm chung trong **1 cuốn sách tương tác Jupyter Book**, lưu trữ trên một repo riêng biệt và xuất bản qua GitHub Pages (`introds-arxiv-book.github.io`).
   - Milestone 1 là phần mở đầu (Section 1). Milestone 2 bổ sung phần tiếp theo (Section 2) vào chính cuốn sách này, không tạo sách mới.
   - **Ràng buộc quan trọng:** Toàn bộ bảng biểu và biểu đồ **phải được sinh tự động trong quá trình biên dịch sách (during book compilation)**, tuyệt đối không dán ảnh chụp màn hình tĩnh.
3. **Bộ dữ liệu xuất bản cuối cùng (Hugging Face Dataset):**
   - Không nộp dữ liệu trung gian ở Milestone 1 và Milestone 2. Dữ liệu thô và đã xử lý được lưu giữ tại nhóm để làm đầu vào cho các giai đoạn kế tiếp.
   - Ở Milestone 3, toàn bộ dữ liệu hoàn chỉnh được xuất bản công khai lên Hugging Face Hub dưới dạng các bảng **Parquet phân mảnh (sharded Parquet)** gồm 6 bảng chuẩn hóa.
4. **Báo cáo tổng kết và Poster Session (Milestone 3):**
   - Mỗi nhóm nộp 1 tệp `.pptx` chứa 1 poster duy nhất định dạng khổ đứng **Portrait A2**.
   - Sau khi được giảng viên duyệt, nhóm in poster và thuyết trình tại buổi Poster Session.

### 1.2. Quy định học thuật và liêm chính
- Mã nguồn phải có chú thích (comments) rõ ràng, tài liệu hướng dẫn đầy đủ.
- Được phép tham khảo tài liệu trực tuyến nhưng bắt buộc phải trích dẫn nguồn đầy đủ.
- Được thảo luận ý tưởng với bạn bè nhưng phải tự tay hiện thực và tự diễn giải theo hiểu biết cá nhân.
- **Quy tắc không khoan nhượng:** Bất kỳ Milestone nào phát hiện hành vi gian lận hoặc thiếu trung thực sẽ nhận điểm 0 toàn bộ.
- Tuyệt đối không chấp nhận nộp bài trễ (No late submission).

---

## 2. CHI TIẾT MILESTONE 1 — THU THẬP DỮ LIỆU (DATA CRAWLING)

### 2.1. Mục tiêu và phạm vi
- Đối tượng thu thập: Kho lưu trữ mở **arXiv** với hơn 2 triệu bài báo.
- Thay vì chỉ cào metadata hoặc tệp PDF khó xử lý, đồ án yêu cầu thu thập **toàn văn mã nguồn LaTeX gốc** làm nền tảng cho việc bóc tách cấu trúc ở Milestone 2 và mô hình học máy ở Milestone 3.
- Quy mô: Mỗi sinh viên được giao một dải ID cố định (5.000 bài báo/người, nhóm 5 người tổng cộng **25.000 bài báo duy nhất**).
- **Ràng buộc cốt lõi:** Với mỗi bài báo được giao, **bắt buộc phải thu thập toàn bộ các phiên bản (every version: v1, v2, v3...)**, không được bỏ sót bất kỳ bản chỉnh sửa nào.

### 2.2. Ba trụ cột kỹ thuật của Milestone 1
1. **Khám phá bài báo và số phiên bản (Entry Discovery):**
   - Dùng thư viện `arxiv.py` truy vấn danh sách ID được giao qua endpoint `http://export.arxiv.org/api/query`.
   - Đặc tính quan trọng của arXiv API: Khi tra cứu ID gốc (ví dụ `2310.12345`), API trả về định danh của phiên bản mới nhất (ví dụ `2310.12345v4`). Hậu tố `v4` cho biết bài báo có đúng 4 phiên bản cần tải.
   - Thử nghiệm mở rộng: Khảo sát giao thức thu hoạch siêu dữ liệu quy mô lớn OAI-PMH (endpoint mới từ 03/2025: `https://oaipmh.arxiv.org/oai`) và tập dữ liệu tĩnh Kaggle arXiv Dataset.
2. **Tải toàn văn mã nguồn TeX (Full-Text Source Download):**
   - Tải từng phiên bản độc lập qua mirror chuyên dụng: `https://export.arxiv.org/src/{arxiv_id}v{version}` (ví dụ `.../src/2310.12345v2`).
   - Tuyệt đối không tải từ trang chủ `arxiv.org` vì sẽ bị tường lửa chặn mã lỗi 403.
   - **Kỷ luật điều phối mạng:** Bắt buộc duy trì khoảng nghỉ tối thiểu 3 giây (`REQUEST_DELAY >= 3.0s`) giữa 2 yêu cầu liên tiếp, chỉ dùng 1 kết nối tại một thời điểm, và thiết lập `User-Agent` mô tả rõ danh tính dự án học thuật.
   - **Quy tắc lọc dữ liệu (Bảo tồn dung lượng):**
     - Khoảng 97% bài báo có mã nguồn nén `.tar.gz`, 3% còn lại là dạng chỉ có PDF (`pdf_only`).
     - **Chỉ giải nén và giữ lại tệp `.tex` và `.bib`**. Toàn bộ tệp ảnh nhị phân (`.png`, `.jpg`, `.pdf`, font, file tạm) phải được loại bỏ ngay trong bước giải nén để tránh phình to ổ đĩa.
     - Giữ nguyên các câu lệnh LaTeX định nghĩa hình ảnh (`\begin{figure}`, `\includegraphics`) bên trong tệp `.tex` để phục vụ bóc tách cấu trúc ở Milestone 2.
     - Với các bài không có nguồn TeX (ví dụ `pdf_only` hoặc Word), phải ghi nhận là một bản ghi rỗng (`_EMPTY.json`) thay vì bỏ qua bài báo.
3. **Trích xuất thông tin trích dẫn (Extracting References):**
   - Khai thác **Semantic Scholar Graph API** qua endpoint `https://api.semanticscholar.org/graph/v1/paper/arXiv:{arxiv_id}`.
   - Thu thập danh sách tài liệu tham khảo kèm siêu dữ liệu (tiêu đề, tác giả, năm, venue, externalIds).
   - Kiểm tra khóa `externalIds.ArXiv` để xác định các trích dẫn cũng là bài báo trên arXiv. Giữ lại cả định danh chuẩn cũ trước năm 2007 (`hep-th/9901001`).

### 2.3. Hai bảng dữ liệu của Milestone 1
- Bảng `papers`:
  - `arxiv_id` (string, bắt buộc)
  - `title` (string)
  - `authors` (danh sách chuỗi)
  - `submission_date` (chuỗi ISO 8601)
  - `revised_dates` (danh sách chuỗi)
  - `venue` (string, có thể rỗng)
- Bảng `references`:
  - `arxiv_id` (string, bài báo nguồn đi trích dẫn)
  - `ref_arxiv_id` (string, mã arXiv của bài báo được trích dẫn)
  - `ref_title` (string)
  - `ref_authors` (danh sách chuỗi)
  - `ref_submission_date` (string)
  - `ref_s2_id` (string, mã Semantic Scholar)

### 2.4. Tiêu chí chấm điểm Milestone 1
1. **Báo cáo (Jupyter Book):** Minh họa đầy đủ thống kê, bảng biểu và biểu đồ sinh tự động trong quá trình biên dịch sách.
2. **Mã nguồn:** Sạch sẽ, dễ đọc, có thể tái lập và chạy được.
3. **Khám phá & Thu thập:** Áp dụng đúng công cụ, đạt độ phủ 100% tất cả phiên bản của các bài báo được giao.
4. **Dữ liệu đầu ra:** Tỷ lệ cào thành công, tổ chức thư mục đúng chuẩn quy ước.
5. **Hiệu năng hệ thống (Scraper's Performance):** Đo lường thời gian thực thi (wall-clock time), bộ nhớ RAM đỉnh (Peak RAM), RAM trung bình, dung lượng đĩa tối đa và dung lượng đầu ra trên môi trường Google Colab CPU-only.

---

## 3. CHI TIẾT MILESTONE 2 — BÓC TÁCH CẤU TRÚC VÀ CHUẨN HÓA (HIERARCHICAL PARSING & STANDARDIZATION)

### 3.1. Mục tiêu
Chuyển đổi dữ liệu phi cấu trúc (mã nguồn LaTeX thu thập từ M1) thành cấu trúc phân cấp dạng cây hoàn chỉnh, chuẩn hóa văn bản và công thức toán học, trích xuất BibTeX và khử trùng lặp dữ liệu liên phiên bản.

### 3.2. Bốn bài toán kỹ thuật trọng tâm
1. **Thu thập tệp mã nguồn đa nguồn (Multi-file Gathering):**
   - Xác định tệp gốc biên dịch chính (`publication root`): là tệp `.tex` chứa khai báo `\documentclass`.
   - Phân giải đệ quy cây nhúng tệp qua các lệnh `\input{...}`, `\include{...}` và `\subfile{...}`.
   - **Xử lý lệnh bị comment:** Các lệnh `\input` bị comment (`% \input{...}`) phải được xử lý như văn bản thuần, không được nhúng vào đường biên dịch.
   - **Loại bỏ tệp thừa:** Mọi tệp `.tex` nằm lẫn trong thư mục nhưng không thể duyệt tới từ tệp gốc đều bị coi là tệp rác/tệp nháp và phải bị loại bỏ.
   - Xử lý chống vòng lặp include (`a.tex -> b.tex -> a.tex`).
2. **Xây dựng cây phân cấp tài liệu (Hierarchy Construction):**
   - Gốc cây là `Document`.
   - Cấp 2 thường là `Chapter` hoặc `Section`.
   - Các cấp thấp hơn: `Subsection`, `Subsubsection`, `Paragraph`... Cấp độ phân bậc phải được **suy luận tự động (`infer_levels`)** theo cấu trúc thực tế của từng tài liệu thay vì gán nhãn cứng.
   - **Phần tử lá nhỏ nhất (Smallest Elements):**
     - `Sentence`: Câu văn hoàn chỉnh ngăn cách bởi dấu chấm kết câu. **Tuyệt đối không được cắt đôi** công thức toán học, câu lệnh, từ viết tắt (`i.e.`, `e.g.`, `et al.`, `Fig. 1`, `Sec. 2`), đường dẫn URL, hoặc số thập phân (`3.14`).
     - `Formula`: Các khối công thức toán học độc lập (`\begin{equation}`, `$$...$$`).
     - `Figure`: Hình ảnh và bảng biểu (đề bài quy định coi Table là một dạng của Figure).
   - Khối danh sách (`\begin{itemize}`): Tách thành khối phân nhánh cấp cao hơn, mỗi mục (`item`) là một phần tử con cấp kế tiếp.
   - **Loại trừ và Bao hàm:**
     - Mục Tài liệu tham khảo (`References` / `\begin{thebibliography}`) **không được đưa vào cây phân cấp**.
     - Mục Lời cảm ơn (`Acknowledgements`) và Phụ lục (`Appendix` / `\section*`) **bắt buộc phải được giữ lại và bóc tách đầy đủ**.
3. **Chuẩn hóa văn bản và công thức toán (Cleanup & Normalization):**
   - Làm sạch LaTeX: Xóa bỏ các lệnh định dạng không mang ý nghĩa ngữ nghĩa như `\centering`, tùy chọn vị trí ảnh/bảng `[htbp]`, `\midrule`, `\toprule`, `\hline`.
   - Chuẩn hóa toán học:
     - Toàn bộ toán nội dòng (inline math) đưa về dạng thống nhất `$..$`.
     - Toàn bộ toán khối (block math: `$$..$$`, `\[..\]`, `align`, `gather`) đưa về dạng chuẩn `\begin{equation}..\end{equation}`.
4. **Trích xuất BibTeX và Khử trùng lặp hai tầng (Deduplication):**
   - **Bóc tách `\bibitem`:** Chuyển đổi các trích dẫn viết tay tự do trong mã TeX thành bản ghi BibTeX có cấu trúc bằng biểu thức chính quy (regex).
   - **Khử trùng lặp tài liệu trích dẫn (Reference Entries):**
     - Khi một tài liệu trích dẫn xuất hiện ở nhiều phiên bản với các citation key khác nhau (ví dụ: v1 dùng `vaswani2017`, v2 đổi thành `vit_transformer`), phải chọn một key đại diện chuẩn duy nhất.
     - Đổi tên toàn bộ lệnh `\cite{...}` trong thân văn bản về key chuẩn đã chọn.
     - **Hợp nhất trường dữ liệu (Unionize fields):** Không chọn một bản ghi và vứt bỏ bản ghi khác, mà phải lấy hợp toàn bộ các trường (ví dụ v1 có `year`, v2 có `doi` thì bản ghi hợp nhất phải có cả `year` lẫn `doi`).
   - **Khử trùng lặp nội dung văn bản (Full-text Content):**
     - Thực hiện **sau khi đã làm sạch và chuẩn hóa văn bản**.
     - Nếu một phần tử (câu văn, công thức toán) có nội dung giống hệt nhau giữa các phiên bản, phần tử đó chỉ được lưu **đúng 1 dòng duy nhất** trong bảng `elements` và có cùng một `element_id`.
     - Bảng `hierarchy` của các phiên bản sau chỉ cần trỏ lại `element_id` đó.

### 3.3. Ba bảng dữ liệu của Milestone 2
- Bảng `elements`:
  - `element_id` (string, bắt buộc): Khóa định danh duy nhất của phần tử (`pub_key#kind_code_hash`).
  - `arxiv_id` (string, bắt buộc)
  - `kind` (string, phân loại: document, section, subsection, paragraph, sentence, formula, figure...)
  - `content` (string): Nội dung đã chuẩn hóa.
- Bảng `hierarchy`:
  - `arxiv_id` (string, bắt buộc)
  - `version` (int)
  - `element_id` (string, bắt buộc)
  - `parent_id` (string, bắt buộc): Khóa ngoại trỏ đến phần tử cha trong cây phân cấp của phiên bản đó.
- Bảng `bibtex`:
  - `arxiv_id` (string, bắt buộc)
  - `citation_key` (string, khóa trích dẫn chuẩn sau dedup)
  - `entry_type` (string, loại tài liệu: article, inproceedings, book...)
  - `title`, `authors`, `year`, `doi`, `journal`, `url`.

---

## 4. CHI TIẾT MILESTONE 3 — QUY TRÌNH ĐỐI SÁNH TRÍCH DẪN (REFERENCE MATCHING PIPELINE)

### 4.1. Bài toán đối sánh thực thể (Entity Resolution)
- Mục tiêu: Ánh xạ từng bản ghi BibTeX trích xuất từ văn bản bài báo (bảng `bibtex` ở M2) với bản ghi trích dẫn có mã arXiv thu thập từ Semantic Scholar (bảng `references` ở M1) của **cùng một bài báo**.
- Không gian ứng viên: Nếu một bài báo có $m$ bản ghi BibTeX và $n$ trích dẫn có mã arXiv, không gian ứng viên là một ma trận nhị phân kích thước $m \times n$. Mỗi ô mang nhãn 1 (nếu khớp cùng một tài liệu) hoặc 0 (nếu không khớp). Mỗi bản ghi BibTeX có tối đa một nhãn đúng (hoặc toàn bộ nhãn 0 nếu không tìm thấy trích dẫn tương ứng).

### 4.2. Quy định gán nhãn dữ liệu (Data Labelling)
Số lượng bài báo gán nhãn được tính theo công thức phụ thuộc vào số thành viên nhóm ($k = 5$):

1. **Gán nhãn thủ công (Manual Labelling):**
   - Tối thiểu $5 \times k = 25$ bài báo được gán nhãn thủ công hoàn toàn.
   - Mỗi bài báo gán nhãn thủ công phải có ít nhất 20 bản ghi BibTeX được gán nhãn ($Q \ge 20$).
   - Tổng số bản ghi gán nhãn thủ công toàn nhóm phải đạt tối thiểu $100 \times k = 500$ bản ghi.
2. **Gán nhãn tự động bằng quy tắc cổ điển (Automatic Matching):**
   - Sử dụng regex, so khớp độ tương đồng chuỗi ký tự (string similarity/Levenshtein).
   - Áp dụng trên **tối thiểu 10% số bài báo** nằm ngoài tập gán nhãn thủ công, và tối thiểu phải chứa ít nhất $2 \times k = 10$ bài báo.
   - Khi áp dụng trên bài báo nào, bộ đối sánh tự động phải gán nhãn toàn bộ các bản ghi BibTeX của bài báo đó.

### 4.3. Phân chia tập dữ liệu và xây dựng đặc trưng (Data Split & Feature Engineering)
- **Chiến lược phân chia tập dữ liệu:**
  - Tập Kiểm thử (Test Set): Gồm $k = 5$ bài gán nhãn thủ công + $k = 5$ bài gán nhãn tự động (tổng 10 bài).
  - Tập Thẩm định (Validation Set): Gồm $k = 5$ bài gán nhãn thủ công + $k = 5$ bài gán nhãn tự động (tổng 10 bài).
  - Tập Huấn luyện (Training Set): Gồm toàn bộ các bài gán nhãn còn lại.
- **Kỹ thuật trích xuất đặc trưng (Feature Engineering):**
  - Biến đổi bài toán thành phân loại nhị phân, hồi quy, hoặc xếp hạng (ranking).
  - Xây dựng đặc trưng: Độ tương đồng tên tiêu đề (Jaccard, TF-IDF, Levenshtein, Embedding cosine), độ trùng khớp danh sách tác giả, so khớp năm xuất bản, so khớp chuỗi định danh DOI/arXiv, và các đặc trưng dựa trên cấu trúc phân cấp từ Milestone 2.
  - Phải có phân tích dữ liệu và lập luận chặt chẽ về lý do thiết kế từng đặc trưng trong poster và báo cáo.

### 4.4. Đánh giá mô hình bằng chỉ số MRR@5
- Với mỗi bản ghi BibTeX trong tập kiểm thử, mô hình dự đoán và xếp hạng danh sách 5 ứng viên trích dẫn có khả năng khớp nhất (`cand_1` đến `cand_5`).
- Chỉ số đánh giá: **Mean Reciprocal Rank @ 5 (MRR@5)**:
  $$\text{MRR@5} = \frac{1}{|Q|} \sum_{i=1}^{|Q|} \frac{1}{\text{rank}_i}$$
  Trong đó:
  - $|Q|$ là tổng số bản ghi BibTeX có gán nhãn trong tập Test.
  - $\text{rank}_i$ là vị trí của ứng viên đúng trong danh sách top 5 (nhận giá trị từ 1 đến 5). Nếu ứng viên đúng không nằm trong top 5, điểm của bản ghi đó bằng 0.

### 4.5. Bảng dữ liệu `predictions`
- `arxiv_id` (string, bắt buộc)
- `partition` (string: `train`, `valid`, hoặc `test`)
- `citation_key` (string, bắt buộc)
- `groundtruth_arxiv_id` (string, mã arXiv đúng của tài liệu được trích dẫn)
- `cand_1`, `cand_2`, `cand_3`, `cand_4`, `cand_5` (string, danh sách 5 ứng viên xếp hạng từ cao xuống thấp)

---

## 5. ĐẶC TẢ 6 BẢNG DỮ LIỆU XUẤT BẢN CUỐI CÙNG TRÊN HUGGING FACE

Ở cuối đồ án (Milestone 3), toàn bộ sản phẩm dữ liệu được đóng gói thành một kho dữ liệu duy nhất trên Hugging Face Hub định dạng **sharded Parquet** gồm 6 bảng:

| Tên bảng | Nội dung lưu trữ | Cột và kiểu dữ liệu | Milestone sinh ra |
| :--- | :--- | :--- | :--- |
| **`papers`** | Siêu dữ liệu các bài báo được giao | `arxiv_id` (str), `title` (str), `authors` (list[str]), `submission_date` (str ISO), `revised_dates` (list[str]), `venue` (str/null) | Milestone 1 |
| **`references`** | Danh mục trích dẫn thu thập từ Semantic Scholar (chỉ giữ trích dẫn có mã arXiv) | `arxiv_id` (str), `ref_arxiv_id` (str), `ref_title` (str), `ref_authors` (list[str]), `ref_submission_date` (str), `ref_s2_id` (str) | Milestone 1 |
| **`elements`** | Kho phần tử nội dung phân cấp dùng chung (đã khử trùng lặp liên phiên bản) | `element_id` (str), `arxiv_id` (str), `kind` (str), `content` (str) | Milestone 2 |
| **`hierarchy`** | Cây quan hệ phân cấp nút - cha theo từng phiên bản | `arxiv_id` (str), `version` (int), `element_id` (str), `parent_id` (str) | Milestone 2 |
| **`bibtex`** | Danh mục BibTeX chuẩn sau khi hợp nhất đa phiên bản | `arxiv_id` (str), `citation_key` (str), `entry_type` (str), `title` (str), `authors` (list[str]), `year` (int/null), `doi` (str), `journal` (str), `url` (str) | Milestone 2 |
| **`predictions`** | Kết quả xếp hạng đối sánh trích dẫn của mô hình học máy | `arxiv_id` (str), `partition` (str), `citation_key` (str), `groundtruth_arxiv_id` (str/null), `cand_1`..`cand_5` (str/null) | Milestone 3 |

---

## 6. PHÂN TÍCH CHUYÊN SÂU VỀ GOOGLE COLAB: YÊU CẦU, BẢN CHẤT VÀ CÁCH THỰC HIỆN

### 6.1. Đề bài thực sự nói gì về Google Colab?
Đề bài chính thức đề cập đến Google Colab tại hai vị trí trong phần **Báo cáo hiệu năng (Performance Requirements)** của Milestone 1 và Milestone 2:

> *"The scraper’s (and parser’s) performance should also be illustrated through two main points, running time and memory footprint... **The testbed for the final benchmarking is a Google Colab instance running on CPU-only mode. No upper limit on the running time of the scraper is enforced, while the upper limit on maximum disk usage is given by the Colab instance.**"*

### 6.2. Bản chất khoa học: Google Colab được dùng để làm gì?
1. **Google Colab là môi trường chuẩn hóa (Standard Hardware Testbed):**  
   Trong các cuộc thi hoặc đồ án khoa học dữ liệu, mỗi sinh viên sử dụng một máy tính cá nhân khác nhau (từ laptop 2 nhân RAM 4GB đến PC máy trạm 16 nhân RAM 64GB). Việc so sánh trực tiếp thời gian chạy hay bộ nhớ giữa các máy tính cá nhân là không công bằng và không có tính chuẩn hóa.  
   Giảng viên đưa ra môi trường Google Colab CPU-only (2 vCPU, RAM 12,7 GB) làm **thước đo chung tiêu chuẩn** để đo hiệu năng hệ thống của các nhóm trên cùng một hệ quy chiếu.
2. **Colab phục vụ bài đo Benchmark, không phải toàn bộ 85 giờ cào dữ liệu:**  
   - Để cào đủ 25.000 bài báo có dừng 3 giây/lần tải, tổng thời gian mạng tối thiểu là **hơn 84 giờ liên tục**.  
   - Google Colab miễn phí ngắt kết nối cưỡng bức sau **tối đa 12 giờ**.  
   - Do đó, việc yêu cầu cào toàn bộ 25.000 bài trong một phiên Colab duy nhất là **bất khả thi về mặt vật lý**.
   - Tại buổi Q&A, Giảng viên đã giải thích: Sinh viên được phép chia nhiều phiên, lưu log thời gian đối chiếu; đồng thời phép đo hiệu năng chuẩn hóa trên Colab được thực hiện thông qua **mẫu đo đạc chuẩn (Calibrated Benchmark Sample)**.

### 6.3. Cần làm những gì trên Google Colab để đạt điểm tối đa?

#### Nhiệm vụ 1: Đo kiểm hiệu năng Milestone 1 (Crawler Performance)
- Mở Colab ở chế độ `CPU-only`.
- Chạy công cụ `src/benchmark.py` bọc ngoài 4 giai đoạn trên mẫu 20 bài báo của một thành viên (`--limit 20`):
  1. `discovery`: Đo thời gian phân giải danh sách và RAM tiêu thụ.
  2. `download`: Đo RAM đỉnh qua hàm nhân `getrusage` (trên Linux Colab đạt ~58,89 MB), thời gian thực tế (~503 giây).
  3. `corpus_builder`: Đo thời gian giải nén và lọc TeX (~0,7 giây).
  4. `reference_builder`: Đo thời gian gọi Semantic Scholar API (~3,1 giây).
- Xuất ra 4 dòng kết quả thực nghiệm trong `logs/benchmark_runs.csv` với trường `testbed` mang nhãn `Linux-... (Python 3.x, RAM 12.7GB)`.
- Đưa bảng và phân tích này vào sổ tay [03-performance.ipynb](file:///d:/introds-arxiv-project/book/milestone1/03-performance.ipynb).

#### Nhiệm vụ 2: Đo kiểm hiệu năng Milestone 2 (Parser Performance)
- Tương tự như Milestone 1, khi hoàn thiện bộ phân tích cú pháp `src/parse_main.py`:
- Chạy `benchmark.py` trên Google Colab CPU-only để đo:
  - Thời gian thực thi toàn trình (end-to-end wall time).
  - Thời gian trung bình để bóc tách 1 bài báo (average time per publication).
  - Bộ nhớ RAM đỉnh của bộ bóc tách (maximum RAM used).
  - Dung lượng lưu trữ đầu ra sau khi khử trùng lặp.
- Đưa bảng so sánh vào sổ tay `milestone2/02-standardization.ipynb`.

#### Nhiệm vụ 3: Lưu trữ và đối soát nhật ký phiên chạy
- Mọi lần thực thi trên Colab nên liên kết với Google Drive (`drive.mount('/content/drive')`) để lưu lại nhật ký thời gian và dữ liệu, phục vụ minh chứng tính tái lập (reproducibility) của đồ án.

