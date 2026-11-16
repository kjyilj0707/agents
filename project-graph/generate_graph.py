"""config.json 의 작업공간 루트(ROOTS)에 있는 각 프로젝트 안에서 파일·데이터·자료 사이의 논리적 관계를
정적 분석해서 신경망 형태의 인터랙티브 그래프(PROJECT_GRAPH.html)로 만든다.

찾는 관계
- 읽기   데이터 → 코드      pd.read_csv(...), gpd.read_file(...), open(p) 등
- 쓰기   코드 → 데이터/그림  df.to_csv(...), plt.savefig(...), open(p, 'w') 등
- import  모듈 → 코드        같은 프로젝트의 .py 를 import
- 참조   문서/웹 → 파일     .md 가 언급한 파일, .html/.js 가 불러오는 파일
- 사본   같은 내용의 파일   (예: 제출자료 폴더에 복사된 파일)

경로는 Path(__file__).parent / 'data' / 'x.csv' 같은 식을 변수까지 따라가며 계산하고,
못 찾으면 파일 이름이 같은 가장 가까운 파일로 연결한다.

실행: python generate_graph.py   → PROJECT_GRAPH.html (브라우저 또는 VS Code 명령
"프로젝트 관계 그래프 열기"로 연다)
"""
import ast
import fnmatch
import hashlib
import json
import os
import re
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path

from generate_map import BASE, MANAGER, ROOTS, SKIP_DIRS

HERE = Path(__file__).resolve().parent
OUTPUT = HERE / "PROJECT_GRAPH.html"
TEMPLATE = HERE / "graph_template.html"

CODE_EXT = {".py", ".ipynb", ".sql", ".r", ".sh", ".ps1"}
WEB_EXT = {".html", ".js", ".ts", ".jsx", ".tsx", ".css"}
DOC_EXT = {".md", ".pdf", ".txt", ".docx", ".hwp", ".pptx"}
IMG_EXT = {".png", ".jpg", ".jpeg", ".gif", ".svg", ".webp", ".mp3", ".wav"}
# shapefile 묶음은 .shp 하나로 대표한다
SHAPE_SIDECAR = {".cpg", ".dbf", ".prj", ".qmd", ".shx", ".sbn", ".sbx", ".xml"}
GROUP_MIN = 8          # 같은 폴더·같은 확장자 데이터 파일이 이만큼 이상이면 묶음 노드 하나로
HASH_LIMIT = 30 * 2**20

READ_WORDS = ("read", "load", "open_dataset", "imread", "graph_from")
WRITE_WORDS = ("to_", "save", "write", "dump", "export", "imsave", "mkdir")
WRITE_VAR = re.compile(r"(^|_)(out|output|save|export|dst|dest|result|cache)", re.I)
FILE_TOKEN = re.compile(
    r"(?<![\w가-힣.\-/])[\w가-힣.\-/]{1,120}\.(?:py|ipynb|csv|json|geojson|gpkg|parquet|png|html|md|xlsx|xls|shp|graphml|jsonl|pdf|txt|js|sql)\b",
    re.I)


def kind_of(p: Path) -> str:
    ext = p.suffix.lower()
    if ext == ".ipynb":
        return "notebook"
    if ext in CODE_EXT:
        return "code"
    if ext in WEB_EXT:
        return "web"
    if ext in DOC_EXT:
        return "doc"
    if ext in IMG_EXT:
        return "media"
    return "data"


# ───────────────────────── 파일 색인 ─────────────────────────
class Project:
    def __init__(self, root_name: str, path: Path):
        self.root_name = root_name
        self.path = path
        self.files: list[Path] = []
        self.dirs: list[Path] = []
        for dp, dns, fns in os.walk(path):
            dns[:] = sorted(d for d in dns if d not in SKIP_DIRS and not d.startswith("."))
            self.dirs.extend(Path(dp) / d for d in dns)
            for fn in sorted(fns):
                p = Path(dp) / fn
                if fn.startswith(".") or p.suffix.lower() in SHAPE_SIDECAR:
                    continue
                self.files.append(p)
        self.by_name: dict[str, list[Path]] = defaultdict(list)
        for f in self.files:
            self.by_name[f.name.lower()].append(f)
        self.dir_by_name: dict[str, list[Path]] = defaultdict(list)
        for d in self.dirs:
            self.dir_by_name[d.name.lower()].append(d)
        self.modules = {f.stem: f for f in self.files if f.suffix == ".py"}
        self.edges: dict[tuple[Path, Path, str], int] = Counter()

    def rel(self, p: Path) -> str:
        return p.relative_to(self.path).as_posix()

    # 문자열(또는 * 패턴) 경로를 실제 파일/폴더로 맞춘다
    def resolve(self, raw: str, src: Path) -> list[Path]:
        key = (raw, src.parent)
        if key not in self._cache:
            self._cache[key] = self._resolve(raw, src)
        return self._cache[key]

    def _resolve(self, raw: str, src: Path) -> list[Path]:
        raw = raw.strip().strip("\"'").replace("\\", "/")
        if not raw or len(raw) > 300 or raw.startswith(("http:", "https:", "data:", "#", "mailto:")):
            return []
        raw = raw.split("?")[0].split("#")[0]
        if "*" in raw:
            return self._glob(raw, src)
        cand = Path(raw) if Path(raw).is_absolute() else (src.parent / raw)
        try:
            cand = Path(os.path.normpath(cand))
        except ValueError:
            return []
        if cand in self._fileset or cand in self._dirset:
            return [cand]
        name = raw.rstrip("/").rsplit("/", 1)[-1].lower()
        if not name:
            return []
        pool = self.by_name.get(name)
        if not pool and "." not in name and len(name) > 3 and "/" in raw.rstrip("/"):
            pool = self.dir_by_name.get(name)  # 'data/h5' 처럼 폴더를 가리키는 문자열
        if not pool:
            return []
        tail = raw.rstrip("/").lower()
        suffix_hits = [p for p in pool if p.as_posix().lower().endswith("/" + tail)]
        pool = suffix_hits or pool
        return [max(pool, key=lambda p: (_common(p, src), -len(p.parts)))]

    def _glob(self, pattern: str, src: Path) -> list[Path]:
        pattern = pattern.lstrip("./")
        pat_low = pattern.lower()
        hits = [f for f in self.files
                if fnmatch.fnmatch(self.rel(f).lower(), "*" + pat_low if not pat_low.startswith("*") else pat_low)
                or fnmatch.fnmatch(f.name.lower(), pat_low.rsplit("/", 1)[-1])
                and ("/" not in pat_low or fnmatch.fnmatch(self.rel(f).lower(), "*" + pat_low.replace("**/", "*")))]
        if not hits or pat_low.rsplit("/", 1)[-1] in ("*", "*.*"):
            return hits[:200]
        # 이름 패턴만 같은 엉뚱한 파일까지 잡히지 않게, 가장 가까운 폴더 쪽만 남긴다
        best = max(_common(h, src) for h in hits)
        return [h for h in hits if _common(h, src) == best][:200]

    def finalize_index(self):
        self._fileset = set(self.files)
        self._dirset = set(self.dirs)
        self._cache: dict = {}


def _common(a: Path, b: Path) -> int:
    n = 0
    for x, y in zip(a.parts, b.parts):
        if x != y:
            break
        n += 1
    return n


# ───────────────────────── Python 분석 ─────────────────────────
class PyAnalyzer:
    """AST 를 돌며 경로 식을 계산하고, 그 경로가 어떤 호출에 쓰였는지로 읽기/쓰기를 정한다."""

    def __init__(self, proj: Project, src: Path):
        self.proj = proj
        self.src = src
        self.env: dict[str, str] = {}          # 변수 → 계산된 경로 문자열
        self.var_refs: dict[str, set] = defaultdict(set)  # 변수 → 그 안의 경로들
        self.found: dict[Path, str] = {}       # 대상 → read/write/use
        self.imports: set[Path] = set()

    # 경로 식 계산 (모르면 None, f-string 은 * 로)
    def ev(self, n) -> str | None:
        if isinstance(n, ast.Constant) and isinstance(n.value, str):
            return n.value
        if isinstance(n, ast.Name):
            if n.id == "__file__":
                return self.src.as_posix()
            return self.env.get(n.id)
        if isinstance(n, ast.JoinedStr):
            parts = []
            for v in n.values:
                if isinstance(v, ast.Constant):
                    parts.append(str(v.value))
                else:
                    inner = self.ev(v.value) if isinstance(v, ast.FormattedValue) else None
                    parts.append(inner if inner and "/" in inner else "*")
            s = "".join(parts)
            return s if s.strip("*") else None
        if isinstance(n, ast.BinOp) and isinstance(n.op, ast.Div):
            a, b = self.ev(n.left), self.ev(n.right)
            if a is not None and b is not None:
                return a.rstrip("/") + "/" + b
            return None
        if isinstance(n, ast.BinOp) and isinstance(n.op, ast.Add):
            a, b = self.ev(n.left), self.ev(n.right)
            if a is not None or b is not None:
                return (a or "*") + (b or "*")
            return None
        if isinstance(n, ast.Attribute):
            base = self.ev(n.value)
            if base is None:
                return None
            if n.attr == "parent":
                return base.rstrip("/").rsplit("/", 1)[0]
            if n.attr in ("stem", "name", "suffix"):
                return None
            return base
        if isinstance(n, ast.Call):
            f = n.func
            fname = f.attr if isinstance(f, ast.Attribute) else (f.id if isinstance(f, ast.Name) else "")
            if fname in ("Path", "PurePath", "abspath", "realpath", "normpath", "expanduser") and n.args:
                return self.ev(n.args[0])
            if fname == "join" and n.args and isinstance(f, ast.Attribute) and not (
                    isinstance(f.value, ast.Constant)):
                parts = [self.ev(a) for a in n.args]
                if all(p is not None for p in parts):
                    return "/".join(p.rstrip("/") for p in parts)
            if fname in ("dirname",) and n.args:
                b = self.ev(n.args[0])
                return b.rstrip("/").rsplit("/", 1)[0] if b else None
            if fname in ("resolve", "absolute", "expanduser") and isinstance(f, ast.Attribute):
                return self.ev(f.value)
            if fname in ("with_suffix", "with_name") and isinstance(f, ast.Attribute) and n.args:
                b, s = self.ev(f.value), self.ev(n.args[0])
                if b and s:
                    head, _, last = b.rpartition("/")
                    if fname == "with_name":
                        return head + "/" + s
                    return head + "/" + last.rsplit(".", 1)[0] + s
            if fname == "cwd":
                return self.src.parent.as_posix()
            return None
        return None

    def targets(self, s: str | None) -> list[Path]:
        if s and (len(s) > 260 or any(c in s for c in "\n\t{}%<>|") or ":" in s[2:]):
            return []
        if s and "*" in s:
            # f"{x}.png" 처럼 이름이 전부 변수면 폴더가 적혀 있을 때만, 확장자는 반드시 있어야 한다
            head, _, last = s.rpartition("/")
            literal = last.replace("*", "")
            if not re.search(r"\.[A-Za-z0-9]{1,8}$", last) or "*.*" in last or (
                    len(literal.rsplit(".", 1)[0]) < 2 and not head.strip("*./")):
                return []
        if not s or ("." not in s.rsplit("/", 1)[-1] and "/" not in s and "*" not in s):
            # 확장자도 경로 구분도 없는 문자열은 파일 경로가 아니다 (단, 폴더 이름일 수는 있다)
            if s and s.lower() in self.proj.dir_by_name and len(s) > 3:
                return self.proj.resolve(s + "/", self.src)
            return []
        if s.endswith("*") and "/" not in s and "." not in s:
            return []
        return [t for t in self.proj.resolve(s, self.src) if t != self.src]

    def mark(self, paths, how):
        rank = {"use": 0, "read": 1, "write": 2}
        for p in paths:
            if p == self.src or (how == "use" and p in self.proj._dirset):
                continue  # 'data' 폴더 변수 같은 단순 경로 정의는 관계로 치지 않는다
            cur = self.found.get(p)
            if cur is None or rank[how] > rank[cur] or (cur == "write" and how == "read"):
                # 같은 파일을 읽기도 쓰기도 하면 쓰기로 (캐시 패턴)
                self.found[p] = how if cur != "write" else "write"

    def refs_in(self, node) -> list[Path]:
        out = []
        whole = self.ev(node)
        if whole is not None:
            out += self.targets(whole)
            if out:
                return out
        for sub in ast.walk(node):
            if isinstance(sub, ast.Name) and sub.id in self.var_refs:
                out += self.var_refs[sub.id]
            elif sub is not node and isinstance(sub, (ast.Constant, ast.JoinedStr, ast.BinOp)):
                v = self.ev(sub)
                if v:
                    out += self.targets(v)
        return out

    def run(self, code: str):
        try:
            tree = ast.parse(code)
        except SyntaxError:
            self.regex_fallback(code)
            return
        self.visit_body(tree)

    def visit_body(self, tree):
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for a in node.names:
                    self._import(a.name)
            elif isinstance(node, ast.ImportFrom) and node.module:
                self._import(node.module)
                for a in node.names:
                    self._import(f"{node.module}.{a.name}")
        # 대입은 위에서 아래 순서로 따라가야 변수 값이 맞는다
        for node in _ordered(tree):
            if isinstance(node, (ast.Assign, ast.AnnAssign)) and node.value is not None:
                tgts = node.targets if isinstance(node, ast.Assign) else [node.target]
                val = self.ev(node.value)
                # 경로 식이거나 경로를 담은 dict/list 일 때만 변수에 경로를 붙인다
                # (df = pd.read_csv(...) 의 df 는 경로가 아니다)
                if val is not None:
                    refs = self.targets(val)
                elif isinstance(node.value, (ast.Dict, ast.List, ast.Tuple, ast.Set)):
                    refs = self.refs_in(node.value)
                else:
                    refs = []
                for t in tgts:
                    if isinstance(t, ast.Name):
                        if val is not None:
                            self.env[t.id] = val
                        if refs:
                            self.var_refs[t.id] = set(refs)
                            self.mark(refs, "write" if WRITE_VAR.search(t.id) else "use")
            elif isinstance(node, ast.Call):
                self._call(node)
            elif isinstance(node, ast.With):
                for item in node.items:
                    if isinstance(item.context_expr, ast.Call):
                        self._call(item.context_expr)

    def _import(self, mod: str):
        last = mod.split(".")[-1]
        first = mod.split(".")[0]
        for name in (last, first):
            f = self.proj.modules.get(name)
            if f and f != self.src:
                self.imports.add(f)
                return

    def _call(self, call: ast.Call):
        f = call.func
        fname = (f.attr if isinstance(f, ast.Attribute) else f.id if isinstance(f, ast.Name) else "").lower()
        if not fname:
            return
        how = None
        if fname in ("open", "fopen"):
            mode = None
            if len(call.args) > 1:
                mode = self.ev(call.args[1])
            for kw in call.keywords:
                if kw.arg == "mode":
                    mode = self.ev(kw.value)
            how = "write" if mode and any(c in mode for c in "wax") else "read"
        elif fname in ("write", "writelines", "dump", "dumps", "print", "makedirs", "exists", "is_file",
                       "is_dir", "iterdir", "listdir", "unlink", "remove", "loads", "join"):
            return
        elif fname in ("read_text", "read_bytes", "glob", "rglob"):
            how = "read"
            if isinstance(f, ast.Attribute):
                self.mark(self.refs_in(f.value), how)
        elif fname in ("write_text", "write_bytes"):
            how = "write"
            if isinstance(f, ast.Attribute):
                self.mark(self.refs_in(f.value), how)
        elif fname.startswith(WRITE_WORDS) or fname in ("savefig", "imwrite"):
            how = "write"
        elif any(w in fname for w in READ_WORDS):
            how = "read"
        if how is None:
            return
        args = list(call.args) + [kw.value for kw in call.keywords if kw.arg in (
            None, "path", "path_or_buf", "fname", "filename", "file", "filepath", "io", "outfile", "fp")]
        if fname in ("glob", "rglob") and call.args and isinstance(f, ast.Attribute):
            base, pat = self.ev(f.value), self.ev(call.args[0])
            if base and pat:
                self.mark(self.targets(base.rstrip("/") + "/" + pat), how)
            return
        for a in args:
            self.mark(self.refs_in(a), how)

    def regex_fallback(self, code: str):
        for m in re.finditer(r"""(['"])([^'"\n]{1,250}?)\1""", code):
            self.mark(self.targets(m.group(2)), "use")


def _ordered(tree):
    """ast.walk 는 너비 우선이라 대입 순서가 섞인다. 소스 위치 순으로 정렬해 돌려준다."""
    nodes = [n for n in ast.walk(tree) if hasattr(n, "lineno")]
    nodes.sort(key=lambda n: (n.lineno, n.col_offset))
    return nodes


def notebook_code(p: Path) -> str:
    try:
        nb = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError, UnicodeDecodeError):
        return ""
    out = []
    for cell in nb.get("cells", []):
        if cell.get("cell_type") != "code":
            continue
        src = cell.get("source", "")
        src = "".join(src) if isinstance(src, list) else src
        lines = []
        for line in src.splitlines():
            s = line.lstrip()
            lines.append("" if s.startswith(("%", "!", "?")) else line)
        cell_code = "\n".join(lines)
        try:
            ast.parse(cell_code)
            out.append(cell_code)
        except SyntaxError:
            out.append("\n".join(f"#{ln}" if ln else "" for ln in lines))
            out.append(_strings_as_code(cell_code))
    return "\n\n".join(out)


def notebook_markdown(p: Path) -> str:
    try:
        nb = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError, UnicodeDecodeError):
        return ""
    return "\n".join("".join(c.get("source", "")) if isinstance(c.get("source"), list) else c.get("source", "")
                     for c in nb.get("cells", []) if c.get("cell_type") == "markdown")


def _strings_as_code(code: str) -> str:
    return "\n".join(f"_s = {m.group(0)}" for m in re.finditer(r"""(['"])[^'"\n]{1,250}?\1""", code))


# ───────────────────────── 문서 / 웹 분석 ─────────────────────────
def _resolve_all(proj: Project, src: Path, cands) -> set[Path]:
    hits = set()
    for c in cands:
        if "/" not in c and "." not in c:
            continue
        for t in proj.resolve(c, src):
            if t != src and t in proj._fileset:
                hits.add(t)
    return hits


def text_refs(proj: Project, src: Path, text: str) -> tuple[set[Path], set[Path]]:
    """(불러오는 파일, 언급만 하는 파일) 을 돌려준다."""
    loads = set(re.findall(r"""<(?:script|img|source|audio|iframe|embed)[^>]*?\bsrc\s*=\s*["']([^"']+)["']""", text, re.I))
    loads |= set(re.findall(r"""<link[^>]*?\bhref\s*=\s*["']([^"']+)["']""", text, re.I))
    loads |= set(re.findall(r"""fetch\(\s*[`'"]([^`'"]+)[`'"]""", text))
    loads |= set(re.findall(r"""import[^'"`;]*?from\s*['"]([^'"]+)['"]""", text))
    loads |= set(re.findall(r"""['"`]([^'"`\n<>{}]{1,200}\.(?:json|geojson|mp3|csv))['"`]""", text))
    cands = set(re.findall(r"\]\(([^)\s]+)\)", text))                    # 마크다운 링크
    cands |= set(re.findall(r"""\bhref\s*=\s*["']([^"']+)["']""", text))
    cands |= {m.group(0) for m in FILE_TOKEN.finditer(text)}
    load_hits = _resolve_all(proj, src, loads)
    return load_hits, _resolve_all(proj, src, cands) - load_hits


def read_text(p: Path, limit=2_000_000) -> str:
    try:
        if p.stat().st_size > limit:
            return ""
        raw = p.read_bytes()
    except OSError:
        return ""
    for enc in ("utf-8", "cp949"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    return ""


# ───────────────────────── 그래프 만들기 ─────────────────────────
def analyze(proj: Project):
    proj.finalize_index()
    for src in proj.files:
        ext = src.suffix.lower()
        if ext in (".py", ".ipynb"):
            code = read_text(src, 50_000_000) if ext == ".py" else notebook_code(src)
            a = PyAnalyzer(proj, src)
            a.run(code)
            for t, how in a.found.items():
                if how == "read":
                    proj.edges[(t, src, "read")] += 1
                elif how == "write":
                    proj.edges[(src, t, "write")] += 1
                else:
                    proj.edges[(t, src, "use")] += 1
            for m in a.imports:
                proj.edges[(m, src, "import")] += 1
            if ext == ".ipynb":
                loads, mentions = text_refs(proj, src, notebook_markdown(src))
                for t in (loads | mentions) - set(a.found) - a.imports:
                    proj.edges[(src, t, "mention")] += 1
        elif ext in (".html", ".js", ".css", ".ts", ".jsx", ".tsx"):
            loads, mentions = text_refs(proj, src, read_text(src))
            for t in loads:
                proj.edges[(t, src, "read")] += 1
            for t in mentions:
                proj.edges[(src, t, "mention")] += 1
        elif ext in (".md", ".sql", ".txt"):
            if ext == ".txt" and src.stat().st_size > 200_000:
                continue
            loads, mentions = text_refs(proj, src, read_text(src))
            for t in loads | mentions:
                proj.edges[(src, t, "mention")] += 1


def file_hash(p: Path) -> str | None:
    try:
        if p.stat().st_size > HASH_LIMIT or p.stat().st_size < 64:
            return None
        return hashlib.md5(p.read_bytes()).hexdigest()
    except OSError:
        return None


def build_graph(projects: list[Project]) -> dict:
    nodes: list[dict] = []
    links: list[dict] = []
    proj_meta = []
    hash_owner: dict[str, list[str]] = defaultdict(list)

    for pi, proj in enumerate(projects):
        pid = f"{proj.root_name}/{proj.path.name}"
        touched = {a for a, _, _ in proj.edges} | {b for _, b, _ in proj.edges}

        # 묶음: 같은 폴더·확장자의 데이터·미디어 파일이 많으면 노드 하나로
        bucket: dict[tuple[Path, str], list[Path]] = defaultdict(list)
        for f in proj.files:
            if kind_of(f) in ("data", "media") or (f.suffix.lower() in (".txt", ".pdf") and False):
                bucket[(f.parent, f.suffix.lower())].append(f)
        node_of: dict[Path, str] = {}
        for (d, ext), fs in bucket.items():
            if len(fs) >= GROUP_MIN:
                gid = f"{pid}::{proj.rel(d) if d != proj.path else '.'}/*{ext}"
                nodes.append(dict(
                    id=gid, project=pid, label=f"{d.name if d != proj.path else proj.path.name}/*{ext}",
                    kind=kind_of(fs[0]), group=True, count=len(fs),
                    path=d.as_posix(), rel=(proj.rel(d) if d != proj.path else ".") + f"/*{ext}",
                    dir=proj.rel(d) if d != proj.path else ".",
                    size=sum(_size(f) for f in fs)))
                for f in fs:
                    node_of[f] = gid
        for d in proj.dirs:   # 폴더를 가리키는 참조 → 그 폴더의 묶음 노드(없으면 폴더 노드)
            if d in touched:
                inside = sorted({node_of[f] for f in proj.files if f.parent == d and f in node_of})
                if len(inside) == 1:
                    node_of[d] = inside[0]
                else:
                    did = f"{pid}::{proj.rel(d)}/"
                    nodes.append(dict(id=did, project=pid, label=d.name + "/", kind="folder", group=True,
                                      count=sum(1 for f in proj.files if d in f.parents),
                                      path=d.as_posix(), rel=proj.rel(d) + "/", dir=proj.rel(d.parent) or ".",
                                      size=0))
                    node_of[d] = did
        for f in proj.files:
            if f in node_of:
                continue
            fid = f"{pid}::{proj.rel(f)}"
            node_of[f] = fid
            h = file_hash(f) if kind_of(f) != "media" else None
            if h:
                hash_owner[h].append(fid)
            nodes.append(dict(id=fid, project=pid, label=f.name, kind=kind_of(f), group=False, count=1,
                              path=f.as_posix(), rel=proj.rel(f),
                              dir=proj.rel(f.parent) if f.parent != proj.path else ".", size=_size(f)))

        merged: dict[tuple[str, str, str], int] = Counter()
        for (a, b, t), n in proj.edges.items():
            if a in node_of and b in node_of and node_of[a] != node_of[b]:
                merged[(node_of[a], node_of[b], t)] += n
        # 같은 쌍에 읽기와 use 가 함께 있으면 더 구체적인 쪽만
        seen_pair = {(a, b) for (a, b, t) in merged if t in ("read", "write", "import")} | \
                    {(b, a) for (a, b, t) in merged if t in ("read", "write", "import")}
        for (a, b, t), n in merged.items():
            if t in ("use", "mention") and (a, b) in seen_pair:
                continue
            links.append(dict(source=a, target=b, type=t, weight=n, project=pid))
        proj_meta.append(dict(id=pid, root=proj.root_name, name=proj.path.name, path=proj.path.as_posix(),
                              files=len(proj.files),
                              # 프로젝트 폴더에 자체 에이전트 팀(.claude/agents)이 있으면 그래프에서 버튼을 띄운다
                              agents=(proj.path / ".claude" / "agents").is_dir()))

    # 사본 관계 (내용이 같은 파일)
    for h, ids in hash_owner.items():
        if len(ids) < 2:
            continue
        ids = sorted(ids, key=lambda i: (len(i), i))
        for other in ids[1:]:
            links.append(dict(source=ids[0], target=other, type="copy", weight=1,
                              project=ids[0].split("::")[0] if ids[0].split("::")[0] == other.split("::")[0] else "*"))
    return dict(nodes=nodes, links=links, projects=proj_meta, manager=MANAGER,
                generated=datetime.now().strftime("%Y-%m-%d %H:%M"))


def _size(p: Path) -> int:
    try:
        return p.stat().st_size
    except OSError:
        return 0


def main() -> None:
    projects = []
    for root in ROOTS:
        base = BASE / root
        if not base.exists():
            continue
        for d in sorted(base.iterdir(), key=lambda p: p.name.lower()):
            if d.is_dir() and d.name not in SKIP_DIRS and not d.name.startswith("."):
                proj = Project(root, d)
                analyze(proj)
                projects.append(proj)
    graph = build_graph(projects)
    html = TEMPLATE.read_text(encoding="utf-8").replace(
        "/*__GRAPH_DATA__*/null", json.dumps(graph, ensure_ascii=False).replace("</", "<\\/"))
    OUTPUT.write_text(html, encoding="utf-8")
    kinds = Counter(l["type"] for l in graph["links"])
    print(f"생성 완료: {OUTPUT}  (노드 {len(graph['nodes'])}, 관계 {len(graph['links'])}: "
          + ", ".join(f"{k} {v}" for k, v in kinds.most_common()) + ")")


if __name__ == "__main__":
    main()
