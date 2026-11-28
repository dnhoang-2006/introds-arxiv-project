"""Hai bộ xếp hạng ứng viên: baseline và model học được.

Cả hai cùng một giao diện — `fit(X, y)` rồi `score(X)` — nên `match_main.py`
đổi qua lại chỉ bằng một cờ dòng lệnh.

Vì sao phải có baseline
-----------------------
M3 câu 7: một nhóm báo MRR@5 = 1,0, và thầy chỉ ra baseline chỉ so tiêu đề,
không học gì, cũng đã đạt ≈ 0,99. Không có baseline thì con số của model không
chứng minh được điều gì. `TitleBaseline` ở đây chính là baseline đó.

Về "kiến thức ngoài"
--------------------
M3 câu 4 ý 6 chốt LogisticRegression, RandomForest, LightGBM, TF-IDF huấn luyện
trên chính corpus của nhóm **không** tính là kiến thức ngoài. Gọi API bên ngoài
hoặc tải model đã huấn luyện sẵn thì mới tính. Module này chỉ dùng
scikit-learn huấn luyện tại chỗ.
"""
from __future__ import annotations

from typing import Protocol

try:
    from matching.features import FEATURE_NAMES  # pyrefly: ignore[missing-import]
except ImportError:
    from .features import FEATURE_NAMES

TITLE_SIM_INDEX = FEATURE_NAMES.index("title_sim")


class Ranker(Protocol):
    name: str

    def fit(self, X: list[list[float]], y: list[int]) -> "Ranker": ...
    def score(self, X: list[list[float]]) -> list[float]: ...


class TitleBaseline:
    """Xếp hạng bằng đúng độ tương đồng tiêu đề. Không học gì.

    `fit()` cố ý không làm gì — baseline phải độc lập với dữ liệu huấn luyện,
    nếu không nó không còn là mốc so sánh trung thực.
    """

    name = "baseline-title"

    def fit(self, X: list[list[float]], y: list[int]) -> "TitleBaseline":
        return self

    def score(self, X: list[list[float]]) -> list[float]:
        return [row[TITLE_SIM_INDEX] for row in X]


class LogisticRanker:
    """LogisticRegression trên toàn bộ vector đặc trưng.

    `class_weight="balanced"` là bắt buộc chứ không phải tuỳ chọn: mỗi entry sinh
    n hàng mà nhiều nhất một hàng là dương, với trung vị 13 reference mỗi bài thì
    tỉ lệ dương chỉ khoảng 7%. Không cân lại trọng số thì model đoán "không khớp"
    cho mọi hàng vẫn đạt 93% accuracy mà MRR bằng 0.
    """

    name = "logreg"

    def __init__(self, *, seed: int = 42, max_iter: int = 1000) -> None:
        self.seed = seed
        self.max_iter = max_iter
        self._clf = None
        self._constant: float | None = None

    def fit(self, X: list[list[float]], y: list[int]) -> "LogisticRanker":
        from sklearn.linear_model import LogisticRegression

        classes = set(y)
        if len(classes) < 2:
            # Tập huấn luyện chưa có cả hai lớp (thường gặp khi chạy thử --limit
            # nhỏ). Không ném lỗi, cũng không giả vờ đã học: trả điểm hằng số để
            # match_main còn chạy hết được, và báo rõ ở phần tóm tắt.
            self._constant = float(next(iter(classes))) if classes else 0.0
            return self
        self._clf = LogisticRegression(
            class_weight="balanced", max_iter=self.max_iter, random_state=self.seed
        ).fit(X, y)
        return self

    def score(self, X: list[list[float]]) -> list[float]:
        if self._clf is None:
            return [self._constant or 0.0] * len(X)
        return [float(p) for p in self._clf.predict_proba(X)[:, 1]]

    @property
    def coefficients(self) -> dict[str, float] | None:
        """Hệ số theo tên đặc trưng — đưa lên poster được ở phần phân tích."""
        if self._clf is None:
            return None
        return dict(zip(FEATURE_NAMES, (float(c) for c in self._clf.coef_[0])))


#: Tên dùng ở `--model`.
RANKERS = {"baseline": TitleBaseline, "logreg": LogisticRanker}


def build_ranker(name: str, *, seed: int = 42) -> Ranker:
    if name not in RANKERS:
        raise ValueError(f"--model không hợp lệ: {name!r}. Chọn: {sorted(RANKERS)}")
    cls = RANKERS[name]
    return cls(seed=seed) if cls is LogisticRanker else cls()
