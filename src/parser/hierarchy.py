"""Dựng cây phân cấp từ văn bản LaTeX đã chuẩn hoá.

Tuần 1: extract_body, infer_levels, strip_references, split_sentences — hàm thuần tuý,
nhận một chuỗi trả một kết quả, test bằng tests/test_hierarchy.py.
Tuần 2: build_tree — cần đầu ra của gather/normalize/bib_dedup.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from .normalize import strip_noncontent


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

    Cấp section lấy từ infer_levels(): cấp 1 -> kind "section", 2 -> "subsection",
    3 -> "subsubsection", từ 4 trở xuống -> "paragraph". Lớp book có \\chapter thì
    chapter là "section" và \\section là "subsection".

    Node gốc có content rỗng; build_store() tự gán f"{arxiv_id}v{version}" khi băm.

    >>> t = build_tree(r"\\begin{document}\\section{Intro} A b. C d.\\end{document}")
    >>> [(c.kind, c.content) for c in t.children[0].children]
    [('sentence', 'A b.'), ('sentence', 'C d.')]
    """
    body = _strip_comments(strip_references(extract_body(tex)))
    levels = infer_levels(body)
    root = Node("document", "")

    # stack: (cấp, node). Gốc ở cấp 0, mọi section có cấp >= 1.
    stack: list[tuple[int, Node]] = [(0, root)]
    pos = 0
    for m in SECTION_CMD.finditer(body):
        if m.start() < pos:          # nằm trong tiêu đề của heading trước — bỏ qua
            continue
        stack[-1][1].children.extend(_parse_block(body[pos:m.start()]))
        title, pos = _read_group(body, m.end() - 1)
        level = levels[m.group(1)]
        while stack[-1][0] >= level:
            stack.pop()
        node = Node(_LEVEL_KIND.get(level, "paragraph"), _clean_prose(title))
        stack[-1][1].children.append(node)
        stack.append((level, node))
    stack[-1][1].children.extend(_parse_block(body[pos:]))
    return root


# --------------------------------------------------------------------------- #
# Tiện ích của build_tree
# --------------------------------------------------------------------------- #
_LEVEL_KIND = {1: "section", 2: "subsection", 3: "subsubsection"}

# Môi trường thành lá kind="figure" (đề gộp bảng vào hình; tabular/algorithm đứng
# riêng cũng là khối hình-bảng, tách câu bên trong chỉ ra rác).
#
# LUẬT "NGOÀI CÙNG THẮNG": chỉ môi trường ngoài cùng khớp danh sách mới thành lá, và
# lá giữ NGUYÊN VĂN cả khối — không quét vào bên trong nữa. Nên \begin{table}...
# \begin{tabular}...\end{tabular}...\end{table} là MỘT node figure, figure chứa các
# subfigure cũng là MỘT node. tabular chỉ thành lá riêng khi nó đứng ngoài mọi
# table/figure (vd. trong center, trong \item).
#
# algorithm không phải hình cũng không phải bảng; gán "figure" là lựa chọn thực dụng
# vì trong 10 kind cho phép không có giá trị nào gần hơn (ghi rõ trong báo cáo).
_FIGURE_ENVS = frozenset({
    "figure", "figure*", "table", "table*", "subfigure", "subtable",
    "wrapfigure", "wraptable", "sidewaysfigure", "sidewaystable",
    "longtable", "longtable*", "tabular", "tabular*", "tabularx",
    "algorithm", "algorithm*",
})

# Môi trường thành lá kind="formula". normalize đưa khối về equation, nhưng vẫn bắt
# các biến thể phòng khi văn bản chưa qua normalize.
_FORMULA_ENVS = frozenset({
    "equation", "equation*", "align", "align*", "alignat", "alignat*",
    "gather", "gather*", "multline", "multline*", "flalign", "flalign*",
    "eqnarray", "eqnarray*", "displaymath", "math", "dmath", "dmath*",
})

_LIST_ENVS = frozenset({"itemize", "enumerate", "description"})

# Môi trường bóc vỏ có đối số bắt buộc vô nghĩa ({width}, {số cột}) — bỏ luôn đối số.
_ENVS_WITH_ARG = frozenset({"minipage", "multicols", "adjustbox"})

_BEGIN = re.compile(r"\\begin\s*\{([A-Za-z@]+\*?)\}")
_ENV_TOKEN = re.compile(r"\\(begin|end)\s*\{([A-Za-z@]+\*?)\}")
# Toán khối viết tắt: $$...$$ và \[...\] (không bắt \\[2pt] xuống dòng).
_DISPLAY = re.compile(r"\$\$.*?\$\$|(?<!\\)\\\[.*?\\\]", re.DOTALL)
# Ranh giới \item ở độ sâu 0 — cần biết \begin/\end để bỏ qua danh sách lồng.
_LIST_TOKEN = re.compile(r"\\(begin|end)\s*\{[A-Za-z@]+\*?\}|\\item(?![A-Za-z])\s*")

# Lệnh không mang nội dung (\label, \maketitle, \vspace...) bỏ bằng
# normalize.strip_noncontent() — nguồn sự thật duy nhất, clean_latex cũng gọi nó.
# KHÔNG thêm danh sách lệnh riêng ở file này.
# \end{...} lạc trong văn xuôi: môi trường bị heading cắt ngang, vd.
# \begin{appendix}\section{A}...\end{appendix}. Chỉ bỏ khi tách câu.
_STRAY_END = re.compile(r"\\end\s*\{[A-Za-z@]+\*?\}")
_HAS_WORD = re.compile(r"\w")


def _read_group(s: str, i: int, open_: str = "{", close: str = "}") -> tuple[str, int]:
    """s[i] là dấu mở. Trả (nội dung bên trong, vị trí ngay sau dấu đóng khớp).

    Bỏ qua ký tự bị escape (\\{). Thiếu dấu đóng thì lấy tới hết chuỗi.
    """
    depth = 0
    j = i
    while j < len(s):
        c = s[j]
        if c == "\\":
            j += 2
            continue
        if c == open_:
            depth += 1
        elif c == close:
            depth -= 1
            if depth == 0:
                return s[i + 1:j], j + 1
        j += 1
    return s[i + 1:], len(s)


def _skip_args(s: str, i: int, mandatory: int = 0) -> int:
    """Bỏ qua một [tuỳ chọn] và `mandatory` nhóm {...} đứng ngay từ vị trí i."""
    j = i + _leading_ws(s, i)
    if j < len(s) and s[j] == "[":
        _, j = _read_group(s, j, "[", "]")
    for _ in range(mandatory):
        k = j + _leading_ws(s, j)
        if k < len(s) and s[k] == "{":
            _, j = _read_group(s, k)
    return j


def _find_env_end(s: str, start: int, name: str) -> tuple[int, int]:
    """Tìm \\end{name} khớp với \\begin{name} vừa đọc xong ở vị trí start.

    Đếm lồng nhau cùng tên (itemize trong itemize). Trả (đầu \\end, cuối \\end);
    thiếu \\end thì coi môi trường kéo tới hết chuỗi.
    """
    depth = 1
    for m in _ENV_TOKEN.finditer(s, start):
        if m.group(2) != name:
            continue
        depth += 1 if m.group(1) == "begin" else -1
        if depth == 0:
            return m.start(), m.end()
    return len(s), len(s)


def _collapse(s: str) -> str:
    return " ".join(s.split())


def _clean_prose(s: str) -> str:
    return _collapse(strip_noncontent(s))


def _sentences(prose: str) -> list[Node]:
    prose = _STRAY_END.sub(" ", strip_noncontent(prose))
    return [Node("sentence", t) for t in split_sentences(prose) if _HAS_WORD.search(t)]


def _parse_block(text: str) -> list[Node]:
    """Bóc môi trường thành node TRƯỚC, phần văn xuôi còn lại mới đem tách câu."""
    out: list[Node] = []
    pos = 0
    while True:
        mb = _BEGIN.search(text, pos)
        md = _DISPLAY.search(text, pos)
        if md and (not mb or md.start() < mb.start()):
            out.extend(_sentences(text[pos:md.start()]))
            out.append(Node("formula", _collapse(md.group(0))))
            pos = md.end()
            continue
        if not mb:
            out.extend(_sentences(text[pos:]))
            return out

        out.extend(_sentences(text[pos:mb.start()]))
        name = mb.group(1)
        inner_end, env_end = _find_env_end(text, mb.end(), name)

        if name in _FIGURE_ENVS:
            out.append(Node("figure", _collapse(text[mb.start():env_end])))
        elif name in _FORMULA_ENVS:
            out.append(Node("formula", _collapse(text[mb.start():env_end])))
        elif name in _LIST_ENVS:
            node = _parse_list(text[_skip_args(text, mb.end()):inner_end])
            if node.children:
                out.append(node)
        else:
            # lemma, theorem, proof, abstract, center...: bỏ vỏ, ruột xử lý như văn xuôi
            # (ruột vẫn có thể chứa equation/figure/itemize nên gọi đệ quy).
            if name.rstrip("*") in _ENVS_WITH_ARG:
                inner_start = _skip_args(text, mb.end(), mandatory=1)
            else:
                inner_start = mb.end()
            out.extend(_parse_block(text[inner_start:inner_end]))
        pos = env_end


def _parse_list(inner: str) -> Node:
    """Ruột của itemize/enumerate/description -> node itemize, mỗi \\item một con."""
    cuts: list[tuple[int, int]] = []          # (đầu, cuối) của các \item ở độ sâu 0
    depth = 0
    for m in _LIST_TOKEN.finditer(inner):
        if m.group(1) == "begin":
            depth += 1
        elif m.group(1) == "end":
            depth -= 1
        elif depth == 0:
            cuts.append((m.start(), m.end()))

    node = Node("itemize", _list_text(inner))
    for k, (_, start) in enumerate(cuts):
        end = cuts[k + 1][0] if k + 1 < len(cuts) else len(inner)
        raw = inner[start:end]
        if raw.startswith("["):                   # \item[nhãn] -> giữ chữ của nhãn
            label, after = _read_group(raw, 0, "[", "]")
            raw = label + " " + raw[after:]
        content = _list_text(raw)                 # item có thể chứa danh sách lồng
        if not content:
            continue
        # LUÔN tách câu, kể cả khi item chỉ có một câu: item là node chứa, câu luôn
        # là lá kind="sentence". Nếu item một câu lại là lá, thì khi v2 thêm câu vào
        # item đó, cùng câu ấy bị băm với kind "item" ở v1 và "sentence" ở v2 -> hai
        # element_id -> dedup hỏng đúng ở loại sửa đổi phổ biến nhất.
        node.children.append(Node("item", content, _parse_block(raw)))
    return node


# Vỏ của danh sách: \item[nhãn] và \begin{itemize}[tuỳ chọn] / \end{itemize}.
_ITEM_MARK = re.compile(r"\\item(?![A-Za-z])\s*(?:\[([^\]]*)\])?")
_LIST_WRAP = re.compile(
    r"\\begin\s*\{(?:itemize|enumerate|description)\}(?:\s*\[[^\]]*\])?"
    r"|\\end\s*\{(?:itemize|enumerate|description)\}"
)
_ITEM_SEP = "\x02"


def _list_text(raw: str) -> str:
    """Content sạch của node itemize/item: bỏ vỏ danh sách, mỗi point một dòng.

    Schema mục 1.1: content là nội dung đã chuẩn hoá — không được để \\item hay
    \\begin{itemize} thô lọt vào (sẽ lộ ra trong dataset M3 và làm đỏ phép kiểm
    "không còn lệnh LaTeX sót"). \\item được thay bằng dấu xuống dòng làm dấu phân
    cách point, nhãn của \\item[nhãn] được giữ lại như chữ thường. Danh sách lồng
    trong item cũng được làm sạch theo cùng cách.

    >>> _list_text(r"\\item Alpha is good. \\item Beta only.")
    'Alpha is good.\\nBeta only.'
    >>> _list_text(r"Third \\begin{enumerate}[a)] \\item n1 \\item[X] n2 \\end{enumerate}")
    'Third\\nn1\\nX n2'
    """
    text = _ITEM_MARK.sub(lambda m: _ITEM_SEP + (m.group(1) or "") + " ", raw)
    text = strip_noncontent(_LIST_WRAP.sub(" ", text))
    parts = (_collapse(p) for p in text.split(_ITEM_SEP))
    return "\n".join(p for p in parts if p)
