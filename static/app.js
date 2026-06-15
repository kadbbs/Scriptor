let state = {
  projects: [],
  project: null,
  chapter: null,
};

const $ = (selector) => document.querySelector(selector);

function setStatus(text) {
  $("#status").textContent = text || "";
}

async function api(path, options = {}) {
  const response = await fetch(path, {
    headers: { "Content-Type": "application/json" },
    ...options,
  });
  if (!response.ok) {
    const detail = await response.json().catch(() => ({}));
    throw new Error(detail.detail || response.statusText);
  }
  return response.json();
}

async function loadProjects() {
  state.projects = await api("/api/projects");
  renderProjects();
}

async function loadProject(id) {
  state.project = await api(`/api/projects/${id}`);
  state.chapter = null;
  renderProject();
}

function renderProjects() {
  const list = $("#projectList");
  list.innerHTML = "";
  state.projects.forEach((project) => {
    const item = document.createElement("div");
    item.className = `project-item ${state.project?.id === project.id ? "active" : ""}`;
    item.innerHTML = `<strong>${escapeHtml(project.title)}</strong><span>${escapeHtml(project.genre || "未分类")} · ${project.target_chapters}章</span>`;
    item.addEventListener("click", () => loadProject(project.id));
    list.appendChild(item);
  });
}

function renderProject() {
  const project = state.project;
  renderProjects();
  $("#projectTitle").textContent = project.title;
  $("#projectMeta").textContent = `${project.genre || "未分类"} · ${project.target_chapters}章 · 每章约${project.chapter_words}字`;
  $("#bibleText").textContent = project.bible || "暂无设定。";
  $("#bibleBtn").disabled = false;
  $("#outlineBtn").disabled = !project.bible;
  const maxChapter = project.chapters.reduce((max, chapter) => Math.max(max, chapter.number), 0);
  $("#outlineStart").value = maxChapter + 1;

  const chapters = $("#chapterList");
  chapters.innerHTML = "";
  project.chapters.forEach((chapter) => {
    const row = document.createElement("div");
    row.className = `chapter-row ${state.chapter?.id === chapter.id ? "active" : ""}`;
    row.innerHTML = `<strong>第${chapter.number}章 ${escapeHtml(chapter.title || "未命名")}</strong><span>${escapeHtml(chapter.outline || "暂无大纲")}</span>`;
    row.addEventListener("click", () => selectChapter(chapter));
    chapters.appendChild(row);
  });

  if (!project.chapters.length) {
    chapters.innerHTML = `<div class="chapter-row"><strong>暂无章节</strong><span>先生成一批大纲</span></div>`;
  }
  renderChapter();
}

function selectChapter(chapter) {
  state.chapter = chapter;
  renderProject();
}

function renderChapter() {
  const chapter = state.chapter;
  $("#chapterBtn").disabled = !chapter;
  if (!chapter) {
    $("#chapterTitle").textContent = "正文";
    $("#chapterOutline").textContent = "";
    $("#chapterContent").value = "";
    return;
  }
  $("#chapterTitle").textContent = `第${chapter.number}章 ${chapter.title || "未命名"}`;
  $("#chapterOutline").textContent = chapter.outline || "";
  $("#chapterContent").value = chapter.content || "";
}

$("#projectForm").addEventListener("submit", async (event) => {
  event.preventDefault();
  const formEl = event.currentTarget;
  const form = new FormData(formEl);
  const payload = Object.fromEntries(form.entries());
  payload.target_chapters = Number(payload.target_chapters || 500);
  payload.chapter_words = Number(payload.chapter_words || 3000);
  setStatus("正在创建项目...");
  try {
    const project = await api("/api/projects", { method: "POST", body: JSON.stringify(payload) });
    formEl.reset();
    await loadProjects();
    await loadProject(project.id);
    setStatus("项目已创建");
  } catch (error) {
    setStatus(error.message);
  }
});

$("#bibleBtn").addEventListener("click", async () => {
  if (!state.project) return;
  setStatus("正在生成设定...");
  $("#bibleBtn").disabled = true;
  try {
    await api(`/api/projects/${state.project.id}/bible`, { method: "POST" });
    await loadProject(state.project.id);
    setStatus("设定已生成");
  } catch (error) {
    setStatus(error.message);
  } finally {
    $("#bibleBtn").disabled = false;
  }
});

$("#outlineBtn").addEventListener("click", async () => {
  if (!state.project) return;
  const start = Number($("#outlineStart").value || 1);
  const count = Number($("#outlineCount").value || 20);
  setStatus(`正在生成第 ${start}-${start + count - 1} 章大纲...`);
  $("#outlineBtn").disabled = true;
  try {
    await api(`/api/projects/${state.project.id}/outline`, {
      method: "POST",
      body: JSON.stringify({ start, count }),
    });
    $("#outlineStart").value = start + count;
    await loadProject(state.project.id);
    setStatus("大纲批次已生成");
  } catch (error) {
    setStatus(error.message);
  } finally {
    $("#outlineBtn").disabled = false;
  }
});

$("#chapterBtn").addEventListener("click", async () => {
  if (!state.project || !state.chapter) return;
  setStatus(`正在生成第 ${state.chapter.number} 章正文...`);
  $("#chapterBtn").disabled = true;
  try {
    await api(`/api/projects/${state.project.id}/chapters/${state.chapter.number}/content`, { method: "POST" });
    const chapter = await api(`/api/projects/${state.project.id}/chapters/${state.chapter.number}`);
    state.chapter = chapter;
    await loadProject(state.project.id);
    state.chapter = chapter;
    renderChapter();
    setStatus("正文已生成");
  } catch (error) {
    setStatus(error.message);
  } finally {
    $("#chapterBtn").disabled = false;
  }
});

function escapeHtml(value) {
  return String(value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

loadProjects().catch((error) => setStatus(error.message));
