# Nhãn Milestone 3

Định dạng và quy ước: xem `docs/schema_m3.md`.

    labels/manual/<MSSV>.jsonl    gán tay, 5 publication mỗi người, tối thiểu 20 nhãn mỗi bài
    labels/auto/<MSSV>.jsonl      matcher tự động, 500 publication mỗi người

Một dòng JSON mỗi nhãn:

    {"arxiv_id": "2507.06659", "citation_key": "vaswani2017",
     "groundtruth_arxiv_id": "1706.03762", "labeler": "24120053", "method": "manual"}

`groundtruth_arxiv_id` để `null` khi entry không khớp reference nào. Dòng đó vẫn
sinh hàng trong candidate matrix (dữ liệu âm) nhưng không vào mẫu số khi tính MRR@5.
