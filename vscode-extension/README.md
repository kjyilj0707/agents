# VS Code 확장: Project Map Reveal

| 기능 | 설명 |
|---|---|
| 상태 표시줄 **에이전트 연구실** 버튼 | 작업영역에 `labmap`이 있으면 연구실 화면을 옆 칸에, 없으면 Agent Flow를 연다. 단축키·명령 팔레트가 안 먹을 때(한글 입력 상태 등) 쓰는 마우스 길 |
| 그래프 클릭 → Claude + 연구실 | 프로젝트 관계 그래프에서 프로젝트를 누르면 그 폴더의 Claude 세션(`claude --agent …`를 부르는 실행 파일이 있으면 그것)을 터미널에 켜고, 연구실을 옆 칸에 띄운다. 같은 폴더의 터미널이 살아 있으면 새로 만들지 않는다 |
| 연구실 패널 | 그 폴더 `.lab/map.json`의 `port`, `project`를 읽어 `🦀 <project>` 패널을 연다. 프로젝트마다 패널 하나 |
| 첫 화면 그래프 | 작업영역에 `project_map` 폴더가 있으면 VS Code를 열 때 관계 그래프를 띄운다 |
| 주소 링크 | `vscode://kjyil.project-map-reveal/reveal?path=…`(탐색기에서 펼치기), `/agentflow`, `/labmap` |

## 설치

```bash
cd vscode-extension
npx @vscode/vsce package          # project-map-reveal-<버전>.vsix 생성
code --install-extension project-map-reveal-*.vsix
```

또는 폴더를 `~/.vscode/extensions/kjyil.project-map-reveal-<버전>/`에 그대로 복사한다.

## 주의: 설치본이 여러 버전일 때

VS Code는 `~/.vscode/extensions/extensions.json`에 적힌 **한 버전만** 읽는다. 버전 폴더가 여러 개면 원본만 고쳐서는 반영되지 않는다.

```bash
grep -o '"kjyil.project-map-reveal-[0-9.]*"' ~/.vscode/extensions/extensions.json   # 실제로 쓰는 버전
```

고친 뒤에는 각 VS Code 창에서 맨 위 가운데 검색칸에 `>restart extension host` → "개발자: 확장 호스트 다시 시작". **창마다 따로** 해야 한다. 터미널은 끊기지 않는다.

## 설정

- `AGENT_LAB_DEFAULT_DIR` (환경 변수, 선택): 연구실 폴더를 찾지 못했을 때 열 기본 폴더.
