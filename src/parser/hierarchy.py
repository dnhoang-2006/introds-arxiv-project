"""Dựng cây phân cấp từ văn bản LaTeX đã chuẩn hoá.

Tuần 1: extract_body, infer_levels, strip_references, split_sentences — hàm thuần tuý,
nhận một chuỗi trả một kết quả, test bằng tests/test_hierarchy.py.
Tuần 2: build_tree — cần đầu ra của gather/normalize/bib_dedup.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field


@dataclass
class Node:
    kind: str                      # một trong 10 giá trị ở schema_m2.md mục 3
    content: str                   # nội dung ĐÃ chuẩn hoá và ĐÃ đổi tên \cite
    children: list["Node"] = field(default_factory=list)


# --------------------------------------------------------------------------- #
# Tiện ích chung
# --------------------------------------------------------------------------- #
# % không đứng sau dấu \ là bắt đầu comment (\% là ký tự phần trăm thật).
_COMMENT = re.compile(r"(?<!\\)%[^\n]*")


def _strip_comments(tex: str) -> str:
    return _COMMENT.sub("", tex)


# --------------------------------------------------------------------------- #
# 0. extract_body
# --------------------------------------------------------------------------- #
BODY = re.compile(r"\\begin\{document\}(.*?)(?:\\end\{document\}|$)", re.DOTALL)


def extract_body(tex: str) -> str:
    """Lấy phần thân, bỏ preamble (và mọi thứ sau \\end{document} — LaTeX bỏ qua chúng).

    Không cắt thì cả preamble (\\newtheorem, \\usepackage...) bị đem đi tách câu và
    dồn thành một "câu" hàng trăm nghìn ký tự.

    File con được \\input KHÔNG có \\begin{document} nên trả nguyên văn — nhánh này
    là bắt buộc (khoảng 58% file .tex trong corpus là file con), không phải phòng hờ.

    >>> extract_body(r"\\usepackage{x} \\begin{document} Body. \\end{document} junk")
    ' Body. '
    >>> extract_body("Child file. No preamble.")
    'Child file. No preamble.'
    """
    m = BODY.search(tex)
    return m.group(1) if m else tex


# --------------------------------------------------------------------------- #
# 1. infer_levels
# --------------------------------------------------------------------------- #
# Thứ tự lồng nhau CHUẨN của LaTeX, từ cao xuống thấp.
SECTION_ORDER = (
    "part", "chapter", "section", "subsection",
    "subsubsection", "paragraph", "subparagraph",
)

# \section{...}, \section*{...}, \section[ngắn]{dài}
SECTION_CMD = re.compile(
    r"\\(" + "|".join(SECTION_ORDER) + r")\*?\s*(?:\[[^\]]*\]\s*)?\{"
)


def infer_levels(tex: str) -> dict[str, int]:
    """Suy cấp độ của từng lệnh section dựa trên các lệnh THỰC SỰ có trong tài liệu.

    Không được hardcode "section luôn là cấp 1" — đề yêu cầu tự nhận diện, và
    bài dùng lớp book có \\chapter nằm trên \\section.

    Cách làm: lấy tập lệnh section xuất hiện trong chính tài liệu này, xếp theo thứ
    tự lồng nhau chuẩn của LaTeX (part > chapter > section > ...), rồi đánh số liên
    tiếp từ 1. Lệnh nào vắng mặt thì không chiếm cấp.

    Vì sao không xếp theo thứ tự xuất hiện lần đầu: nhiều bài có \\paragraph{...}
    trong phần abstract trước khi gặp \\section đầu tiên — xếp theo lần xuất hiện sẽ
    đẩy paragraph lên cấp 1, sai. Với tài liệu "bình thường" hai cách cho cùng kết quả.

    Bắt được cả dạng có dấu sao (\\section*{Appendix}) và dạng có tiêu đề ngắn
    (\\section[Ngắn]{Dài}). Lệnh nằm trong comment bị bỏ qua.

    >>> infer_levels(r"\\chapter{A} \\section{B} \\subsection{C}")
    {'chapter': 1, 'section': 2, 'subsection': 3}
    >>> infer_levels(r"\\section*{Intro} \\subsection{B}")
    {'section': 1, 'subsection': 2}
    """
    present = {m.group(1) for m in SECTION_CMD.finditer(_strip_comments(tex))}
    ordered = [cmd for cmd in SECTION_ORDER if cmd in present]
    return {cmd: i + 1 for i, cmd in enumerate(ordered)}


# --------------------------------------------------------------------------- #
# 2. strip_references
# --------------------------------------------------------------------------- #
_REF_TITLES = r"(?:References?|Bibliography|Literature\s+Cited|Works\s+Cited|Tài\s+liệu\s+tham\s+khảo)"

# Tiêu đề section/chapter mang tên References
_REF_HEADING = re.compile(
    r"\\(?:chapter|section|subsection)\*?\s*(?:\[[^\]]*\]\s*)?\{\s*" + _REF_TITLES + r"\s*\}",
    re.IGNORECASE,
)

# Điểm kết thúc của một section References: heading cùng cấp trở lên, \appendix,
# hoặc hết tài liệu. Phần sau điểm này (Appendix, Acknowledgements) được GIỮ.
_REF_SECTION_END = re.compile(
    r"\\(?:part|chapter|section)\*?\s*(?:\[[^\]]*\]\s*)?\{|\\appendix\b|"
    r"\\begin\{appendix\}|\\end\{document\}"
)

# Các môi trường danh mục tài liệu: thebibliography (chuẩn), references (AAS/MNRAS)
_BIB_ENV = re.compile(
    r"\\begin\{(thebibliography|references)\}.*?(?:\\end\{\1\}|$)",
    re.DOTALL,
)

# Lệnh in danh mục từ file .bib: \bibliography{refs}, \bibliographystyle{plain},
# \printbibliography[...]
_BIB_CMDS = re.compile(
    r"\\bibliography(?:style)?\s*\{[^}]*\}|\\printbibliography\b(?:\s*\[[^\]]*\])?"
)


def strip_references(tex: str) -> str:
    """Bỏ phần References khỏi văn bản trước khi dựng cây.

    Đề: References KHÔNG được parse vào cây, nhưng Acknowledgements và Appendix
    thì BẮT BUỘC phải giữ — kể cả khi chúng nằm SAU phần References.

    Nên cắt đúng đoạn thebibliography rồi NỐI LẠI phần sau, đừng cắt thẳng từ
    References tới hết file.

    Ba lớp cắt, theo thứ tự:
        1. Section mang tên References/Bibliography: cắt từ heading tới heading
           cùng cấp kế tiếp (hoặc \\appendix, \\end{document}) — phần sau giữ lại.
        2. Môi trường thebibliography/references còn sót ở bất kỳ đâu.
        3. Lệnh \\bibliography{...}, \\bibliographystyle{...}, \\printbibliography.

    >>> out = strip_references(r"A. \\begin{thebibliography}{9}\\bibitem{x}Y\\end{thebibliography} \\section*{Appendix} B.")
    >>> "Appendix" in out and "bibitem" not in out
    True
    """
    # Lớp 1: section mang tên References. Lặp vì hiếm khi có hai (vd. "References"
    # và "Supplementary References").
    pos = 0
    pieces: list[str] = []
    while True:
        m = _REF_HEADING.search(tex, pos)
        if not m:
            pieces.append(tex[pos:])
            break
        pieces.append(tex[pos:m.start()])
        # Bỏ qua chính môi trường thebibliography nằm trong section (nó có thể
        # chứa chữ giống heading), rồi mới tìm điểm kết thúc section.
        body_start = m.end()
        env = _BIB_ENV.match(tex, body_start + _leading_ws(tex, body_start))
        search_from = env.end() if env else body_start
        end = _REF_SECTION_END.search(tex, search_from)
        pos = end.start() if end else len(tex)
    tex = " ".join(p for p in pieces if p)

    # Lớp 2 và 3.
    tex = _BIB_ENV.sub(" ", tex)
    tex = _BIB_CMDS.sub(" ", tex)
    return tex


def _leading_ws(s: str, start: int) -> int:
    """Số ký tự khoảng trắng liên tiếp bắt đầu từ vị trí start."""
    n = 0
    while start + n < len(s) and s[start + n].isspace():
        n += 1
    return n


# --------------------------------------------------------------------------- #
# 3. split_sentences
# --------------------------------------------------------------------------- #
# Viết tắt mà dấu chấm KHÔNG kết thúc câu. Phân biệt hoa/thường có chủ đích:
# "No." là viết tắt của Number, còn "no." cuối câu ("the answer is no.") thì không.
_ABBREVIATIONS = (
    # Latin / tiếng Anh học thuật
    r"i\.e", r"e\.g", r"I\.e", r"E\.g", r"et\s+al", r"cf", r"Cf", r"vs", r"Vs",
    r"resp", r"approx", r"viz", r"w\.r\.t", r"a\.k\.a", r"ca", r"pp", r"vol", r"Vol",
    # Tham chiếu trong bài báo
    r"Fig", r"Figs", r"Eq", r"Eqs", r"Eqn", r"Sec", r"Secs", r"Sect", r"Tab", r"Tabs",
    r"Ref", r"Refs", r"Thm", r"Lem", r"Def", r"Prop", r"Cor", r"Alg", r"Ch", r"Chap",
    r"App", r"No", r"Nos",
    # Danh xưng
    r"Dr", r"Prof", r"Mr", r"Mrs", r"Ms", r"St", r"Jr",
)

# Những đoạn được CHE trước khi tách, theo thứ tự (cái dài/ôm ngoài che trước).
_PROTECT: tuple[re.Pattern[str], ...] = (
    # Môi trường bất kỳ: \begin{equation}...\end{equation}, \begin{figure}...
    re.compile(r"\\begin\{([A-Za-z]+\*?)\}.*?\\end\{\1\}", re.DOTALL),
    # Toán inline: $...$ và \(...\)
    re.compile(r"\$[^$]+\$"),
    re.compile(r"\\\(.*?\\\)", re.DOTALL),
    # URL trần — không nuốt dấu câu đứng cuối URL
    re.compile(r"(?:https?|ftp)://[^\s{}]+?(?=[.,;:!?)\]]*(?:\s|$))"),
    # Lệnh LaTeX có đối số: \cite{a.b}, \ref{fig:1.2}, \url{...}, \href{..}{..}
    re.compile(r"\\[A-Za-z]+\*?(?:\s*\[[^\]]*\])*(?:\s*\{[^{}]*\})+"),
    # Số thập phân: 3.14, 0.5
    re.compile(r"(?<![\w.])\d+\.\d+(?![\w.]*\d)"),
    # Viết tắt
    re.compile(r"(?<![A-Za-z])(?:" + "|".join(_ABBREVIATIONS) + r")\."),
)

_MASK = re.compile(r"\x00(\d+)\x00")

# Ranh giới câu: . ! ? (có thể kèm ngoặc/nháy đóng), rồi khoảng trắng, rồi một
# ký tự mở đầu câu (chữ hoa, CHỮ SỐ, lệnh LaTeX, ngoặc mở, đoạn đã che, dấu nháy).
#   - Có chữ số: "...was 0.82. 95% confidence intervals..." là hai câu. An toàn vì
#     các viết tắt hay đứng trước số (Fig. 2, et al. 2019, Sec. 3) đã bị che.
#   - CỐ Ý không có chữ thường: dấu chấm + chữ thường trong văn học thuật gần như
#     luôn là viết tắt chưa bắt được ("approx. the same"), không phải hết câu.
_BOUNDARY = re.compile(
    r"([.!?]+[\"')\]]*)\s+(?=[A-ZÀ-ỸĐ\d\\(\[\x00\"'`])"
)


def split_sentences(text: str) -> list[str]:
    """Tách văn xuôi thành câu.

    Đề: không được cắt bên trong công thức, lệnh, từ viết tắt (i.e., et al., Fig. 1),
    URL, hay số thập phân — "a dot that does not end a sentence does not create a new leaf".

    Cách an toàn: CHE các đoạn đó bằng placeholder -> tách -> BỎ CHE.

    Ca test tối thiểu, phải ra đúng 3 câu:
        "We use BERT (Devlin et al. 2019). The result is 3.14 times better.
         See Fig. 2 for details."

    >>> len(split_sentences("We use BERT (Devlin et al. 2019). The result is 3.14 times better. See Fig. 2 for details."))
    3
    """
    store: list[str] = []

    def mask(m: re.Match[str]) -> str:
        store.append(m.group(0))
        return f"\x00{len(store) - 1}\x00"

    for pat in _PROTECT:
        text = pat.sub(mask, text)

    marked = _BOUNDARY.sub(lambda m: m.group(1) + "\x01", text)

    out: list[str] = []
    for part in marked.split("\x01"):
        # Bỏ che lặp lại: một đoạn đã che có thể chứa placeholder của đoạn che trước
        # (vd. \footnote{... $x$ ...} chứa toán inline đã che).
        while _MASK.search(part):
            part = _MASK.sub(lambda m: store[int(m.group(1))], part)
        part = " ".join(part.split())
        if part:
            out.append(part)
    return out


# --------------------------------------------------------------------------- #
# 4. build_tree — tuần 2
# --------------------------------------------------------------------------- #
def build_tree(tex: str) -> Node:
    """Dựng cây hoàn chỉnh của MỘT version.

    Thứ tự: extract_body -> strip_references -> infer_levels -> duyệt và dựng cây
            -> bóc môi trường thành lá -> tách câu phần văn xuôi còn lại.
    Lá gồm: sentence, formula, figure (bảng tính là figure).
    \\begin{itemize} là node `itemize`, mỗi \\item là node con `item`.

    ⚠️ BÓC MÔI TRƯỜNG TRƯỚC, TÁCH CÂU SAU. split_sentences che nguyên cả môi trường
    nên nếu đưa thẳng vào thì mỗi figure/table thành một "câu" khổng lồ. Trên 300 file
    thật, các khối quá dài bắt đầu bằng: figure 17, table 13, lemma 11, table* 8, theorem 6.
        figure, figure*, table, table*        -> kind="figure" (đề gộp bảng vào hình)
        equation (đã chuẩn hoá bởi normalize) -> kind="formula"
        lemma, theorem, proposition, proof... -> KHÔNG phải lá: coi là văn xuôi,
                                                 bỏ vỏ \\begin/\\end rồi tách câu bên trong
    """
    raise NotImplementedError
