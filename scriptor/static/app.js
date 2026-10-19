const $ = (selector) => document.querySelector(selector);
const state = { books: [], book: null, number: null, tab: "writing", busy: false, baseline: "", runs: [], history: [] };
const escape = (value) => String(value ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const path = (suffix = "") => `/api/books/${encodeURIComponent(state.book.id)}${suffix}`;
const dirty = () => $("#content").value !== state.baseline;
const current = () => state.book?.chapters.find((c) => c.number === state.number);
const plan = () => state.book?.plans.find((p) => p.number === state.number);
const canEdit = (number) => !!state.book?.plans.some((p) => p.number === number && p.stage === state.book.stage) && (number === state.book.total_chapters + 1 || number === state.book.total_chapters);
const editable = () => canEdit(state.number);
const draftKey = () => `scriptor:draft:${state.book.id}:${state.number}`;
let noticeTimer;
let confirmResolve;

function notify(message, error = false) {
  clearTimeout(noticeTimer);
  const el = $("#notice"); el.textContent = message; el.className = error ? "error" : ""; el.hidden = false;
  noticeTimer = setTimeout(() => { el.hidden = true; }, error ? 15000 : 5500);
}

async function api(url, options = {}) {
  const response = await fetch(url, { headers: { "Content-Type": "application/json" }, ...options });
  if (!response.ok) {
    const data = await response.json().catch(() => ({}));
    const detail = Array.isArray(data.detail) ? data.detail.map((x) => `${x.loc?.slice(1).join(".") || "输入"}：${x.msg}`).join("；") : data.detail;
    throw new Error(detail || `请求失败（${response.status}）`);
  }
  return response.json();
}
const post = (url, payload = {}) => api(url, { method: "POST", body: JSON.stringify(payload) });

function ask(title, message) {
  $("#confirm-title").textContent = title; $("#confirm-message").textContent = message;
  $("#confirm-dialog").showModal();
  return new Promise((resolve) => { confirmResolve = resolve; });
}
function answer(value) { $("#confirm-dialog").close(); confirmResolve?.(value); confirmResolve = null; }
$("#confirm-yes").onclick = () => answer(true);
$("#confirm-no").onclick = () => answer(false);
$("#confirm-dialog").addEventListener("cancel", (event) => { event.preventDefault(); answer(false); });

async function leaveDraft() {
  return !dirty() || await ask("离开当前正文？", "当前修改尚未审核保存。切换后可从本浏览器的草稿恢复；其他设备无法读取这份草稿。");
}
function persistDraft() {
  if (!state.book || !state.number || !editable()) return;
  try {
    if (dirty()) localStorage.setItem(draftKey(), JSON.stringify({ content: $("#content").value, baseline: state.baseline }));
    else localStorage.removeItem(draftKey());
  } catch { $("#save-state").textContent = "浏览器草稿存储不可用，请及时保存"; }
}
function blocked(selector, value) { $(selector).dataset.blocked = String(value); }
function controls() {
  const book = state.book;
  blocked("#plan-open", !book?.bible);
  blocked("#bible-generate", !book || book.total_chapters > 0);
  blocked("#generate", !editable());
  blocked("#save", !editable() || !$("#content").value.trim() || (!!current() && !dirty()));
  blocked("#history", !current());
  blocked("#stage-submit", !book?.progress.achieved);
  blocked("#draft-restore", !editable());
  document.querySelectorAll("button").forEach((button) => { button.disabled = state.busy || button.dataset.blocked === "true"; });
  $("#content").disabled = state.busy || !editable();
  $("#export").setAttribute("aria-disabled", String(state.busy));
}
async function action(label, task) {
  if (state.busy) return;
  state.busy = true; $("#activity").textContent = label; $("#activity").className = "busy"; controls();
  try { await task(); }
  catch (error) { notify(error.message, true); }
  finally { state.busy = false; $("#activity").textContent = "准备就绪"; $("#activity").className = ""; controls(); }
}

async function refreshShelf() {
  state.books = await api("/api/books"); renderShelf();
}
function renderShelf() {
  $("#book-list").innerHTML = state.books.length ? state.books.map((b) => `<button class="book-item ${b.id === state.book?.id ? "active" : ""}" data-book="${escape(b.id)}"><strong>${escape(b.spec.title)}</strong><small>${escape(b.spec.genre)} · ${b.total_chapters} 章 · ${Number(b.total_words).toLocaleString()} 字符</small></button>`).join("") : '<div class="empty">书架还空着。<br>从一个想法开始吧。</div>';
}
async function loadBook(id, number = null) {
  state.book = await api(`/api/books/${encodeURIComponent(id)}`);
  const available = [...new Set([...state.book.plans, ...state.book.chapters].map((c) => c.number))].sort((a, b) => a - b);
  state.number = available.includes(number) ? number : available.includes(state.book.total_chapters + 1) ? state.book.total_chapters + 1 : available.at(-1) ?? null;
  state.runs = []; state.history = [];
  renderBook(); renderEditor();
  await refreshShelf();
  if (state.tab === "runs") await loadRuns();
}
function renderBook() {
  const b = state.book;
  $("#welcome").hidden = true; $("#workspace").hidden = false;
  $("#breadcrumb").textContent = `我的作品 / ${b.spec.title}`;
  $("#book-title").textContent = b.spec.title; $("#book-genre").textContent = b.spec.genre;
  $("#book-meta").textContent = `${b.total_chapters} 章已完成 · ${b.total_words.toLocaleString()} 字符 · 单章目标 ${b.spec.chapter_words} 字`;
  $("#stage-label").textContent = `阶段 ${b.stage}`; $("#stage-goal").textContent = b.progress.goal;
  $("#export").href = path("/export");
  const available = [...new Set([...b.plans, ...b.chapters].map((c) => c.number))].sort((a, z) => a - z);
  $("#chapter-list").innerHTML = available.length ? available.map((number) => {
    const ch = b.chapters.find((c) => c.number === number), p = b.plans.find((c) => c.number === number);
    return `<button class="chapter-item ${state.number === number ? "active" : ""}" data-chapter="${number}"><span>第 ${String(number).padStart(2, "0")} 章 <em>${ch ? "已采纳" : "待写作"}</em></span><strong>${escape(ch?.title || p?.data.title)}</strong></button>`;
  }).join("") : `<div class="empty">${b.bible ? "点击「规划」<br>安排第一批章节" : "先在「作品设定」<br>构建故事的世界"}</div>`;
  renderBible(); renderMemory(); showTab(state.tab);
}
function renderEditor({ restore = true } = {}) {
  const ch = current(), p = plan();
  $("#chapter-label").textContent = state.number ? `CHAPTER ${String(state.number).padStart(2, "0")} / ${ch ? `版本 ${ch.version}` : "待写作"}` : "正文";
  $("#chapter-title").textContent = ch?.title || p?.data.title || "选择一个章节";
  state.baseline = ch?.content || ""; $("#content").value = state.baseline;
  $("#generate").textContent = ch ? "重新生成" : "生成正文";
  $("#outline-details").hidden = !p;
  $("#outline").innerHTML = p ? `<p><strong>本章目标：</strong>${escape(p.data.objective)}</p>${p.data.scenes.map((s, i) => `<div class="scene"><strong>${i + 1}. ${escape(s.location)} · ${escape(s.viewpoint)}</strong><p>目标：${escape(s.objective)}</p><p>冲突：${escape(s.conflict)}</p><p>变化：${escape(s.change)}</p></div>`).join("")}<p><strong>章末钩子：</strong>${escape(p.data.hook)}</p>` : "";
  $("#review-panel").hidden = !ch;
  $("#review-panel").innerHTML = ch ? `<h3>已采纳 · 审核摘要</h3><p>${escape(ch.review.summary)}</p><p class="muted">${ch.review.facts.length} 条事实 · 验收置信度 ${(ch.review.confidence * 100).toFixed(0)}%</p>` : "";
  if (restore && editable()) {
    try {
      const draft = JSON.parse(localStorage.getItem(draftKey()) || "null");
      if (draft && draft.content !== state.baseline) {
        if (draft.baseline === state.baseline) { $("#content").value = draft.content; notify("已恢复此浏览器中尚未保存的草稿"); }
        else notify("检测到基于旧版本的本地草稿，未自动覆盖当前正文；点击「本地草稿」可核对载入", true);
      }
    } catch { /* Reading is optional; canonical content remains available. */ }
  }
  try { $("#draft-restore").hidden = !state.number || !localStorage.getItem(draftKey()); }
  catch { $("#draft-restore").hidden = true; }
  updateEditorStatus(); controls();
}
function updateEditorStatus() {
  $("#word-count").textContent = `${[...$("#content").value].length.toLocaleString()} 字符`;
  $("#save-state").textContent = !state.number ? "尚未选择章节" : dirty() ? "有未保存修改 · 浏览器草稿" : current() ? "已审核保存" : "等待写作";
  if (state.number && !editable()) $("#save-state").textContent = "只读 · 仅当前阶段最新一章可编辑";
}
function renderBible() {
  const b = state.book.bible;
  $("#bible-generate").textContent = b ? "重新生成设定" : "生成作品设定";
  $("#bible-content").innerHTML = b ? `<article class="card"><h3>世界与时代</h3><p>${escape(b.world)}</p><h3>不可违背的规则</h3><ol>${b.rules.map((r) => `<li>${escape(r)}</li>`).join("")}</ol></article><div class="card-grid">${b.characters.map((c) => `<article class="card"><h3>${escape(c.name)}</h3><p>欲望：${escape(c.motivation)}</p><p class="muted">限制：${escape(c.constraints)}</p></article>`).join("")}</div><article class="card"><h3>分卷方向</h3>${b.arcs.map((a, i) => `<p><strong>${i + 1}. ${escape(a.title)}</strong><br>${escape(a.conflict)}<br><span class="muted">回报：${escape(a.payoff)}</span></p>`).join("")}<hr><h3>结局方向</h3><p>${escape(b.ending_direction)}</p></article>` : '<div class="empty">创意已就位。点击「生成作品设定」，构建世界规则、角色和分卷方向。</div>';
}
function renderMemory() {
  const names = { character: "人物状态", event: "已发生事件", thread: "伏笔" };
  $("#memory-content").innerHTML = state.book.memory.length ? `<div class="card-grid">${state.book.memory.map((f) => `<article class="card"><span class="pill">${names[f.kind]} · ${f.status === "resolved" ? "已完成" : "活跃"}</span><h3>${escape(f.subject)}</h3><p>${escape(f.detail)}</p><blockquote>${escape(f.evidence)}</blockquote><small>原文证据 · 第 ${f.chapter} 章</small></article>`).join("")}</div>` : '<div class="empty">正文通过审核后，人物、事件与伏笔会在这里留下记录。</div>';
}
function showTab(tab) {
  state.tab = tab;
  for (const name of ["writing", "bible", "memory", "runs"]) $(`#${name}-view`).hidden = tab !== name;
  document.querySelectorAll("[data-tab]").forEach((el) => { if (el.dataset.tab === tab) el.setAttribute("aria-current", "page"); else el.removeAttribute("aria-current"); });
}
async function loadRuns() {
  state.runs = await api(path("/runs"));
  const names = { bible: "作品设定", plan: "章节规划", write: "正文生成", edit: "正文审核", advance: "阶段切换" };
  $("#runs-content").innerHTML = state.runs.length ? state.runs.map((run, i) => {
    const art = run.artifacts, candidate = art.candidate;
    const tokens = run.calls.reduce((sum, c) => sum + (c.usage?.total_tokens || 0), 0);
    return `<article class="card"><div class="run-head"><h3>${names[run.operation] || escape(run.operation)}</h3><span class="pill ${run.status === "failed" ? "failure" : ""}">${({ succeeded: "已完成", failed: "未采纳", running: "执行中或曾中断" })[run.status] || escape(run.status)}</span></div><small>${escape(run.created_at)} UTC · ${tokens.toLocaleString()} tokens</small>${run.error ? `<p class="failure">${escape(run.error)}</p>` : ""}${art.review ? `<details><summary>审核结果</summary><div class="run-content">${escape(art.review.summary)}${art.review.contradictions.length ? `\n矛盾：${escape(art.review.contradictions.join("；"))}` : ""}\n${art.review.criteria.map((c) => `${c.achieved ? "✓" : "○"} ${escape(c.criterion)}\n${c.evidence.map(escape).join("\n")}`).join("\n")}</div></details>` : ""}${candidate ? `<details><summary>候选正文</summary><div class="run-content">${escape(candidate)}</div></details><div class="run-actions"><button class="secondary" data-recover="${i}">载入当前章节编辑器</button><button class="subtle" data-download-run="${i}">下载候选</button></div>` : ""}</article>`;
  }).join("") : '<div class="empty">还没有运行记录。完成一次生成后，可以在这里查看。</div>';
}
function stageDialog() {
  const progress = state.book.progress;
  $("#stage-progress").innerHTML = `<p>${escape(progress.goal)}</p>${progress.criteria.map((c) => `<div class="criterion"><strong class="${c.achieved ? "success" : "muted"}">${c.achieved ? "✓" : "○"} ${escape(c.criterion)}</strong>${c.evidence.map((e) => `<blockquote>第 ${e.chapter} 章：${e.quotes.map(escape).join("；")}</blockquote>`).join("")}</div>`).join("")}`;
  $("#stage-hint").textContent = progress.achieved ? "当前目标已验收。填写新目标并确认后，旧的未写规划会被清除。" : "当前阶段尚未全部验收，完成后才能进入下一阶段。";
  $("#stage-dialog").showModal(); controls();
}
function acceptance(form) { return [...new Set(form.get("acceptance").split(/\r?\n/).map((x) => x.trim()).filter(Boolean))]; }
function download(text, filename) {
  const url = URL.createObjectURL(new Blob([text], { type: "text/plain;charset=utf-8" }));
  const link = document.createElement("a"); link.href = url; link.download = filename; link.click(); setTimeout(() => URL.revokeObjectURL(url), 1000);
}

document.querySelectorAll("[data-close]").forEach((button) => { button.onclick = () => button.closest("dialog").close(); });
for (const selector of ["#new-book", "#welcome-create"]) $(selector).onclick = () => $("#book-dialog").showModal();
$("#book-list").onclick = async (event) => {
  const button = event.target.closest("[data-book]");
  if (!button || state.busy || button.dataset.book === state.book?.id || !await leaveDraft()) return;
  await action("加载作品…", () => loadBook(button.dataset.book));
};
$("#chapter-list").onclick = async (event) => {
  const button = event.target.closest("[data-chapter]");
  if (!button || state.busy || +button.dataset.chapter === state.number || !await leaveDraft()) return;
  state.number = +button.dataset.chapter; renderBook(); renderEditor();
};
$("#tabs").onclick = async (event) => {
  const button = event.target.closest("[data-tab]"); if (!button || state.busy) return;
  showTab(button.dataset.tab);
  if (state.tab === "runs") await action("读取运行记录…", loadRuns);
};
$("#content").oninput = () => { updateEditorStatus(); persistDraft(); controls(); };
$("#draft-restore").onclick = async () => {
  try {
    const draft = JSON.parse(localStorage.getItem(draftKey()) || "null");
    if (draft && await ask("载入本地草稿？", "本地草稿可能基于旧版本，载入后请核对正文并重新审核。当前编辑器内容会被替换。")) await recover(draft.content, state.number, true);
  } catch { notify("无法读取本地草稿", true); }
};
window.addEventListener("beforeunload", (event) => { if (dirty() || state.busy) { event.preventDefault(); event.returnValue = ""; } });
$("#refresh").onclick = async () => {
  if (!await leaveDraft()) return;
  await action("刷新中…", async () => { if (state.book) await loadBook(state.book.id, state.number); else await refreshShelf(); if (state.book && state.tab === "runs") await loadRuns(); });
};
$("#book-form").onsubmit = async (event) => {
  event.preventDefault(); if (!await leaveDraft()) return;
  const f = new FormData(event.currentTarget), rules = acceptance(f);
  if (!rules.length || rules.length > 20) return notify("请输入 1–20 条验收条件，每行一条", true);
  await action("创建作品…", async () => {
    const result = await post("/api/books", { book: { title: f.get("title"), genre: f.get("genre"), premise: f.get("premise"), style: f.get("style").trim() || "中文网文，场景具体，人物动机清楚", chapter_words: +f.get("chapter_words") }, stage: { goal: f.get("goal"), setting: f.get("setting"), acceptance: rules } });
    $("#book-dialog").close(); $("#book-form").reset(); state.tab = "bible"; await loadBook(result.id); notify("作品已创建，接下来生成作品设定");
  });
};
$("#bible-generate").onclick = async () => {
  if (state.book.bible && !await ask("重新生成设定？", "已有设定和未写章节的规划将被替换。")) return;
  await action("正在构建作品设定，请稍候…", async () => { await post(path("/bible")); await loadBook(state.book.id); notify("作品设定已生成，可以开始规划章节"); });
};
$("#plan-open").onclick = () => { $("#plan-form [name=start]").value = state.book.total_chapters + 1; $("#plan-form [name=start]").min = state.book.total_chapters + 1; $("#plan-dialog").showModal(); };
$("#plan-form").onsubmit = async (event) => {
  event.preventDefault(); if (!await leaveDraft()) return;
  const f = new FormData(event.currentTarget), start = +f.get("start");
  if (state.book.plans.some((p) => p.number >= start) && !await ask("替换后续规划？", `第 ${start} 章及其后的未写规划将被替换。`)) return;
  await action("正在安排章节与场景，请稍候…", async () => { await post(path("/plans"), { start, count: +f.get("count") }); $("#plan-dialog").close(); state.tab = "writing"; await loadBook(state.book.id, start); notify("章节规划已生成"); });
};
$("#generate").onclick = async () => {
  if ((current() || dirty()) && !await ask("重新生成正文？", "将生成新的候选并重新审核。成功后替换当前正文，保留已采纳历史版本，并清除后续未写规划。未保存的本地修改会被替换。")) return;
  await action("正在生成与审核完整正文，请稍候…", async () => {
    await post(path(`/chapters/${state.number}/generate`), { rewrite: !!current(), expected_revision: state.book.revision });
    try { localStorage.removeItem(draftKey()); } catch { /* Optional local storage. */ }
    await loadBook(state.book.id, state.number); notify("正文已生成并通过审核");
  });
};
$("#save").onclick = async () => {
  if (current() && !await ask("审核并保存修改？", "审核通过后保存为新版本，并清除依赖旧正文的后续未写规划。原版本会保留。")) return;
  await action("正在审核正文，未通过时会保留编辑内容…", async () => {
    await post(path(`/chapters/${state.number}/generate`), { rewrite: !!current(), content: $("#content").value, expected_revision: state.book.revision });
    try { localStorage.removeItem(draftKey()); } catch { /* Optional local storage. */ }
    await loadBook(state.book.id, state.number); notify("正文已审核保存");
  });
};
$("#advance").onclick = stageDialog;
$("#stage-form").onsubmit = async (event) => {
  event.preventDefault(); if (!await leaveDraft()) return;
  const f = new FormData(event.currentTarget), rules = acceptance(f);
  if (!rules.length || rules.length > 20) return notify("请输入 1–20 条验收条件", true);
  await action("更新阶段…", async () => { await post(path("/stages"), { stage: { goal: f.get("goal"), setting: f.get("setting"), acceptance: rules }, confirm: f.has("confirm") }); $("#stage-dialog").close(); $("#stage-form").reset(); await loadBook(state.book.id); notify("已开启下一阶段，请重新规划后续章节"); });
};
$("#history").onclick = () => action("读取历史版本…", async () => {
  state.history = await api(path(`/chapters/${state.number}/history`));
  $("#history-content").innerHTML = state.history.map((v, i) => `<article class="card"><h3>版本 ${v.version} · ${escape(v.title)}</h3><small>${escape(v.created_at)} UTC</small><div class="history-content">${escape(v.content)}</div><div class="run-actions"><button data-history="${i}" class="secondary">载入编辑器</button><button data-download-history="${i}" class="subtle">下载</button></div></article>`).join("") || '<div class="empty">暂无历史版本</div>';
  $("#history-dialog").showModal();
});
async function recover(content, number = state.number, confirmed = false) {
  if (!canEdit(number)) return notify("该候选对应章节当前不可编辑；仅可恢复当前阶段的最新一章或已规划的下一章。可先下载留存", true);
  if (!confirmed && dirty() && !await ask("替换编辑器内容？", "当前未保存的修改将被替换。载入后仍需点击「保存并审核」才能采纳。")) return;
  if (number !== state.number) { state.number = number; renderBook(); renderEditor({ restore: false }); }
  $("#content").value = content; showTab("writing"); updateEditorStatus(); persistDraft(); controls(); notify("已载入编辑器；审核保存后才会成为正式正文");
}
$("#runs-content").onclick = async (event) => {
  const recoverButton = event.target.closest("[data-recover]"), downloadButton = event.target.closest("[data-download-run]");
  if (recoverButton) { const run = state.runs[+recoverButton.dataset.recover]; await recover(run.artifacts.candidate, run.artifacts.context?.before_chapter ?? state.number); }
  if (downloadButton) download(state.runs[+downloadButton.dataset.downloadRun].artifacts.candidate, "candidate.txt");
};
$("#history-content").onclick = async (event) => {
  const restore = event.target.closest("[data-history]"), save = event.target.closest("[data-download-history]");
  if (restore) { $("#history-dialog").close(); await recover(state.history[+restore.dataset.history].content); }
  if (save) download(state.history[+save.dataset.downloadHistory].content, `chapter-${state.number}-v${state.history[+save.dataset.downloadHistory].version}.txt`);
};
$("#export").onclick = (event) => { if (state.busy) event.preventDefault(); };
await action("读取书架…", refreshShelf);
