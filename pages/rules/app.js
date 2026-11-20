/**
 * 入口：装配各模块、绑定事件、启动加载。
 * 具体逻辑分散在 js/ 下，这里只做编排。
 */

import { bridge, get } from "./js/bridge.js";
import { sections, state } from "./js/config.js";
import { renderList } from "./js/list.js";
import { addItem, closeDrawer, openDrawer, syncChars } from "./js/drawer.js";
import { deleteItem, saveAll, saveItem } from "./js/api.js";
import { initTabs } from "./js/tabs.js";

const els = {
  status: document.getElementById("status"),
  confirmOverlay: document.getElementById("confirm-overlay"),
  confirmText: document.getElementById("confirm-text"),
  confirmOk: document.getElementById("confirm-ok"),
  confirmCancel: document.getElementById("confirm-cancel"),
};

/* ---------------------------------------------------------------- 状态提示 */

function setStatus(text, kind = "") {
  els.status.textContent = text;
  els.status.className = "status" + (kind ? " " + kind : "");
}

document.addEventListener("ui:status", (e) => {
  setStatus(e.detail.text, e.detail.kind || "");
});

document.addEventListener("list:dirty", () => {
  state.dirty = true;
  setStatus("有未保存的更改", "");
});

/* ---------------------------------------------------------------- 确认框 */

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

/* ---------------------------------------------------------------- 装配 */

/** 把某个列表的按钮与抽屉事件接上。 */
function bindSection(key) {
  const sec = sections[key];
  const d = sec.drawer;

  sec.addEl.addEventListener("click", () => addItem(key));
  sec.saveEl.addEventListener("click", () => saveAll(key));

  d.content.addEventListener("input", () => syncChars(key));
  d.name.addEventListener("input", () => {
    d.title.textContent = d.name.value.trim() || sec.drawerTitle;
  });

  d.done.addEventListener("click", () => saveItem(key));
  d.del.textContent = d.deleteLabel;
  d.del.addEventListener("click", () => deleteItem(key, askConfirm));
  d.close.addEventListener("click", () => closeDrawer(key));
  d.overlay.addEventListener("click", () => closeDrawer(key));

  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape" && d.root.classList.contains("open")) closeDrawer(key);
  });
}

Object.keys(sections).forEach(bindSection);

// 列表行点击 → 开抽屉
document.addEventListener("list:open", (e) => {
  const { key, index } = e.detail;
  openDrawer(key, index);
});

initTabs(() => setStatus(""));

/* ---------------------------------------------------------------- 启动 */

async function load() {
  setStatus("加载中…");
  try {
    const data = await get("config");
    if (data.limits) state.limits = { ...data.limits };
    if (typeof data.default_thought_rule === "string") {
      state.defaultThoughtRule = data.default_thought_rule;
    }
    sections.rules.items = Array.isArray(data.rules) ? data.rules : [];
    sections.thoughts.items = Array.isArray(data.thought_chains)
      ? data.thought_chains
      : [];
    renderList("rules");
    renderList("thoughts");
    setStatus("");
  } catch (err) {
    setStatus("读取失败：" + (err && err.message ? err.message : String(err)), "err");
  }
}

await bridge.ready();
await load();