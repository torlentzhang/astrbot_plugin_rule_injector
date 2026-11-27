/**
 * 入口：装配各模块、绑定事件、启动加载。
 * 具体逻辑分散在 components/ 与 utils/ 下，这里只做编排。
 */

import { bridge, get, getProfile } from "./utils/bridge.js";
import { sections, state } from "./utils/model.js";
import { renderList } from "./components/rule-list.js";
import {
  addItem,
  closeDrawer,
  openDrawer,
  syncChars,
  syncExample,
} from "./components/rule-drawer.js";
import { deleteItem, saveAll, saveItem } from "./utils/api.js";
import { initTabs } from "./components/tabs.js";
import { initExamples, renderExampleThoughts } from "./components/thought-editor.js";
import { askConfirm } from "./components/confirm-dialog.js";
import { initProfileSelector, loadProfiles } from "./components/profile-selector.js";

const els = {
  status: document.getElementById("status"),
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

// 示例场景跟着思维链那页的「保存」一起落盘
Object.values(sections.thoughts.example).forEach((field) => {
  field.addEventListener("input", () => {
    document.dispatchEvent(new CustomEvent("list:dirty"));
  });
});

// 列表行点击 → 开抽屉
document.addEventListener("list:open", (e) => {
  const { key, index } = e.detail;
  openDrawer(key, index);
});

initTabs(() => setStatus(""));
initExamples(saveAll);
initProfileSelector(load);

/* ---------------------------------------------------------------- 启动 */

async function load() {
  setStatus("加载中…");
  try {
    const data = await get("config", { profile: getProfile() });
    if (data.limits) state.limits = { ...data.limits };
    if (typeof data.default_thought_rule === "string") {
      state.defaultThoughtRule = data.default_thought_rule;
    }
    sections.rules.items = Array.isArray(data.rules) ? data.rules : [];
    sections.thoughts.items = Array.isArray(data.thought_chains)
      ? data.thought_chains
      : [];
    if (data.thought_example && typeof data.thought_example === "object") {
      state.thoughtExample = {
        user: data.thought_example.user || "",
        reply: data.thought_example.reply || "",
      };
    }
    syncExample();
    renderList("rules");
    renderList("thoughts");
    renderExampleThoughts();
    setStatus("");
  } catch (err) {
    setStatus("读取失败：" + (err && err.message ? err.message : String(err)), "err");
  }
}

await bridge.ready();
if (await loadProfiles()) {
  await load();
} else {
  setStatus("没有可用配置文件", "err");
}
