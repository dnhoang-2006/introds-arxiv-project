# So sánh 3 nguồn metadata arXiv

- **API**: paper_meta.json, lấy từ 2026-11-02 đến 2026-11-02
- **OAI**: định dạng arXivRaw, lấy từ 2026-11-02 đến 2026-11-02
- **Kaggle**: Cornell snapshot ngày 2026-11-01

## Độ phủ

| source | n_assigned | n_present | n_missing |
|---|---|---|---|
| API | 5000 | 5000 | 0 |
| OAI | 5000 | 500 | 4500 |
| Kaggle | 5000 | 5000 | 0 |

## Khớp cả 3 nguồn trên tập ID chung

| field | n_common | all_three_identical | all_three_after_normalize | any_disagreement |
|---|---|---|---|---|
| title | 500 | 491 | 500 | 0 |
| authors | 500 | 482 | 497 | 3 |
| venue | 500 | 499 | 499 | 1 |
| submission_date | 500 | 500 | 500 | 0 |
| latest_date | 500 | 500 | 500 | 0 |
| n_versions | 500 | 500 | 500 | 0 |

## Khớp theo từng cặp nguồn

| pair | field | n_compared | identical | normalized_equal | different | only_left | only_right | both_null |
|---|---|---|---|---|---|---|---|---|
| API vs OAI | title | 500 | 491 | 9 | 0 | 0 | 0 | 0 |
| API vs OAI | authors | 500 | 482 | 15 | 3 | 0 | 0 | 0 |
| API vs OAI | venue | 500 | 65 | 0 | 0 | 0 | 1 | 434 |
| API vs OAI | submission_date | 500 | 500 | 0 | 0 | 0 | 0 | 0 |
| API vs OAI | latest_date | 500 | 500 | 0 | 0 | 0 | 0 | 0 |
| API vs OAI | n_versions | 500 | 500 | 0 | 0 | 0 | 0 | 0 |
| API vs Kaggle | title | 5000 | 4892 | 107 | 1 | 0 | 0 | 0 |
| API vs Kaggle | authors | 5000 | 4850 | 132 | 18 | 0 | 0 | 0 |
| API vs Kaggle | venue | 5000 | 727 | 1 | 0 | 0 | 3 | 4269 |
| API vs Kaggle | submission_date | 5000 | 5000 | 0 | 0 | 0 | 0 | 0 |
| API vs Kaggle | latest_date | 5000 | 4999 | 0 | 1 | 0 | 0 | 0 |
| API vs Kaggle | n_versions | 5000 | 4999 | 0 | 1 | 0 | 0 | 0 |
| OAI vs Kaggle | title | 500 | 500 | 0 | 0 | 0 | 0 | 0 |
| OAI vs Kaggle | authors | 500 | 500 | 0 | 0 | 0 | 0 | 0 |
| OAI vs Kaggle | venue | 500 | 66 | 0 | 0 | 0 | 0 | 434 |
| OAI vs Kaggle | submission_date | 500 | 500 | 0 | 0 | 0 | 0 | 0 |
| OAI vs Kaggle | latest_date | 500 | 500 | 0 | 0 | 0 | 0 | 0 |
| OAI vs Kaggle | n_versions | 500 | 500 | 0 | 0 | 0 | 0 | 0 |

## Nguyên nhân lệch tác giả

| pair | cause | n_papers |
|---|---|---|
| API vs Kaggle | name_split_at_parenthesis | 5 |
| API vs Kaggle | raw_without_separator | 1 |
| API vs Kaggle | suffix_dropped | 12 |
| API vs OAI | name_split_at_parenthesis | 2 |
| API vs OAI | suffix_dropped | 1 |

## Số version

| source | how_version_count_is_known | n_papers | n_with_version_count | n_with_3plus_versions | n_3plus_with_all_version_dates |
|---|---|---|---|---|---|
| API | Suy từ hậu tố vN của entry_id; chỉ có ngày v1 và ngày bản mới nhất | 5000 | 5000 | 600 | 0 |
| OAI | Liệt kê từng <version> trong arXivRaw: ngày và dung lượng | 500 | 500 | 55 | 55 |
| Kaggle | Liệt kê từng phần tử versions: ngày, không có dung lượng | 5000 | 5000 | 600 | 600 |
