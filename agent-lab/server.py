"""에이전트 연구실 공용 서버. 이 컴퓨터(127.0.0.1)에서만 열린다.

  python server.py <프로젝트루트> <포트>

  GET /                 index.html (공용 화면)
  GET /clawd/<이름>.svg  Clawd 캐릭터 그림 (공용)
  GET /map.json         <프로젝트>/.lab/map.json
  GET /events?offset=N  <프로젝트>/.lab/live/events.jsonl 의 N바이트 뒤 새 줄들. offset=-1 이면 마지막 줄들.
  GET /health           {"app":"agent-lab", ...}

위 주소 말고는 아무것도 내보내지 않는다. 주소를 파일 경로로 바꾸지 않으므로
/../../.env 같은 경로 탈출이 통하지 않는다. 다른 사이트가 이 서버를 몰래 부르지 못하게
Host 머리글이 127.0.0.1·localhost 가 아니면 거절한다.
"""
import json
import re
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

HERE = Path(__file__).resolve().parent
CLAWD = HERE / "clawd"
SVG_NAME = re.compile(r"^/clawd/(clawd-[a-z-]+\.svg)$")
INITIAL_LINES = 2000
ROOT = None  # 실행할 때 정한다


def parse(lines):
    out = []
    for ln in lines:
        try:
            out.append(json.loads(ln))
        except Exception:
            pass
    return out


class H(BaseHTTPRequestHandler):
    server_version = "agent-lab"
    sys_version = ""

    def log_message(self, *a):
        pass

    def send(self, code, body, ctype):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        host = (self.headers.get("Host") or "").rsplit(":", 1)[0]
        if host not in ("127.0.0.1", "localhost"):
            return self.send(403, b"forbidden", "text/plain")
        u = urlparse(self.path)
        p = u.path
        lab = ROOT / ".lab"
        if p in ("/", "/index.html"):
            return self.send(200, (HERE / "index.html").read_bytes(), "text/html; charset=utf-8")
        if p == "/map.json":
            f = lab / "map.json"
            if f.is_file():
                return self.send(200, f.read_bytes(), "application/json; charset=utf-8")
            return self.send(404, b"no map", "text/plain")
        m = SVG_NAME.match(p)
        if m:
            f = CLAWD / m.group(1)
            if f.is_file() and f.resolve().parent == CLAWD:
                return self.send(200, f.read_bytes(), "image/svg+xml")
        if p == "/health":
            try:
                name = json.loads((lab / "map.json").read_text(encoding="utf-8")).get("project", "")
            except Exception:
                name = ""
            body = json.dumps({"app": "agent-lab", "project": name, "root": ROOT.name}, ensure_ascii=False)
            return self.send(200, body.encode("utf-8"), "application/json; charset=utf-8")
        if p == "/events":
            return self.events(u)
        self.send(404, b"not found", "text/plain")

    def events(self, u):
        log = ROOT / ".lab" / "live" / "events.jsonl"
        try:
            off = int(parse_qs(u.query).get("offset", ["-1"])[0])
        except ValueError:
            off = -1
        size = log.stat().st_size if log.exists() else 0
        events, reset = [], False
        if size:
            with open(log, "rb") as f:
                if off < 0 or off > size:  # 처음이거나 파일이 새로 시작됨(회전)
                    data = f.read().decode("utf-8", "replace").splitlines()[-INITIAL_LINES:]
                    events, reset = parse(data), True
                else:
                    f.seek(off)
                    chunk = f.read()
                    cut = chunk.rfind(b"\n") + 1  # 덜 쓴 마지막 줄은 다음에 읽는다
                    size = off + cut
                    events = parse(chunk[:cut].decode("utf-8", "replace").splitlines())
        else:
            reset = off != 0
        body = json.dumps({"offset": size, "reset": reset, "events": events}, ensure_ascii=False)
        return self.send(200, body.encode("utf-8"), "application/json; charset=utf-8")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("사용법: python server.py <프로젝트루트> [포트]")
        sys.exit(1)
    ROOT = Path(sys.argv[1]).expanduser().resolve()
    if not (ROOT / ".lab" / "map.json").is_file():
        print(f"{ROOT}/.lab/map.json 이 없다.")
        sys.exit(1)
    port = int(sys.argv[2]) if len(sys.argv) > 2 else 8765
    ThreadingHTTPServer(("127.0.0.1", port), H).serve_forever()
