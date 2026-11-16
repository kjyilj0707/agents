"""에이전트 연구실 공용 훅. Claude Code가 이벤트마다 이 파일을 실행한다.

어느 프로젝트의 일인지는 CLAUDE_PROJECT_DIR(없으면 입력의 cwd)에서 위로 올라가며
`.lab/map.json` 이 있는 폴더를 찾아 정한다. 그런 폴더가 없으면 아무것도 남기지 않는다.

받은 이벤트에서 '누가(에이전트) / 무엇을(도구) / 어느 파일을'만 뽑아
<프로젝트>/.lab/live/events.jsonl 에 한 줄씩 붙인다. 화면(index.html)이 이 파일을 읽어 그린다.

남기지 않는 것: 프롬프트 본문, 도구 결과, 파일 내용, Bash 명령 원문, .env 경로.
(Bash는 명령에 들어 있는 파일 경로와 Claude가 붙인 짧은 설명만 남긴다.)
어떤 오류가 나도 조용히 끝나서(exit 0) Claude Code 작업을 막지 않는다.
"""
import json
import os
import re
import sys
import time
from pathlib import Path

MAX_BYTES = 5 * 2**20
EXT = r"py|csv|jsonl|json|xlsx|txt|md|pkl|html|ipynb|pdf|ts|tsx|js|mjs|cjs|jsx|css|scss|yml|yaml|toml|sh|sql|svg|png"
PATH_RE = re.compile(r"[\w./~가-힣@-]+\.(?:" + EXT + r")\b|[\w.~가-힣@-]*/[\w./가-힣@-]+")
WRITE_TOOLS = {"Write", "Edit", "MultiEdit", "NotebookEdit"}
READ_TOOLS = {"Read", "Grep", "Glob", "LS"}
READ_VERBS = re.compile(r"fetch|search|get|list|read|query|view|download|find")
WRITE_VERBS = re.compile(r"create|update|delete|append|move|comment|upload|send|post|write|edit|set|merge|push|publish")
GIT_REMOTE = re.compile(r"(^|[\s;&|(])(gh\s|git\s+(push|pull|fetch|clone|remote))")


def find_root(start):
    """start에서 위로 올라가며 .lab/map.json 이 있는 폴더를 찾는다(최대 6단계)."""
    try:
        p = Path(start).expanduser().resolve()
    except Exception:
        return None
    for _ in range(7):
        if (p / ".lab" / "map.json").is_file():
            return p
        if p.parent == p:
            break
        p = p.parent
    return None


def secret(path):
    return any(part == ".env" or part.startswith(".env.") for part in Path(path).parts)


# 지도(map.json)의 "outside": {"@별칭": "~/바깥/폴더"} — 프로젝트 밖 폴더도 '@별칭/경로'로 기록한다(관제탑용)
OUTSIDE = []


def rel(p, cwd, root):
    """경로를 프로젝트 기준 상대 경로로. 폴더 밖이면 OUTSIDE 별칭으로, 그것도 아니거나 .env 면 None."""
    try:
        p = os.path.expanduser(p.strip("'\"`"))
        ap = Path(p) if os.path.isabs(p) else Path(cwd) / p
        ap = Path(os.path.normpath(ap))
        tail = "/" if ap.is_dir() else ""
        try:
            s = str(ap.relative_to(root))
        except ValueError:
            for alias, base in OUTSIDE:
                try:
                    s = alias + "/" + str(ap.relative_to(base))
                    break
                except ValueError:
                    continue
            else:
                return None
            s = s.rstrip("/.") if s.endswith("/.") else s
        if s == "." or secret(s):
            return None
        return s + tail
    except Exception:
        return None


def external_of(tool, ti, cmd):
    t = tool.lower()
    blob = json.dumps(ti, ensure_ascii=False).lower()[:4000] if (ti and tool != "Bash") else ""
    if "notion" in t or ("composio" in t and "notion" in blob):
        return "notion"
    if "drive" in t or "drive.google" in blob or "googledrive" in blob:
        return "drive"
    if "github" in t or (tool == "Bash" and GIT_REMOTE.search(cmd or "")):
        return "github"
    if "slack" in t:
        return "slack"
    if "figma" in t:
        return "figma"
    if t in ("webfetch", "websearch") or "web-fetch" in blob:
        return "web"
    return None


def load_map(root):
    try:
        return json.loads((root / ".lab" / "map.json").read_text(encoding="utf-8"))
    except Exception:
        return {}


def main():
    d = json.load(sys.stdin)
    cwd = d.get("cwd") or os.getcwd()
    root = find_root(os.environ.get("CLAUDE_PROJECT_DIR") or cwd) or find_root(cwd)
    if not root:
        return
    log = root / ".lab" / "live" / "events.jsonl"
    for alias, base in (load_map(root).get("outside") or {}).items():
        try:
            OUTSIDE.append((str(alias), Path(os.path.expanduser(str(base))).resolve()))
        except Exception:
            pass
    ev = d.get("hook_event_name", "")
    tool = d.get("tool_name")
    # 도구가 끝난 뒤(PostToolUse)는 위임(Agent)이 돌아온 것만 남긴다. 나머지는 기록을 가볍게 하려고 버린다.
    if ev == "PostToolUse" and tool not in ("Agent", "Task"):
        return

    out = {"ts": round(time.time(), 3), "event": ev, "session": (d.get("session_id") or "")[:8]}
    for k in ("agent_id", "agent_type"):
        if isinstance(d.get(k), str) and d[k]:
            out[k] = d[k][:80]
    # 누가 했나: 하위 에이전트면 agent_type, 아니면 이 프로젝트의 기본(총괄) 에이전트
    if out.get("agent_type"):
        out["agent"] = out["agent_type"].split(":")[-1]
    elif not out.get("agent_id"):
        main_agent = load_map(root).get("main_agent")
        if main_agent:
            out["agent"] = main_agent

    ti = d.get("tool_input") if isinstance(d.get("tool_input"), dict) else {}
    if tool:
        out["tool"] = str(tool)[:80]
        files = set()
        for k in ("file_path", "path", "notebook_path"):
            v = ti.get(k)
            if isinstance(v, str):
                r = rel(v, cwd, root)
                if r:
                    files.add(r)
        cmd = ""
        if tool == "Bash":
            cmd = ti.get("command", "") or ""
            for m in PATH_RE.findall(cmd):
                r = rel(m, cwd, root)
                if r:
                    files.add(r)
            desc = ti.get("description")
            if isinstance(desc, str):
                out["desc"] = desc[:100]
            out["mode"] = "run"
        elif tool in WRITE_TOOLS:
            out["mode"] = "write"
        elif tool in READ_TOOLS:
            out["mode"] = "read"
        if tool in ("Agent", "Task"):
            out["delegate"] = str(ti.get("subagent_type") or "general-purpose").split(":")[-1][:80]
            if isinstance(ti.get("description"), str):
                out["desc"] = ti["description"][:100]
            out["mode"] = "delegate"
        ext = external_of(str(tool), ti, cmd)
        if ext:
            out["external"] = ext
            if "mode" not in out or ext == "github":
                verb = str(tool).lower().split("__")[-1]
                if ext == "github" and tool == "Bash":
                    out["mode"] = "write" if re.search(r"push|pr\s+create|issue\s+create|comment", cmd) else "read"
                elif WRITE_VERBS.search(verb):
                    out["mode"] = "write"
                elif READ_VERBS.search(verb) or ext == "web":
                    out["mode"] = "read"
        if files:
            out["files"] = sorted(files)[:12]
    if ev == "SessionStart" and isinstance(d.get("source"), str):
        out["source"] = d["source"][:20]

    log.parent.mkdir(parents=True, exist_ok=True)
    if log.exists() and log.stat().st_size > MAX_BYTES:
        log.rename(log.with_name(time.strftime("events_%Y%m%d_%H%M%S.jsonl")))
    with open(log, "a", encoding="utf-8") as f:
        f.write(json.dumps(out, ensure_ascii=False) + "\n")


if __name__ == "__main__":
    try:
        import signal  # 무슨 일이 있어도 2초 안에 조용히 끝낸다
        signal.signal(signal.SIGALRM, lambda *a: os._exit(0))
        signal.alarm(2)
        main()
    except BaseException:
        pass
    sys.exit(0)
