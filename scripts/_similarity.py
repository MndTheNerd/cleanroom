"""Tokenizer, k-gram winnowing and auxiliary signal extraction (identifiers, strings, comments)."""
from __future__ import annotations

import ast
import builtins
import hashlib
import re
from dataclasses import dataclass, field
from pathlib import Path

HASH_COMMENT = {".py", ".sh", ".bash", ".rb", ".yaml", ".yml", ".toml", ".ini", ".cfg", ".env", ".r"}
SLASH_COMMENT = {".js", ".mjs", ".cjs", ".ts", ".tsx", ".jsx", ".java", ".c", ".h", ".cc", ".cpp", ".hpp",
                 ".cs", ".go", ".rs", ".php", ".swift", ".kt", ".kts", ".scala", ".css"}

KEYWORDS = set("""
and as assert async await break case catch class const continue def default del delete do elif else enum
except export extends false final finally for from func function go if implements import in instanceof
interface is lambda let match mod module new nil none not null of or package pass private protected pub
public raise return self static struct super switch this throw throws trait true try type typeof use var
void while with yield fn impl mut loop where crate extern unsafe goto defer chan map range select fallthrough
int float str bool list dict set tuple bytes string number boolean object any char long short double byte
print len isinstance range open None True False undefined require module exports console
""".split())

# Language builtins (Python's plus common JS/TS globals) are never evidence of copying.
BUILTINS = set(dir(builtins)) | set("""
Array Object String Number Boolean Promise Map Set Error TypeError RangeError SyntaxError JSON Math Date RegExp Symbol
parseInt parseFloat isNaN setTimeout clearTimeout process Buffer
""".split())

# Generic words that do not indicate copying when they appear as identifiers, paths or keys.
GENERIC = KEYWORDS | BUILTINS | set("""
data value values item items key keys name names index result results error errors args kwargs options opts
config settings path paths file files line lines text token tokens input output start end size count total
node nodes list init main test tests util utils helper helpers lib src core app index common base default
version description author license readme setup package build dist docs example examples type types temp tmp
""".split())

_TOKEN_RE = re.compile(r"""
  (?P<ws>\s+)
| (?P<tstr>(?:[rRbBuUfF]{0,2})(?:\"\"\"[\s\S]*?\"\"\"|'''[\s\S]*?'''))
| (?P<str>(?:[rRbBuUfF]{0,2})(?:"(?:\\.|[^"\\\n])*"|'(?:\\.|[^'\\\n])*'|`(?:\\.|[^`\\])*`))
| (?P<num>\b\d[\d_]*(?:\.\d+)?(?:[eE][+-]?\d+)?\b|\b0[xX][0-9a-fA-F]+\b)
| (?P<id>[A-Za-z_$][A-Za-z0-9_$]*)
| (?P<op>==|!=|<=|>=|=>|->|&&|\|\||\+\+|--|\*\*|//|<<|>>|::|[^\sA-Za-z0-9_])
""", re.VERBOSE)


@dataclass
class Lexed:
    tokens: list[tuple[str, str, int]] = field(default_factory=list)  # (kind, text, line)
    comments: list[tuple[str, int]] = field(default_factory=list)
    strings: list[tuple[str, int]] = field(default_factory=list)


def _strip_comments(src: str, ext: str):
    """Split source into code (comments blanked, newlines kept) and a comment list."""
    comments: list[tuple[str, int]] = []
    out = []
    i, n, line = 0, len(src), 1
    hash_c = ext in HASH_COMMENT
    slash_c = ext in SLASH_COMMENT
    while i < n:
        c = src[i]
        # strings: copy through untouched so comment markers inside are ignored
        if c in "\"'`":
            q3 = src[i:i + 3]
            if q3 in ('"""', "'''"):
                j = src.find(q3, i + 3)
                j = n if j < 0 else j + 3
            else:
                j = i + 1
                while j < n and src[j] != c and (src[j] != "\n" or c == "`"):
                    j += 2 if src[j] == "\\" else 1
                j = min(j + 1, n)
            seg = src[i:j]
            out.append(seg)
            line += seg.count("\n")
            i = j
            continue
        if hash_c and c == "#" or slash_c and src.startswith("//", i):
            j = src.find("\n", i)
            j = n if j < 0 else j
            comments.append((src[i:j].lstrip("#/ ").strip(), line))
            i = j
            continue
        if slash_c and src.startswith("/*", i):
            j = src.find("*/", i + 2)
            j = n if j < 0 else j + 2
            body = src[i + 2:j - 2]
            text = " ".join(l.strip().lstrip("*").strip() for l in body.splitlines())
            comments.append((text.strip(), line))
            nl = src.count("\n", i, j)
            out.append("\n" * nl)
            line += nl
            i = j
            continue
        if c == "\n":
            line += 1
        out.append(c)
        i += 1
    return "".join(out), comments


def lex(src: str, ext: str) -> Lexed:
    ext = ext.lower()
    code, comments = _strip_comments(src, ext)
    lx = Lexed(comments=[c for c in comments if c[0]])
    line = 1
    for m in _TOKEN_RE.finditer(code):
        kind, text = m.lastgroup, m.group()
        if kind == "ws":
            line += text.count("\n")
            continue
        if kind == "tstr":
            body = re.sub(r"^[rRbBuUfF]{0,2}", "", text)[3:-3]
            # A bare triple-quoted string at statement level is a docstring: treat it as a comment.
            lx.comments.append((" ".join(body.split()), line))
            lx.tokens.append(("str", text, line))
            line += text.count("\n")
            continue
        if kind == "str":
            body = re.sub(r"^[rRbBuUfF]{0,2}", "", text)[1:-1]
            lx.strings.append((body, line))
        lx.tokens.append((kind, text, line))
        line += text.count("\n")
    return lx


def normalize(tokens) -> list[tuple[str, int]]:
    """Rename identifiers/literals to placeholders; keep keywords and operators."""
    out = []
    for kind, text, line in tokens:
        if kind == "id":
            out.append((text if text in KEYWORDS else "I", line))
        elif kind == "num":
            out.append(("N", line))
        elif kind in ("str", "tstr"):
            out.append(("S", line))
        else:
            out.append((text, line))
    return out


def _h(s: str) -> int:
    return int.from_bytes(hashlib.blake2b(s.encode(), digest_size=8).digest(), "big")


def winnow(norm: list[tuple[str, int]], k: int = 5, w: int = 4) -> list[tuple[int, int]]:
    """Return selected fingerprints as (hash, line) using the robust winnowing algorithm."""
    if len(norm) < k:
        if not norm:
            return []
        return [(_h("\x00".join(t for t, _ in norm)), norm[0][1])]
    grams = [(_h("\x00".join(t for t, _ in norm[i:i + k])), norm[i][1]) for i in range(len(norm) - k + 1)]
    if len(grams) <= w:
        return [min(grams, key=lambda g: g[0])]
    picked, last = [], -1
    for i in range(len(grams) - w + 1):
        win = grams[i:i + w]
        # rightmost minimum
        mi = min(range(w), key=lambda j: (win[j][0], -j))
        pos = i + mi
        if pos != last:
            picked.append(grams[pos])
            last = pos
    return picked


@dataclass
class FileFacts:
    path: str
    ext: str
    fingerprints: list[tuple[int, int]]
    identifiers: set[str]
    strings: list[tuple[str, int]]
    comments: list[tuple[str, int]]
    functions: list[tuple[str, int, int]]  # (name, start, end)
    n_lines: int


def functions_of(src: str, ext: str) -> list[tuple[str, int, int]]:
    if ext == ".py":
        try:
            tree = ast.parse(src)
        except SyntaxError:
            return []
        out = []
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                out.append((node.name, node.lineno, getattr(node, "end_lineno", node.lineno)))
        return out
    # brace languages: header line followed by a balanced block
    out = []
    lines = src.splitlines()
    hdr = re.compile(r"(?:function\s+([A-Za-z_$][\w$]*)|([A-Za-z_$][\w$]*)\s*(?:=\s*(?:async\s*)?\([^)]*\)\s*=>|\([^;{}]*\)\s*(?:->\s*[\w<>\[\], ]+)?\s*\{))")
    for i, l in enumerate(lines):
        m = hdr.search(l)
        if not m or "{" not in "".join(lines[i:i + 2]):
            continue
        name = m.group(1) or m.group(2)
        if name in KEYWORDS:
            continue
        depth, started = 0, False
        for j in range(i, len(lines)):
            depth += lines[j].count("{") - lines[j].count("}")
            started = started or "{" in lines[j]
            if started and depth <= 0:
                out.append((name, i + 1, j + 1))
                break
    return out


def facts(path: Path, root: Path, k: int = 5, w: int = 4) -> FileFacts:
    src = Path(path).read_text(encoding="utf-8", errors="replace")
    ext = Path(path).suffix.lower()
    lx = lex(src, ext)
    fps = winnow(normalize(lx.tokens), k, w)
    idents = {t for kind, t, _ in lx.tokens if kind == "id" and t not in KEYWORDS and t not in BUILTINS}
    return FileFacts(
        path=Path(path).resolve().relative_to(Path(root).resolve()).as_posix(),
        ext=ext, fingerprints=fps, identifiers=idents, strings=lx.strings,
        comments=lx.comments, functions=functions_of(src, ext), n_lines=src.count("\n") + 1,
    )


def distinctive(ident: str) -> bool:
    """Identifiers likely to be project-specific rather than generic vocabulary."""
    low = ident.lower()
    if len(ident) < 4 or low in GENERIC:
        return False
    return True


def code_shaped(word: str) -> bool:
    """True if a word looks like a code identifier rather than an English word."""
    return bool(re.search(r"_|\d|[a-z][A-Z]|^[A-Z]{2,}[a-z]", word))


def norm_text(s: str) -> str:
    return " ".join(re.findall(r"[a-z0-9]+", s.lower()))


def word_shingles(text: str, n: int = 8) -> set[str]:
    words = norm_text(text).split()
    return {" ".join(words[i:i + n]) for i in range(len(words) - n + 1)}


def name_variants(name: str) -> set[str]:
    """Spelling variants of a project name: foo-bar, foo_bar, FooBar, foobar, 'foo bar'."""
    parts = [p for p in re.split(r"[\s_\-.]+|(?<=[a-z])(?=[A-Z])", name) if p]
    if not parts:
        return set()
    low = [p.lower() for p in parts]
    return {"-".join(low), "_".join(low), "".join(low), " ".join(low), "".join(p.capitalize() for p in low), name}


def similar_name(a: str, b: str) -> float:
    """Similarity of two project names in [0,1] (normalized Levenshtein on squashed lowercase)."""
    x = re.sub(r"[^a-z0-9]", "", a.lower())
    y = re.sub(r"[^a-z0-9]", "", b.lower())
    if not x or not y:
        return 0.0
    if x in y or y in x:
        return 1.0
    prev = list(range(len(y) + 1))
    for i, cx in enumerate(x, 1):
        cur = [i]
        for j, cy in enumerate(y, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (cx != cy)))
        prev = cur
    return 1 - prev[-1] / max(len(x), len(y))
