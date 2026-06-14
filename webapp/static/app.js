/* claude-preview web — Cursor-style local IDE frontend */

const $ = (sel) => document.querySelector(sel);
const api = (path, opts) => fetch(path, opts).then((r) => r.json());
const postJSON = (path, body) =>
  api(path, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body || {}) });

const state = {
  workspace: "",
  editor: null,
  diffEditor: null,
  monaco: null,
  tabs: new Map(), // path -> { model, name, language }
  active: null,
  agentWS: null,
  termWS: null,
  busy: false,
};

const LANG_BY_EXT = {
  py: "python", js: "javascript", jsx: "javascript", ts: "typescript", tsx: "typescript",
  json: "json", html: "html", css: "css", scss: "scss", md: "markdown", markdown: "markdown",
  yaml: "yaml", yml: "yaml", toml: "toml", sh: "shell", bash: "shell", rs: "rust", go: "go",
  java: "java", c: "c", h: "c", cpp: "cpp", hpp: "cpp", cs: "csharp", php: "php", rb: "ruby",
  sql: "sql", xml: "xml", bat: "bat", txt: "plaintext",
};
const langFor = (name) => LANG_BY_EXT[(name.split(".").pop() || "").toLowerCase()] || "plaintext";
const baseName = (p) => p.replace(/\\/g, "/").split("/").pop();

/* --------------------------------------------------------------- Monaco -- */
require.config({ paths: { vs: "https://cdnjs.cloudflare.com/ajax/libs/monaco-editor/0.52.2/min/vs" } });
require(["vs/editor/editor.main"], () => {
  state.monaco = monaco;
  state.editor = monaco.editor.create($("#editor"), {
    theme: "vs-dark",
    automaticLayout: true,
    fontSize: 13,
    minimap: { enabled: true },
    scrollBeyondLastLine: false,
    value: "",
    language: "plaintext",
  });
  state.editor.addCommand(monaco.KeyMod.CtrlCmd | monaco.KeyCode.KeyS, saveActive);
  boot();
});

/* ----------------------------------------------------------------- boot -- */
async function boot() {
  const s = await api("/api/state");
  setWorkspace(s);
  await loadTree();
  connectAgent();
  connectTerm();
  wireUI();
  await refreshChanges();
}

function setWorkspace(s) {
  state.workspace = s.workspace;
  $("#workspace").textContent = s.workspace;
  document.title = `claude-preview — ${s.name}`;
}

function setStatus(text, cls = "") {
  const el = $("#status");
  el.textContent = text;
  el.className = "status " + cls;
}

/* ------------------------------------------------------------- file tree -- */
async function loadTree() {
  const tree = $("#tree");
  tree.innerHTML = "";
  const data = await api("/api/tree");
  renderChildren(tree, data.children, 0);
}

function renderChildren(container, children, depth) {
  for (const node of children) {
    const row = document.createElement("div");
    row.className = "tree-item";
    row.style.paddingLeft = 8 + depth * 12 + "px";
    row.dataset.path = node.path;
    const twisty = document.createElement("span");
    twisty.className = "tree-twisty";
    const icon = document.createElement("span");
    icon.className = "tree-icon";
    const label = document.createElement("span");
    label.textContent = node.name;
    if (node.type === "dir") {
      twisty.textContent = "▶";
      icon.textContent = "📁";
      let open = false, childBox = null;
      row.onclick = async () => {
        open = !open;
        twisty.textContent = open ? "▼" : "▶";
        icon.textContent = open ? "📂" : "📁";
        if (open) {
          const d = await api("/api/tree?path=" + encodeURIComponent(node.path));
          childBox = document.createElement("div");
          renderChildren(childBox, d.children, depth + 1);
          row.after(childBox);
        } else if (childBox) {
          childBox.remove();
          childBox = null;
        }
      };
    } else {
      twisty.textContent = "";
      icon.textContent = "📄";
      row.onclick = () => openFile(node.path);
    }
    row.append(twisty, icon, label);
    container.appendChild(row);
  }
}

/* --------------------------------------------------------------- editor -- */
async function openFile(path) {
  hideDiff();
  if (state.tabs.has(path)) return activateTab(path);
  const f = await api("/api/file?path=" + encodeURIComponent(path));
  if (f.error) return;
  const model = state.monaco.editor.createModel(f.content, f.language);
  state.tabs.set(path, { model, name: baseName(path), language: f.language });
  renderTabs();
  activateTab(path);
}

function activateTab(path) {
  const t = state.tabs.get(path);
  if (!t) return;
  state.active = path;
  state.editor.setModel(t.model);
  renderTabs();
  highlightTreeActive(path);
}

function closeTab(path) {
  const t = state.tabs.get(path);
  if (t) t.model.dispose();
  state.tabs.delete(path);
  if (state.active === path) {
    const next = [...state.tabs.keys()].pop() || null;
    state.active = next;
    if (next) state.editor.setModel(state.tabs.get(next).model);
    else state.editor.setModel(state.monaco.editor.createModel("", "plaintext"));
  }
  renderTabs();
}

function renderTabs() {
  const bar = $("#tabs");
  bar.innerHTML = "";
  for (const [path, t] of state.tabs) {
    const el = document.createElement("div");
    el.className = "tab" + (path === state.active ? " active" : "");
    const dirty = t.model.getValue() !== t.savedValue;
    el.innerHTML = `<span>${t.name}</span><span class="close">${dirty ? "●" : "✕"}</span>`;
    el.firstChild.onclick = () => activateTab(path);
    el.onclick = (e) => { if (!e.target.classList.contains("close")) activateTab(path); };
    el.querySelector(".close").onclick = (e) => { e.stopPropagation(); closeTab(path); };
    bar.appendChild(el);
  }
}

function highlightTreeActive(path) {
  document.querySelectorAll(".tree-item.active").forEach((e) => e.classList.remove("active"));
  const row = document.querySelector(`.tree-item[data-path="${cssEscape(path)}"]`);
  if (row) row.classList.add("active");
}
const cssEscape = (s) => s.replace(/["\\]/g, "\\$&");

async function saveActive() {
  if (!state.active) return;
  const t = state.tabs.get(state.active);
  await postJSON("/api/save", { path: state.active, content: t.model.getValue() });
  setStatus("saved " + t.name, "ok");
}

async function reloadOpenFile(path) {
  if (!state.tabs.has(path)) return;
  const f = await api("/api/file?path=" + encodeURIComponent(path));
  if (f.error) { closeTab(path); return; }
  state.tabs.get(path).model.setValue(f.content);
}

/* ----------------------------------------------------------- diff review -- */
async function showDiff(path) {
  const d = await api("/api/diff?path=" + encodeURIComponent(path));
  $("#diff-title").textContent = d.rel + "  —  review change";
  $("#diff-overlay").classList.remove("hidden");
  if (!state.diffEditor) {
    state.diffEditor = state.monaco.editor.createDiffEditor($("#diff-editor"), {
      theme: "vs-dark", automaticLayout: true, readOnly: true, renderSideBySide: true,
    });
  }
  state.diffEditor.setModel({
    original: state.monaco.editor.createModel(d.original, d.language),
    modified: state.monaco.editor.createModel(d.current, d.language),
  });
  $("#diff-accept").onclick = async () => { await postJSON("/api/accept", { path }); afterReview(path); };
  $("#diff-reject").onclick = async () => { await postJSON("/api/reject", { path }); await reloadOpenFile(path); afterReview(path); };
}
function hideDiff() { $("#diff-overlay").classList.add("hidden"); }
function afterReview(path) { hideDiff(); reloadOpenFile(path); refreshChanges(); loadTree(); }

async function refreshChanges() {
  const { items } = await api("/api/changes");
  renderReview(items || []);
}

function renderReview(items) {
  const review = $("#review");
  const list = $("#review-list");
  $("#review-count").textContent = `${items.length} change${items.length === 1 ? "" : "s"}`;
  list.innerHTML = "";
  if (!items.length) { review.classList.add("hidden"); return; }
  review.classList.remove("hidden");
  for (const it of items) {
    const row = document.createElement("div");
    row.className = "review-item";
    row.innerHTML = `
      <span class="badge ${it.status}">${it.status}</span>
      <span class="name" title="${it.rel}">${it.rel}</span>
      <span class="acts">
        <button class="btn sm danger">✕</button>
        <button class="btn sm primary">✓</button>
      </span>`;
    row.querySelector(".name").onclick = () => { openFile(it.path).then(() => showDiff(it.path)); };
    const [rej, acc] = row.querySelectorAll("button");
    rej.onclick = async () => { await postJSON("/api/reject", { path: it.path }); await reloadOpenFile(it.path); refreshChanges(); loadTree(); };
    acc.onclick = async () => { await postJSON("/api/accept", { path: it.path }); refreshChanges(); };
    list.appendChild(row);
  }
}

/* ----------------------------------------------------------------- chat -- */
function connectAgent() {
  const ws = new WebSocket(`ws://${location.host}/ws/agent`);
  state.agentWS = ws;
  ws.onopen = () => setStatus("ready", "ok");
  ws.onclose = () => setStatus("disconnected", "err");
  ws.onmessage = (ev) => handleAgentMsg(JSON.parse(ev.data));
}

let currentAssistantBubble = null;
let assistantBuffer = "";

function handleAgentMsg(m) {
  switch (m.type) {
    case "turn_start":
      state.busy = true; setStatus("Claude is working…", "busy");
      $("#stop-btn").classList.remove("hidden");
      currentAssistantBubble = null; assistantBuffer = "";
      break;
    case "assistant":
      if (!currentAssistantBubble) currentAssistantBubble = addMessage("claude", "");
      assistantBuffer += m.text;
      currentAssistantBubble.innerHTML = marked.parse(assistantBuffer);
      scrollMessages();
      break;
    case "thinking":
      addActivity("…thinking", "read");
      break;
    case "tool":
      if (m.tool === "Bash") addActivity("▶ " + firstLine(m.summary), "bash");
      else addActivity(`${iconFor(m.tool)} ${m.tool} ${m.summary || ""}`.trim(), "read");
      break;
    case "edit":
      addActivity(`${m.op === "write" ? "📝 write" : "✏️ edit"} ${m.rel}`, "edit");
      reloadOpenFile(m.path);
      break;
    case "terminal":
      termPrint("$ " + m.command + "\n", "cmd");
      termPrint(m.output + "\n");
      break;
    case "changes":
      renderReview(m.items || []);
      loadTree();
      break;
    case "result":
      if (m.cost) setStatus(`done — $${m.cost.toFixed(4)} this session`, "ok");
      break;
    case "turn_end":
      state.busy = false; $("#stop-btn").classList.add("hidden");
      if (!$("#status").classList.contains("ok")) setStatus("ready", "ok");
      currentAssistantBubble = null;
      break;
    case "info":
      addActivity(m.message, "read"); break;
    case "error":
      addActivity("✗ " + m.message, "edit"); setStatus("error", "err");
      state.busy = false; $("#stop-btn").classList.add("hidden");
      break;
  }
}

const iconFor = (t) => ({ Read: "👁", Glob: "🔍", Grep: "🔍" }[t] || "•");
const firstLine = (s) => (s || "").split("\n")[0].slice(0, 100);

function addMessage(who, text) {
  const wrap = document.createElement("div");
  wrap.className = "msg " + who;
  wrap.innerHTML = `<span class="who">${who === "user" ? "You" : "Claude"}</span><div class="bubble"></div>`;
  const bubble = wrap.querySelector(".bubble");
  bubble.innerHTML = who === "user" ? escapeHTML(text) : marked.parse(text || "");
  $("#messages").appendChild(wrap);
  scrollMessages();
  return bubble;
}
function addActivity(text, cls) {
  const el = document.createElement("div");
  el.className = "activity";
  el.innerHTML = `<span class="${cls}">${escapeHTML(text)}</span>`;
  $("#messages").appendChild(el);
  scrollMessages();
}
const scrollMessages = () => { const m = $("#messages"); m.scrollTop = m.scrollHeight; };
const escapeHTML = (s) => s.replace(/[&<>]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;" }[c]));

function sendChat() {
  const input = $("#composer-input");
  const text = input.value.trim();
  if (!text || state.busy) return;
  addMessage("user", text);
  state.agentWS.send(JSON.stringify({ type: "chat", text }));
  input.value = "";
}

/* ------------------------------------------------------------- terminal -- */
function connectTerm() {
  const ws = new WebSocket(`ws://${location.host}/ws/term`);
  state.termWS = ws;
  ws.onmessage = (ev) => {
    const m = JSON.parse(ev.data);
    if (m.type === "started") termPrint("$ " + m.cmd + "\n", "cmd");
    else if (m.type === "out") termPrint(m.data);
    else if (m.type === "exit") termPrint(`[exit ${m.code}]\n`, "ec");
  };
}
function termPrint(text, cls) {
  const out = $("#term-output");
  const span = document.createElement("span");
  if (cls) span.className = cls;
  span.textContent = text;
  out.appendChild(span);
  out.scrollTop = out.scrollHeight;
}

/* --------------------------------------------------------------- UI wire -- */
function wireUI() {
  $("#send-btn").onclick = sendChat;
  $("#composer-input").addEventListener("keydown", (e) => {
    if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); sendChat(); }
  });
  $("#stop-btn").onclick = () => state.agentWS.send(JSON.stringify({ type: "interrupt" }));
  $("#reload-tree").onclick = loadTree;
  $("#open-folder").onclick = async () => {
    setStatus("opening folder…", "busy");
    const r = await postJSON("/api/pick-folder", {});
    if (r.cancelled) { setStatus("ready", "ok"); return; }
    setWorkspace(r);
    for (const p of [...state.tabs.keys()]) closeTab(p);
    await loadTree(); await refreshChanges();
    reconnectAgent();
    setStatus("ready", "ok");
  };
  $("#diff-close").onclick = hideDiff;
  $("#accept-all").onclick = async () => { await postJSON("/api/accept-all", {}); refreshChanges(); };
  $("#reject-all").onclick = async () => { await postJSON("/api/reject-all", {}); refreshChanges(); loadTree(); for (const p of state.tabs.keys()) reloadOpenFile(p); };
  $("#term-clear").onclick = () => { $("#term-output").innerHTML = ""; };
  $("#term-input").addEventListener("keydown", (e) => {
    if (e.key === "Enter") {
      const cmd = e.target.value.trim();
      if (cmd) state.termWS.send(JSON.stringify({ cmd }));
      e.target.value = "";
    }
  });
  setupSplitters();
}

function reconnectAgent() {
  try { state.agentWS.close(); } catch {}
  connectAgent();
}

/* simple drag-to-resize for the three side panels + terminal */
function setupSplitters() {
  document.querySelectorAll(".splitter").forEach((sp) => {
    sp.addEventListener("mousedown", (e) => {
      e.preventDefault();
      const target = sp.dataset.target;
      const horizontal = sp.classList.contains("horizontal");
      const el = $("#" + (target === "explorer" ? "explorer" : target === "chat" ? "chat" : "terminal"));
      const startPos = horizontal ? e.clientY : e.clientX;
      const startSize = horizontal ? el.offsetHeight : el.offsetWidth;
      const move = (me) => {
        const delta = (horizontal ? me.clientY : me.clientX) - startPos;
        let size = target === "chat" ? startSize - delta : (horizontal ? startSize - delta : startSize + delta);
        size = Math.max(60, Math.min(size, 900));
        if (horizontal) el.style.height = size + "px";
        else el.style.width = size + "px";
      };
      const up = () => { document.removeEventListener("mousemove", move); document.removeEventListener("mouseup", up); };
      document.addEventListener("mousemove", move);
      document.addEventListener("mouseup", up);
    });
  });
}
