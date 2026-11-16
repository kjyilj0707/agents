"""작업공간 루트 폴더들(ROOTS)의 구조를 Markmap용 마크다운(PROJECT_MAP.md)으로 생성한다.

각 노드는 vscode://file 링크라서 마인드맵에서 클릭하면 VS Code에서 바로 열린다.
- 파일 노드: 해당 파일을 연다
- 폴더 노드: 탐색기 사이드바에서 그 폴더를 펼치고 선택한다
  (reveal-extension 폴더의 로컬 확장 project-map-reveal 이 링크를 처리)

실행: python generate_map.py   (VS Code: 터미널 > 작업 실행 > "프로젝트 맵 갱신")
"""
from collections import Counter
from datetime import datetime
from pathlib import Path
from urllib.parse import quote

import json as _json
import os as _os

# 설정: 이 파일 옆 config.json  {"base": "~", "roots": ["WORK_A", "WORK_B", "MANAGE"], "manager": "MANAGE", "title": "내 작업공간"}
_CFG_PATH = Path(__file__).resolve().parent / "config.json"
_CFG = _json.loads(_CFG_PATH.read_text(encoding="utf-8")) if _CFG_PATH.exists() else {}
BASE = Path(_os.path.expanduser(_CFG.get("base", "~"))).resolve()
ROOTS = list(_CFG.get("roots", []))
# 다른 작업공간 루트를 위에서 관리하는 루트 (신경망 그래프에서 맨 위에 둔다). 없으면 None
MANAGER = _CFG.get("manager")
TITLE = _CFG.get("title", "내 작업공간")
OUTPUT = Path(__file__).resolve().parent / "PROJECT_MAP.md"

# 아예 표시하지 않을 폴더
SKIP_DIRS = {
    ".git", "__pycache__", ".ipynb_checkpoints", ".claude", ".vscode", ".idea",
    "node_modules", ".venv", "venv", "env", ".firebase", ".pytest_cache",
}
# 개별 파일로 보여줄 확장자 (작업물). 나머지는 폴더별 개수로 요약
SHOW_EXT = {
    ".py", ".ipynb", ".sql", ".md", ".html", ".js", ".ts", ".jsx", ".tsx",
    ".css", ".r", ".java", ".c", ".cpp", ".sh", ".ps1",
}
# 가지(선) 색 - 흰색 통일 (스타일은 VS Code 작업영역 파일의 markmap.customCSS)
NEON_COLORS = ["#ffffff"]
FILE_ICON = {".py": "🐍", ".ipynb": "📓", ".sql": "🗄️", ".md": "📝", ".html": "🌐"}


def esc(name: str) -> str:
    for ch in "\\`*_[]<>#|":
        name = name.replace(ch, "\\" + ch)
    return name


def link(text: str, target: Path | None) -> str:
    if target is None:
        return text
    return f"[{text}](vscode://file/{quote(target.as_posix(), safe='/:')})"


def folder_link(text: str, folder: Path) -> str:
    return f"[{text}](vscode://kjyil.project-map-reveal/reveal?path={quote(folder.as_posix(), safe='')})"


def walk(folder: Path, depth: int, lines: list[str]) -> Path | None:
    """folder 내용을 lines에 추가하고, 폴더 노드가 가리킬 대표 파일을 반환한다.
    보여줄 내용이 없으면 None."""
    try:
        entries = sorted(folder.iterdir(), key=lambda p: p.name.lower())
    except (PermissionError, OSError):
        return None

    body: list[str] = []
    indent = "  " * depth
    others: Counter[str] = Counter()
    shown: list[Path] = []
    first_other: Path | None = None
    first_sub: Path | None = None

    for p in entries:
        if p.is_dir():
            if p.name in SKIP_DIRS:
                continue
            sub: list[str] = []
            target = walk(p, depth + 1, sub)
            if target:
                body.append(f"{indent}- {folder_link(f'📁 **{esc(p.name)}**', p)}")
                body.extend(sub)
                first_sub = first_sub or target
        elif p.suffix.lower() in SHOW_EXT:
            icon = FILE_ICON.get(p.suffix.lower(), "📄")
            body.append(f"{indent}- {link(f'{icon} {esc(p.name)}', p)}")
            shown.append(p)
        elif not p.name.startswith("."):
            others[p.suffix.lower() or "(확장자 없음)"] += 1
            first_other = first_other or p

    if others:
        summary = ", ".join(f"{ext} {n}" for ext, n in others.most_common())
        text = f"📦 기타 파일 {sum(others.values())}개 ({esc(summary)})"
        body.append(f"{indent}- {link(text, first_other)}")

    if not body:
        return None
    lines.extend(body)
    readme = next((p for p in shown if p.name.lower() == "readme.md"), None)
    return readme or (shown[0] if shown else None) or first_sub or first_other


def main() -> None:
    lines = [
        "---",
        "markmap:",
        "  initialExpandLevel: 3",
        "  colorFreezeLevel: 3",
        "  color:",
        *[f"    - '{c}'" for c in NEON_COLORS],
        "  spacingHorizontal: 110",
        "  spacingVertical: 10",
        "  paddingX: 12",
        "  maxWidth: 320",
        "  duration: 400",
        "---",
        "",
        f"# 🗂️ {TITLE}",
        "",
    ]
    for root in ROOTS:
        path = BASE / root
        lines.append(f"## {folder_link(root, path)}")
        if path.exists():
            for proj in sorted(path.iterdir(), key=lambda p: p.name.lower()):
                if proj.is_dir() and proj.name not in SKIP_DIRS:
                    sub: list[str] = []
                    walk(proj, 0, sub)
                    lines.append(f"### {folder_link(esc(proj.name), proj)}")
                    lines.extend(sub or ["- (비어 있음)"])
        lines.append("")

    lines.append(f"<!-- 생성: {datetime.now():%Y-%m-%d %H:%M} -->")
    OUTPUT.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"생성 완료: {OUTPUT}")


if __name__ == "__main__":
    main()
