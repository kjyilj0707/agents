// 1) 작업영역에 project_map 폴더가 있으면, VS Code를 열 때 관계 그래프(신경망)를 첫 화면으로 띄우고
//    뒤에서 맵·그래프를 다시 분석해 갱신한다. 폴더 마인드맵은 "폴더 구조 맵 열기" 명령으로 연다.
// 2) vscode://kjyil.project-map-reveal/reveal?path=<절대경로> 링크를 받아
//    탐색기 사이드바에서 해당 폴더(또는 파일)를 펼치고 선택한다.
// 3) 관계 그래프에서 노드를 더블클릭하면 파일을 열고, '탐색기에서 보기'는 탐색기에서 펼친다.
const vscode = require('vscode');
const { execFile } = require('child_process');
const fs = require('fs');
const path = require('path');

// Mac: VS Code 의 PATH 에 python 이 없을 수 있고, 시스템 python3 는 3.9 라 스크립트가 안 돈다(3.10+ 필요).
// 가상환경 → Homebrew python3.13 → python3 → python 순으로 시도한다
const venvPython = path.join(require('os').homedir(), '.venvs', 'work', 'bin', 'python');
const pythonCandidates = [...(fs.existsSync(venvPython) ? [venvPython] : []),
  '/opt/homebrew/bin/python3.13', 'python3', 'python'];

function run(dir, script, i = 0) {
  return new Promise((resolve) => {
    if (i >= pythonCandidates.length) return resolve();
    execFile(pythonCandidates[i], [path.join(dir, script)], { cwd: dir }, (err) => {
      if (err && err.code === 'ENOENT') run(dir, script, i + 1).then(resolve);
      else resolve();
    });
  });
}

function mapFolder() {
  return (vscode.workspace.workspaceFolders || []).find((f) => f.name === 'project_map');
}

async function reveal(target) {
  await vscode.commands.executeCommand('workbench.view.explorer');
  await vscode.commands.executeCommand('revealInExplorer', vscode.Uri.file(target));
}

// 시작 화면: 지난번 그래프를 바로 띄우고, 뒤에서 다시 분석해 끝나면 새 내용으로 바꾼다
async function startup() {
  const folder = mapFolder();
  if (!folder) return;
  const dir = folder.uri.fsPath;
  run(dir, 'generate_map.py');
  if (fs.existsSync(path.join(dir, 'PROJECT_GRAPH.html'))) {
    await openGraph(false);
    await run(dir, 'generate_graph.py');
    if (panel) panel.webview.html = fs.readFileSync(path.join(dir, 'PROJECT_GRAPH.html'), 'utf8');
  } else {
    await openGraph(true);
  }
}

async function openMap() {
  const folder = mapFolder();
  if (!folder) return;
  await run(folder.uri.fsPath, 'generate_map.py');
  const map = vscode.Uri.joinPath(folder.uri, 'PROJECT_MAP.md');
  await vscode.commands.executeCommand('vscode.openWith', map, 'markmap-vscode.markmap');
}

// 그래프의 '에이전트 흐름 보기': Agent Flow 확장(simon-p.agent-flow)의 화면을 옆 칸에 연다
async function openAgentFlow() {
  try {
    await vscode.commands.executeCommand('agentVisualizer.openToSide');
  } catch (e) {
    vscode.window.showWarningMessage('Agent Flow 확장(simon-p.agent-flow)을 열지 못했습니다. 설치되어 있는지 확인하세요.');
  }
}

// 그래프의 'Claude 켜기': 그 상위 폴더에서 터미널을 열어 Claude 를 켜고, Agent Flow 를 옆에 띄운다.
// 폴더에 claude --agent 를 부르는 실행 스크립트(`claude --agent` 를 부르는 파일)가 있으면 그것을, 없으면 claude 를 실행한다.
// 작업영역 폴더 자체뿐 아니라 그 안의 하위 폴더(예: 작업공간/프로젝트)도 허용한다.
function findLauncher(dir) {
  try {
    return fs.readdirSync(dir).find((name) => {
      const f = path.join(dir, name);
      const st = fs.statSync(f);
      if (!st.isFile() || st.size > 4096 || !(st.mode & 0o111)) return false;
      return /claude\s+--agent\s/.test(fs.readFileSync(f, 'utf8'));
    });
  } catch (e) { return undefined; }
}
async function openClaude(dir) {
  const inWorkspace = (vscode.workspace.workspaceFolders || []).some((f) =>
    dir === f.uri.fsPath || dir.startsWith(f.uri.fsPath + path.sep));
  if (!inWorkspace) return;
  // 같은 폴더의 Claude 터미널이 이미 살아 있으면 새로 켜지 않고 앞으로만 가져온다(그래프를 여러 번 눌러도 세션이 하나)
  const name = `Claude · ${path.basename(dir)}`;
  let term = vscode.window.terminals.find((t) => t.name === name && t.exitStatus === undefined);
  if (term) {
    term.show(true);
  } else {
    const launcher = findLauncher(dir);
    term = vscode.window.createTerminal({ name, cwd: dir });
    term.show(true);
    term.sendText(launcher ? `./${launcher}` : 'claude');
  }
  if (labDirFor(dir)) await openLabMap(dir); else await openAgentFlow();
}


// 에이전트 연구실(Clawd 실시간, 공용 도구 ~/project_map/agent-lab): 폴더에 labmap 실행 스크립트가 있으면
// 서버를 켜고 VS Code 안 옆 칸에 띄운다. 포트와 이름은 그 폴더의 .lab/map.json(port, project)에서 읽는다.
// 기록은 그 프로젝트의 .lab/live/events.jsonl 에 공용 훅이 남긴다.
// 연구실 폴더를 못 찾았을 때 쓸 기본 폴더(없으면 null). 필요하면 환경 변수 AGENT_LAB_DEFAULT_DIR 로 지정한다.
const LAB_DIR = process.env.AGENT_LAB_DEFAULT_DIR || null;
const labPanels = new Map();  // 프로젝트 폴더 → 화면
function startLabServer(dir) {
  return new Promise((resolve) => execFile('/bin/zsh', [path.join(dir, 'labmap'), 'up'], { cwd: dir }, () => resolve()));
}
function labInfo(dir) {
  try {
    const m = JSON.parse(fs.readFileSync(path.join(dir, '.lab', 'map.json'), 'utf8'));
    const port = Number.isInteger(m.port) && m.port > 1024 && m.port < 65536 ? m.port : 8765;
    return { port, name: typeof m.project === 'string' && m.project ? m.project : path.basename(dir) };
  } catch (e) { return { port: 8765, name: path.basename(dir) }; }
}
async function openLabMap(dir = LAB_DIR) {
  if (!dir || !fs.existsSync(path.join(dir, 'labmap'))) {
    vscode.window.showWarningMessage(`${dir} 에 labmap 이 없습니다.`);
    return false;
  }
  await startLabServer(dir);
  const { port, name } = labInfo(dir);
  const uri = await vscode.env.asExternalUri(vscode.Uri.parse(`http://127.0.0.1:${port}/`));
  let labPanel = labPanels.get(dir);
  if (!labPanel) {
    labPanel = vscode.window.createWebviewPanel('agentLab', `🦀 ${name}`, vscode.ViewColumn.Beside,
      { enableScripts: true, retainContextWhenHidden: true });
    labPanel.onDidDispose(() => { labPanels.delete(dir); });
    labPanels.set(dir, labPanel);
  }
  labPanel.webview.html = `<!doctype html><html><head><meta charset="utf-8">
<meta http-equiv="Content-Security-Policy" content="default-src 'none'; frame-src ${uri.scheme}://${uri.authority}; style-src 'unsafe-inline';">
<style>html,body,iframe{margin:0;padding:0;border:0;width:100%;height:100vh;overflow:hidden;background:transparent}</style></head>
<body><iframe src="${uri.toString(true)}"></iframe></body></html>`;
  labPanel.reveal(vscode.ViewColumn.Beside, true);
  return true;
}
function labDirFor(dir) {
  return dir && fs.existsSync(path.join(dir, 'labmap')) ? dir : null;
}
// 지금 작업영역에서 labmap 이 있는 폴더를 찾는다.
// 열려 있는 파일의 폴더부터 위로 → 작업영역 폴더 → 그 바로 아래 폴더 순서.
function workspaceLabDir() {
  const roots = (vscode.workspace.workspaceFolders || []).map((f) => f.uri.fsPath);
  const ed = vscode.window.activeTextEditor;
  if (ed && ed.document.uri.scheme === 'file') {
    const root = roots.find((r) => ed.document.uri.fsPath.startsWith(r + path.sep));
    if (root) {
      for (let d = path.dirname(ed.document.uri.fsPath); d.length >= root.length; d = path.dirname(d)) {
        if (labDirFor(d)) return d;
        if (d === root) break;
      }
    }
  }
  for (const r of roots) if (labDirFor(r)) return r;
  for (const r of roots) {
    try {
      for (const name of fs.readdirSync(r)) {
        const d = path.join(r, name);
        if (!name.startsWith('.') && fs.statSync(d).isDirectory() && labDirFor(d)) return d;
      }
    } catch (e) { /* 읽을 수 없는 폴더는 건너뛴다 */ }
  }
  return null;
}
// 상태 표시줄 '에이전트 연구실' 버튼: 작업영역에 labmap 이 있으면 통합 연구실 화면, 없으면 Agent Flow
async function openAgentsForWorkspace() {
  const dir = workspaceLabDir();
  if (dir) await openLabMap(dir); else await openAgentFlow();
}

let panel = null;
async function openGraph(refresh) {
  const folder = mapFolder();
  if (!folder) {
    vscode.window.showWarningMessage('작업영역에 project_map 폴더가 없습니다.');
    return;
  }
  const dir = folder.uri.fsPath;
  const file = path.join(dir, 'PROJECT_GRAPH.html');
  if (refresh || !fs.existsSync(file)) {
    await vscode.window.withProgress(
      { location: vscode.ProgressLocation.Window, title: '프로젝트 관계 분석 중…' },
      () => run(dir, 'generate_graph.py'));
  }
  if (!fs.existsSync(file)) {
    vscode.window.showErrorMessage('PROJECT_GRAPH.html 을 만들지 못했습니다. python generate_graph.py 를 직접 실행해 보세요.');
    return;
  }
  if (!panel) {
    panel = vscode.window.createWebviewPanel('projectGraph', '🧠 프로젝트 관계 그래프', vscode.ViewColumn.Active,
      { enableScripts: true, retainContextWhenHidden: true });
    panel.onDidDispose(() => { panel = null; });
    panel.webview.onDidReceiveMessage(async (msg) => {
      if (!msg || !msg.path) return;
      if (msg.type === 'agents') { if (labDirFor(msg.path)) await openLabMap(msg.path); else await openAgentFlow(); return; }
      if (msg.type === 'claude') { await openClaude(msg.path); return; }
      if (msg.type === 'reveal') await reveal(msg.path);
      else await vscode.commands.executeCommand('vscode.open', vscode.Uri.file(msg.path), vscode.ViewColumn.Beside);
    });
  }
  panel.webview.html = fs.readFileSync(file, 'utf8');
  panel.reveal();
}

function activate(context) {
  context.subscriptions.push(
    vscode.window.registerUriHandler({
      async handleUri(uri) {
        if (uri.path === '/labmap') { await openLabMap(workspaceLabDir() || LAB_DIR); return; }
        // vscode://kjyil.project-map-reveal/agentflow → 이 창에서 Agent Flow 열기
        if (uri.path === '/agentflow') { await openAgentFlow(); return; }
        const target = new URLSearchParams(uri.query).get('path');
        if (target) await reveal(target);
      },
    }),
    vscode.commands.registerCommand('projectMap.openGraph', () => openGraph(false)),
    vscode.commands.registerCommand('projectMap.refreshGraph', () => openGraph(true)),
    vscode.commands.registerCommand('projectMap.openMap', openMap),
    vscode.commands.registerCommand('projectMap.openLabMap', () => openLabMap(workspaceLabDir() || LAB_DIR)),
    vscode.commands.registerCommand('projectMap.openAgentFlow', openAgentsForWorkspace),
  );
  // 맨 아래 상태 표시줄 버튼: labmap 이 있는 작업영역이면 에이전트 연구실, 아니면 Agent Flow 를 연다
  const flowButton = vscode.window.createStatusBarItem(vscode.StatusBarAlignment.Left, 100);
  flowButton.text = '$(type-hierarchy) 에이전트 연구실';
  flowButton.tooltip = '에이전트 연구실 열기 (labmap 이 없는 작업영역에서는 Agent Flow)';
  flowButton.command = 'projectMap.openAgentFlow';
  flowButton.show();
  context.subscriptions.push(flowButton);
  startup();
}

function deactivate() {}

module.exports = { activate, deactivate };
