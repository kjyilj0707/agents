# 설치 순서

맥 기준. 처음 한 번만 하면 되고, 새 프로젝트를 붙일 때는 4번부터 한다.

## 0. 준비물

```bash
brew install node python@3.13
npm install -g @anthropic-ai/claude-code      # Claude Code CLI
brew install --cask clawd-on-desk             # 선택: 캐릭터 그림 출처
```

VS Code 확장(선택): Agent Flow(`simon-p.agent-flow`) — 연구실 지도가 없는 폴더에서 대신 열린다.

## 1. 저장소 받기

```bash
git clone https://github.com/kjyilj0707/agents ~/agents
~/agents/scripts/fetch-clawd.sh
```

다른 위치에 두면 `AGENT_LAB_HOME=<위치>/agent-lab`을 셸 설정에 넣는다.

## 2. VS Code 확장 설치

[`vscode-extension/README.md`](../vscode-extension/README.md) 참고. 설치 후 맨 아래 상태 표시줄에 **에이전트 연구실** 버튼이 보이면 성공.

## 3. 프로젝트 관계 그래프 (VS Code 첫 화면)

```bash
mkdir -p ~/project_map && cp ~/agents/project-graph/* ~/project_map/
cp ~/project_map/config.example.json ~/project_map/config.json   # roots 를 내 작업공간 폴더로 고친다
cd ~/project_map && python3 generate_map.py && python3 generate_graph.py
```

- VS Code 작업영역(`*.code-workspace`)에 작업공간 루트들과 `project_map` 폴더를 함께 넣는다. 열면 첫 화면에 그래프가 뜬다.
- 그래프에서 프로젝트를 **한 번 누르면** Claude 터미널과 연구실이 함께 열린다. 오른쪽 아래 **"누르면 바로 열기"** 체크를 끄면 둘러보기만 한다.
- 템플릿을 고치면 `generate_graph.py`를 다시 돌린다. (`python3 -I`로 돌리면 같은 폴더의 `generate_map`을 못 찾으니 `-I` 없이.)

## 4. 프로젝트에 에이전트 팀 + 연구실 붙이기

```bash
P=~/내프로젝트
cp -r ~/agents/templates/project/. $P/
mkdir -p $P/.claude/agents && cp ~/agents/templates/agents/*.md $P/.claude/agents/
chmod +x $P/labmap $P/team
```

1. `$P/.lab/map.json`: `project`, `main_agent`, **겹치지 않는 `port`**, 에이전트, 단계·경로를 프로젝트에 맞게 고친다.
2. `$P/.claude/settings.json`의 `hooks`에 `settings.hooks.example.json`의 항목을 **추가**한다. 기존 훅은 지우지 않는다. JSON은 python으로 읽고 써서 깨지지 않게 한다.
3. `.gitignore`에 `.lab/live/`를 넣는다(기록은 커밋하지 않는다).
4. `./labmap up`으로 서버를 켜고, VS Code에서 그 폴더를 연 창의 **에이전트 연구실** 버튼을 누른다.
5. 훅 설정은 **Claude 세션을 새로 켤 때** 적용된다. `./team`으로 새로 켠다.

## 5. (선택) 관제탑 폴더

여러 작업공간에 걸친 설정(확장, 그래프, 훅)은 한 곳에서 바꾸는 게 안전하다. 예: `~/MANAGE`에 관제탑 에이전트 팀을 두고, `.lab/map.json`의 `outside`로 바깥 폴더를 별칭 붙여 기록한다.

```json
"outside": {"@tools": "~/agents", "@vscode": "~/.vscode/extensions", "@work": "~/WORKSPACE_A"}
```

## 문제 해결

| 증상 | 원인 | 해결 |
|---|---|---|
| Agent Flow·연구실에 아무것도 안 뜸 | 다른 폴더를 연 VS Code 창에서 열었음 | Claude가 일하는 폴더를 연 창에서 연다. Agent Flow 등록은 `ls ~/.claude/agent-flow/` |
| 버튼이 안 보임 | 확장 호스트가 옛 코드, 또는 VS Code가 다른 버전 설치본을 읽음 | `>restart extension host`, `extensions.json`의 버전 확인 후 그 폴더에도 반영 |
| 단축키·명령 팔레트가 안 먹음 | 한글 입력 상태 | 맨 위 가운데 검색칸을 마우스로 누르고 영문으로 `>명령` |
| 연구실이 조용함 | 세션이 훅 설정 전에 켜졌거나 기록이 없음 | 세션 새로 켜기, 또는 화면의 **시연 재생** |
| 포트 사용 중 | 다른 프로젝트·옛 서버가 같은 포트 | 지도에서 `port`를 바꾸거나 `./labmap stop` |
| 터미널에 `source …/activate`가 저절로 들어감 | VS Code 파이썬 확장의 터미널 자동 활성화 | 설정 `"python.terminal.activateEnvironment": false` |
