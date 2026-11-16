const bridge = window.AstrBotPluginView || window.AstrBotPluginPage;

const els = {
  save: document.getElementById("save"),
  add: document.getElementById("add"),
  status: document.getElementById("status"),
  list: document.getElementById("rule-list"),
  counter: document.getElementById("counter"),
  overlay: document.getElementById("drawer-overlay"),
  drawer: document.getElementById("drawer"),
  title: document.getElementById("drawer-title"),
  dName: document.getElementById("d-name"),
  dScope: document.getElementById("d-scope"),
  dContent: document.getElementById("d-content"),
  dChars: document.getElementById("d-chars"),
  dDelete: document.getElementById("d-delete"),
  dDone: document.getElementById("d-done"),
  close: document.getElementById("drawer-close"),
  confirmOverlay: document.getElementById("confirm-overlay"),
  confirmText: document.getElementById("confirm-text"),
  confirmOk: document.getElementById("confirm-ok"),
  confirmCancel: document.getElementById("confirm-cancel"),
};

let limits = { max_rules: 10 };
let rules = [];
let editingIndex = -1;
let dragIndex = -1;

const SCOPE_LABEL = { group: "仅群聊", private: "仅私聊", all: "通用" };

function setStatus(text, kind = "") {
  els.status.textContent = text;
  els.status.className = "status" + (kind ? " " + kind : "");
}

function askConfirm(message) {
  return new Promise((resolve) => {
    els.confirmText.textContent = message;
    els.confirmOverlay.hidden = false;

    const cleanup = (result) => {
      els.confirmOverlay.hidden = true;
      els.confirmOk.removeEventListener("click", onOk);
      els.confirmCancel.removeEventListener("click", onCancel);
      els.confirmOverlay.removeEventListener("click", onOverlay);
      document.removeEventListener("keydown", onKey);
      resolve(result);
    };
    const onOk = () => cleanup(true);
    const onCancel = () => cleanup(false);
    const onOverlay = (e) => {
      if (e.target === els.confirmOverlay) cleanup(false);
    };
    const onKey = (e) => {
      if (e.key === "Escape") cleanup(false);
    };

    els.confirmOk.addEventListener("click", onOk);
    els.confirmCancel.addEventListener("click", onCancel);
    els.confirmOverlay.addEventListener("click", onOverlay);
    document.addEventListener("keydown", onKey);
  });
}

let dirty = false;

function markDirty() {
  dirty = true;
  setStatus("有未保存的更改", "");
}

function unwrap(payload) {
  if (payload && typeof payload === "object" && "data" in payload) return payload.data;
  return payload;
}

function newId() {
  return Math.random().toString(16).slice(2, 10);
}

/* ---------------- 列表渲染 ---------------- */

function preview(content) {
  const flat = (content || "").replace(/\s+/g, " ").trim();
  return flat || "（内容为空）";
}

function render() {
  els.list.innerHTML = "";

  if (rules.length === 0) {
    const hint = document.createElement("p");
    hint.className = "empty-hint";
    hint.textContent = "还没有规则，点右上角「新增规则」开始。";
    els.list.appendChild(hint);
  } else {
    rules.forEach((rule, index) => {
      const row = document.createElement("div");
      row.className = "rule-row" + (rule.enabled ? "" : " is-off");

      const check = document.createElement("input");
      check.type = "checkbox";
      check.className = "row-check";
      check.checked = rule.enabled;
      check.addEventListener("click", (e) => e.stopPropagation());
      check.addEventListener("change", () => {
        rules[index].enabled = check.checked;
        row.classList.toggle("is-off", !check.checked);
        markDirty();
      });

      const main = document.createElement("div");
      main.className = "row-main";

      const name = document.createElement("div");
      name.className = "row-name";
      name.textContent = rule.name || "未命名规则";

      const meta = document.createElement("div");
      meta.className = "row-meta";
      const tag = document.createElement("span");
      tag.className = "scope-tag " + (rule.scope || "all");
      tag.textContent = SCOPE_LABEL[rule.scope] || "通用";
      const size = document.createElement("span");
      size.textContent = `${(rule.content || "").length} 字`;
      meta.append(tag, size);

      const prev = document.createElement("div");
      prev.className = "row-preview";
      prev.textContent = preview(rule.content);

      main.append(name, meta, prev);

      const arrow = document.createElement("span");
      arrow.className = "row-arrow";
      arrow.textContent = "›";

      const grip = document.createElement("span");
      grip.className = "row-grip";
      grip.textContent = "⋮⋮";
      grip.setAttribute("draggable", "true");
      grip.title = "拖动调整顺序";
      row.append(grip, check, main, arrow);
      row.addEventListener("click", () => openDrawer(index));

      row.addEventListener("dragstart", (e) => {
        dragIndex = index;
        row.classList.add("is-dragging");
        e.dataTransfer.effectAllowed = "move";
      });
      row.addEventListener("dragend", () => {
        row.classList.remove("is-dragging");
        dragIndex = -1;
        els.list.querySelectorAll(".is-drop-target").forEach((el) => {
          el.classList.remove("is-drop-target");
        });
      });
      row.addEventListener("dragover", (e) => {
        if (dragIndex < 0 || dragIndex === index) return;
        e.preventDefault();
        e.dataTransfer.dropEffect = "move";
        row.classList.add("is-drop-target");
      });
      row.addEventListener("dragleave", () => {
        row.classList.remove("is-drop-target");
      });
      row.addEventListener("drop", (e) => {
        e.preventDefault();
        row.classList.remove("is-drop-target");
        if (dragIndex < 0 || dragIndex === index) return;
        const moved = rules.splice(dragIndex, 1)[0];
        rules.splice(index, 0, moved);
        dragIndex = -1;
        render();
        markDirty();
      });
      els.list.appendChild(row);
    });
  }

  els.counter.textContent = `${rules.length} / ${limits.max_rules} 条`;
  els.add.disabled = rules.length >= limits.max_rules;
}

/* ---------------- 抽屉 ---------------- */

function syncDrawerChars() {
  els.dChars.textContent = `${els.dContent.value.length} 字`;
}

function openDrawer(index) {
  editingIndex = index;
  const rule = rules[index];
  els.title.textContent = rule.name || "编辑规则";
  els.dName.value = rule.name || "";
  els.dScope.value = rule.scope || "all";
  els.dContent.value = rule.content || "";
  syncDrawerChars();
  els.drawer.classList.add("open");
  els.overlay.classList.add("open");
  els.drawer.setAttribute("aria-hidden", "false");
  els.dName.focus();
}

function closeDrawer() {
  els.drawer.classList.remove("open");
  els.overlay.classList.remove("open");
  els.drawer.setAttribute("aria-hidden", "true");
  editingIndex = -1;
}

function readDrawer() {
  return {
    name: els.dName.value.trim(),
    scope: els.dScope.value,
    content: els.dContent.value,
  };
}

function addRule() {
  if (rules.length >= limits.max_rules) {
    setStatus(`最多 ${limits.max_rules} 条规则`, "err");
    return;
  }
  const rule = {
    id: newId(),
    name: "",
    enabled: true,
    scope: "all",
    content: "",
  };
  rules.push(rule);
  render();
  openDrawer(rules.length - 1);
}

/* ---------------- 交互绑定 ---------------- */

els.dContent.addEventListener("input", syncDrawerChars);

els.dName.addEventListener("input", () => {
  els.title.textContent = els.dName.value.trim() || "编辑规则";
});

els.dDone.addEventListener("click", async () => {
  if (editingIndex < 0 || !rules[editingIndex]) return;
  const rule = rules[editingIndex];
  const draft = readDrawer();
  if (!draft.content.trim()) {
    setStatus("规则内容不能为空", "err");
    return;
  }
  els.dDone.disabled = true;
  setStatus("保存中…");
  try {
    const raw = await bridge.apiPost("rule", {
      id: rule.id,
      name: draft.name,
      scope: draft.scope,
      content: draft.content,
    });
    const data = unwrap(raw) || {};
    if (data.ok === false) throw new Error(data.error || "保存被拒绝");
    if (Array.isArray(data.rules)) rules = data.rules;
    render();
    setStatus("已保存", "ok");
    closeDrawer();
  } catch (err) {
    setStatus("保存失败：" + (err && err.message ? err.message : String(err)), "err");
  } finally {
    els.dDone.disabled = false;
  }
});

els.close.addEventListener("click", closeDrawer);

els.overlay.addEventListener("click", closeDrawer);

document.addEventListener("keydown", (e) => {
  if (e.key === "Escape" && els.drawer.classList.contains("open")) {
    closeDrawer();
  }
});

els.dDelete.addEventListener("click", async () => {
  if (editingIndex < 0) return;
  const rule = rules[editingIndex];
  const label = rule.name || "这条规则";
  const confirmed = await askConfirm(`确认删除「${label}」吗？`);
  if (!confirmed) return;
  try {
    const raw = await bridge.apiPost("rule/delete", { id: rule.id });
    const data = unwrap(raw) || {};
    if (data.ok === false) throw new Error(data.error || "删除被拒绝");
    if (Array.isArray(data.rules)) rules = data.rules;
    closeDrawer();
    render();
    setStatus("已删除", "ok");
  } catch (err) {
    setStatus("删除失败：" + (err && err.message ? err.message : String(err)), "err");
  }
});

els.add.addEventListener("click", addRule);

/* ---------------- 读取 / 保存 ---------------- */

async function load() {
  setStatus("加载中…");
  try {
    const raw = await bridge.apiGet("config", {});
    const data = unwrap(raw) || {};
    if (data.limits) limits = { ...limits, ...data.limits };
    rules = Array.isArray(data.rules) ? data.rules : [];
    render();
    setStatus("");
  } catch (err) {
    setStatus("读取失败：" + (err && err.message ? err.message : String(err)), "err");
  }
}

async function save() {
  els.save.disabled = true;
  setStatus("保存中…");
  try {
    const payload = rules.map((r) => ({
      id: r.id,
      name: (r.name || "").trim(),
      enabled: !!r.enabled,
      scope: r.scope || "all",
      content: r.content || "",
    }));
    const raw = await bridge.apiPost("config", { rules: payload });
    const data = unwrap(raw) || {};
    if (data && data.ok === false) throw new Error(data.error || "保存被拒绝");
    const count = typeof data.count === "number" ? data.count : payload.length;
    dirty = false;
    setStatus(`已保存（${count} 条规则）`, "ok");
    if (Array.isArray(data.rules)) {
      rules = data.rules;
      render();
    }
  } catch (err) {
    setStatus("保存失败：" + (err && err.message ? err.message : String(err)), "err");
  } finally {
    els.save.disabled = false;
  }
}

els.save.addEventListener("click", save);

await bridge.ready();
await load();
