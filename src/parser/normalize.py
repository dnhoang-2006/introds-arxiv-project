"""Chuẩn hoá LaTeX và chuẩn hoá công thức toán.

!!!!!!!!!! MODULE NÀY QUYẾT ĐỊNH DEDUP CỦA CẢ NHÓM.

element_id được băm từ ĐẦU RA của module này (docs/schema_m2.md mục 2). Chuẩn hoá yếu
thì hai câu giống nhau ở v1 và v2 chỉ khác một dấu cách sẽ thành hai element khác nhau,
và dedup thất bại. Quy tắc dưới đây phải ĐÓNG BĂNG trước khi parse 25.000 bài: sửa sau đó
là toàn bộ element_id đổi theo và phải parse lại từ đầu.

Dùng theo đúng thứ tự (schema_m2.md mục 4):

    clean = normalize_math(clean_latex(raw))

QUYẾT ĐỊNH THIẾT KẾ (ghi ở đây để cả nhóm biết)
-------------------------------------------------
1. Comment `%...` bị BỎ TRƯỚC TIÊN, bằng đúng regex của hierarchy._COMMENT. Nếu không,
   một `$$` nằm trong comment có thể ghép cặp với `$$` thật và làm hỏng công thức.
2. `\\label{...}` bị XOÁ (nhãn là điểm neo, không phải chữ; đổi tên nhãn giữa các
   version làm figure/công thức khác nhau dù cùng nội dung). `\\ref`, `\\cite`, `\\eqref`
   được GIỮ NGUYÊN: `\\cite` còn được bib_dedup đổi tên ở bước 4 của pipeline.
3. Lệnh kiểu chữ `\\textbf \\textit \\emph \\texttt \\textsc \\textsl \\underline`:
   bỏ lệnh, giữ ruột (xử lý ngoặc lồng bằng bộ đếm ngoặc, không bằng regex).
   KHÔNG đụng `\\text{}`, `\\mbox{}`, `\\textrm{}`: chúng nằm trong công thức thì mang nghĩa.
4. Khoảng trắng: dòng trống (`\\n\\n`) là ranh giới đoạn và được GIỮ (đúng một `\\n\\n`);
   mọi khoảng trắng khác, kể cả xuống dòng đơn, tab, NBSP, gộp thành MỘT dấu cách. Nhờ vậy
   cùng một câu bị ngắt dòng khác nhau ở hai version vẫn cho cùng một element_id.
5. Trong `figure`/`table`, bỏ khoảng trắng quanh `\\includegraphics`, `\\caption`...
   để `\\centering` có hay không cũng không làm figure bị coi là khác nhau.
6. Công thức khối đưa về `\\begin{equation}...\\end{equation}`; `align`, `alignat`,
   `flalign`, `eqnarray` thành `equation` chứa `aligned`, còn `gather`, `multline` thành
   `equation` chứa `gathered` (vì `equation` thuần không chứa được `&` và `\\\\`).
   Công thức inline về `$...$`. Công thức rỗng bị bỏ.
7. Giữ NGUYÊN `\\includegraphics` và môi trường figure (đề Milestone 1 yêu cầu).

Giới hạn đã biết: không phân biệt `verbatim`/`lstlisting` (bên trong chúng khoảng trắng
và `%` cũng bị chuẩn hoá); `{\\small x}` đứng ngay sau một lệnh hoặc `}` được giữ ngoặc.

Bất biến bắt buộc, có test (kể cả fuzz):
    clean_latex(clean_latex(x))       == clean_latex(x)
    normalize_math(normalize_math(x)) == normalize_math(x)
    f(f(x)) == f(x) với f = normalize_math ∘ clean_latex
"""

from __future__ import annotations

import re

# Số lần lặp tối đa tới khi chuỗi hết đổi (điểm bất động). Thực tế hội tụ sau 2-3 lần.
MAX_PASSES = 10

# Dấu \ mở đầu một lệnh thật: đứng sau số CHẴN dấu \ (\\ là ngắt dòng, không phải lệnh).
# Group 1 là các cặp \\ đứng trước, phải trả lại nguyên vẹn khi thay thế.
_PRE = r"(?<!\\)((?:\\\\)*)\\"

# --------------------------------------------------------------------------- #
# clean_latex
# --------------------------------------------------------------------------- #
# GIỐNG HỆT hierarchy._COMMENT: \% là ký tự phần trăm thật, % còn lại mở comment.
_COMMENT = re.compile(r"(?<!\\)%[^\n]*")

_LABEL = re.compile(_PRE + r"label\s*\{[^{}]*\}")

# Tuỳ chọn vị trí sau \begin{figure}/{table}: [htbp], [H], [t!]...
_FLOAT_OPT = re.compile(_PRE + r"begin\{((?:figure|table)\*?)\}\s*\[[^\]]*\]")

_STYLE_CMDS = ("textbf", "textit", "emph", "texttt", "textsc", "textsl", "underline")
_STYLE_OPEN = re.compile(_PRE + r"(?:" + "|".join(_STYLE_CMDS) + r")\s*\{")

# Lệnh khai báo cỡ chữ/kiểu chữ: {\small abc} -> abc
_DECLS = (
    "centering", "raggedright", "raggedleft", "small", "footnotesize", "scriptsize",
    "tiny", "normalsize", "large", "Large", "LARGE", "huge", "Huge", "bfseries", "itshape",
)
_DECL_GROUP = re.compile(r"\{\s*(?:\\(?:" + "|".join(_DECLS) + r")(?![A-Za-z])\s*)+")

_BARE = re.compile(
    _PRE + r"(?:" + "|".join(_DECLS + (
        "midrule", "toprule", "bottomrule", "hline", "newpage", "clearpage", "noindent",
        "smallskip", "medskip", "bigskip",
    )) + r")(?![A-Za-z])"
)
_RULES_ARG = re.compile(_PRE + r"(?:cline|cmidrule)\s*(?:\([^)]*\))?\s*\{[^{}]*\}")
_SPACING_ARG = re.compile(_PRE + r"(?:vspace|hspace)\*?\s*\{[^{}]*\}")

# Một figure/table: group 1 = tên môi trường, group 2 = ruột.
_FLOAT_ENV = re.compile(r"\\begin\{((?:figure|table)\*?)\}(.*?)\\end\{\1\}", re.S)
_FLOAT_GAP = re.compile(
    r"\s+(?=\\(?:includegraphics|caption|subcaption|subfloat|centering|begin|end)(?![A-Za-z]))"
)

_PARA_BREAK = re.compile(r"\n\s*\n")
_AFTER_COMMAND = re.compile(r"(?:\\[A-Za-z]+\*?|[}\]])\s*$")


def _match_brace(s: str, open_idx: int) -> int | None:
    """Vị trí dấu `}` khớp với `{` ở open_idx. Bỏ qua \\{ và \\}. None nếu không khớp."""
    depth = 0
    i = open_idx
    n = len(s)
    while i < n:
        c = s[i]
        if c == "\\":
            i += 2
            continue
        if c == "{":
            depth += 1
        elif c == "}":
            depth -= 1
            if depth == 0:
                return i
        i += 1
    return None


def _unwrap_styles(s: str) -> str:
    r"""\textbf{a \emph{b}} -> a b. Đệ quy nên ngoặc lồng không làm hỏng tính ổn định."""
    out: list[str] = []
    i = 0
    while True:
        m = _STYLE_OPEN.search(s, i)
        if m is None:
            out.append(s[i:])
            break
        close = _match_brace(s, m.end() - 1)
        out.append(s[i:m.start()] + m.group(1))
        if close is None:                       # ngoặc không cân: bỏ lệnh, giữ phần còn lại
            i = m.end()
            continue
        out.append(_unwrap_styles(s[m.end():close]))
        i = close + 1
    return "".join(out)


def _unwrap_decl_groups(s: str) -> str:
    r"""{\small abc} đứng một mình -> abc. Nhưng \caption{\small abc} giữ ngoặc: đó là đối số."""
    out: list[str] = []
    i = 0
    while True:
        m = _DECL_GROUP.search(s, i)
        if m is None:
            out.append(s[i:])
            break
        brace = m.start()
        out.append(s[i:brace])
        close = _match_brace(s, brace)
        prefix = s[max(0, brace - 80):brace]
        standalone = close is not None and not _AFTER_COMMAND.search(prefix)
        if standalone:
            out.append(s[m.end():close])        # bỏ cả cặp ngoặc lẫn lệnh khai báo
            i = close + 1
        else:
            out.append("{")                     # chỉ bỏ lệnh khai báo, giữ ngoặc
            i = m.end()
    return "".join(out)


def _tidy_float(m: re.Match[str]) -> str:
    inner = _FLOAT_GAP.sub("", m.group(2)).strip()
    name = m.group(1)
    return f"\\begin{{{name}}}{inner}\\end{{{name}}}"


def _squash_whitespace(s: str) -> str:
    s = s.replace("\r\n", "\n").replace("\r", "\n")
    paragraphs = (" ".join(p.split()) for p in _PARA_BREAK.split(s))
    return "\n\n".join(p for p in paragraphs if p)


def _clean_once(s: str) -> str:
    s = _COMMENT.sub("", s)
    s = _LABEL.sub(lambda m: m.group(1), s)
    s = _FLOAT_OPT.sub(lambda m: m.group(1) + "\\begin{" + m.group(2) + "}", s)
    s = _unwrap_styles(s)
    s = _unwrap_decl_groups(s)
    s = _BARE.sub(lambda m: m.group(1) + " ", s)
    s = _RULES_ARG.sub(lambda m: m.group(1) + " ", s)
    s = _SPACING_ARG.sub(lambda m: m.group(1) + " ", s)
    s = _FLOAT_ENV.sub(_tidy_float, s)
    return _squash_whitespace(s)


def clean_latex(s: str) -> str:
    r"""Bỏ lệnh định dạng không mang nghĩa, giữ nội dung ngữ nghĩa.

    Bỏ      : comment %, \label{}, \centering, \raggedright, \midrule, \toprule, \hline,
              \vspace{...}, \hspace{...}, \noindent, lệnh cỡ chữ (\small, \large...),
              tuỳ chọn vị trí [htbp] sau \begin{figure}/{table}
    Giữ ruột: \textbf{x} -> x, \emph{x} -> x, \texttt{x} -> x (kể cả ngoặc lồng)
    Gộp     : khoảng trắng về một dấu cách, giữ đúng một "\n\n" giữa các đoạn
              (BẮT BUỘC cho dedup)

    GIỮ NGUYÊN \includegraphics, môi trường figure, \ref, \cite — đề Milestone 1 đã yêu cầu,
    Milestone 2 không đổi. Xem "QUYẾT ĐỊNH THIẾT KẾ" ở đầu file.

    ⚠️ PHẢI gọi strip_noncontent() ở trên để bỏ \\label, \\maketitle, \\vspace...
    hierarchy.build_tree() cũng gọi đúng hàm đó. Cần bỏ thêm lệnh nào thì bổ sung vào
    NONCONTENT_CMDS, KHÔNG viết danh sách riêng trong hàm này.

    Bất biến bắt buộc: clean_latex(clean_latex(x)) == clean_latex(x)
    (đạt bằng cách lặp tới khi chuỗi hết đổi).
    """
    for _ in range(MAX_PASSES):
        t = _clean_once(s)
        if t == s:
            break
        s = t
    return s


# --------------------------------------------------------------------------- #
# normalize_math
# --------------------------------------------------------------------------- #
_SPECIAL = re.compile(r"[\\$]")
_BEGIN_ENV = re.compile(r"\\begin\{([A-Za-z]+\*?)\}")
_ALIGNAT_ARG = re.compile(r"^\s*\{\d+\}")

_PLAIN_ENVS = {"equation", "equation*", "displaymath"}
_ALIGN_ENVS = {"align", "align*", "alignat", "alignat*", "flalign", "flalign*",
               "eqnarray", "eqnarray*"}
_GATHER_ENVS = {"gather", "gather*", "multline", "multline*"}


def _find_close(s: str, start: int, closer: str) -> int | None:
    """Vị trí đầu tiên của `closer` từ `start`, bỏ qua ký tự bị escape (\\$, \\\\...)."""
    k = start
    n = len(s)
    first = closer[0]
    while k < n:
        c = s[k]
        if c == "\\":
            if first == "\\" and s.startswith(closer, k):
                return k
            k += 2
            continue
        if c == first and s.startswith(closer, k):
            return k
        k += 1
    return None


def _inline(inner: str) -> str:
    inner = normalize_math(inner).strip()
    return f"${inner}$" if inner else ""        # rỗng thì bỏ: `$$` sinh ra sẽ bị đọc là khối


def _display(inner: str, wrapper: str | None = None) -> str:
    inner = normalize_math(inner).strip()
    if wrapper:
        inner = f"\\begin{{{wrapper}}}{inner}\\end{{{wrapper}}}"
    return f"\\begin{{equation}}{inner}\\end{{equation}}"


def normalize_math(s: str) -> str:
    r"""Đưa mọi công thức về một dạng thống nhất.

    Khối : $$...$$, \[...\], equation*, displaymath      -> \begin{equation}...\end{equation}
           align, alignat, flalign, eqnarray             -> equation chứa aligned
           gather, multline                              -> equation chứa gathered
    Inline: \(...\), \begin{math}...\end{math}, $ x $    -> $x$

    Quét một lượt từ trái sang phải như chính TeX, nên "khối trước, inline sau" đúng một cách
    tự nhiên: `$$x$$` luôn được đọc là khối, `$a$$b$` là hai công thức inline liền nhau, và
    `\\[2pt]` (ngắt dòng trong bảng) không bao giờ bị nhận nhầm là `\[`.

    Kết thúc bằng cùng phép gộp khoảng trắng như clean_latex (xem quyết định số 4), để
    normalize_math(clean_latex(x)) cũng ổn định.

    Bất biến bắt buộc: normalize_math(normalize_math(x)) == normalize_math(x)
    """
    out: list[str] = []
    i = 0
    n = len(s)
    while i < n:
        m = _SPECIAL.search(s, i)
        if m is None:
            out.append(s[i:])
            break
        j = m.start()
        out.append(s[i:j])
        i = j
        c = s[i]

        if c == "$":
            if s.startswith("$$", i):
                end = _find_close(s, i + 2, "$$")
                if end is not None:
                    out.append(_display(s[i + 2:end]))
                    i = end + 2
                    continue
            else:
                end = _find_close(s, i + 1, "$")
                if end is not None and "\n\n" not in s[i + 1:end]:
                    out.append(_inline(s[i + 1:end]))
                    i = end + 1
                    continue
            out.append("$")                     # $ lẻ: giữ nguyên, không đoán
            i += 1
            continue

        # c == "\\"
        nxt = s[i + 1:i + 2]
        if nxt == "[":
            end = _find_close(s, i + 2, "\\]")
            if end is not None:
                out.append(_display(s[i + 2:end]))
                i = end + 2
                continue
        elif nxt == "(":
            end = _find_close(s, i + 2, "\\)")
            if end is not None and "\n\n" not in s[i + 2:end]:
                out.append(_inline(s[i + 2:end]))
                i = end + 2
                continue
        elif nxt == "b":
            env = _BEGIN_ENV.match(s, i)
            if env is not None:
                name = env.group(1)
                closer = f"\\end{{{name}}}"
                if name in _PLAIN_ENVS | _ALIGN_ENVS | _GATHER_ENVS | {"math"}:
                    end = s.find(closer, env.end())
                    if end != -1:
                        inner = s[env.end():end]
                        if name == "math":
                            out.append(_inline(inner))
                        elif name in _PLAIN_ENVS:
                            out.append(_display(inner))
                        else:
                            inner = _ALIGNAT_ARG.sub("", inner, count=1) if name.startswith("alignat") else inner
                            out.append(_display(inner, "aligned" if name in _ALIGN_ENVS else "gathered"))
                        i = end + len(closer)
                        continue
        out.append(s[i:i + 2])                  # \x bất kỳ (kể cả \\ và \$): đi qua nguyên vẹn
        i += 2
    return _squash_whitespace("".join(out))     # công thức rỗng bị bỏ để lại khoảng trắng thừa