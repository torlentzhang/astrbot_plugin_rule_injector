/**
 * 入口：装配各模块、绑定事件、启动加载。
 * 具体逻辑分散在 js/ 下，这里只做编排。
 */

import { bridge, get, setProfile, getProfile } from "./js/bridge.js";
import { sections, state } from "./js/config.js";
import { renderList } from "./js/list.js";
import {
  addItem,
  closeDrawer,
  openDrawer,
  syncChars,
  syncExample,
} from "./js/drawer.js";
import { deleteItem, saveAll, saveItem } from "./js/api.js";
import { initTabs } from "./js/tabs.js";
import { initExamples, renderExampleThoughts } from "./js/examples.js";

const els = {
  status: document.getElementById("status"),
  confirmOverlay: document.getElementById("confirm-overlay"),
  confirmText: document.getElementById("confirm-text"),
  confirmOk: document.getElementById("confirm-ok"),
  confirmCancel: document.getElementById("confirm-cancel"),
  profileSelect: document.getElementById("profile-select"),
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

function askConfirm(message, okLabel = "删除") {
  return new Promise((resolve) => {
    els.confirmText.textContent = message;
    els.confirmOk.textContent = okLabel;
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

/* ---------------------------------------------------------------- 档案 */

/** 拉取档案列表并填充下拉框，默认选中第一个。 */
async function loadProfiles() {
  const data = await get("profiles");
  const list = Array.isArray(data.profiles) ? data.profiles : [];
  els.profileSelect.innerHTML = "";

  list.forEach((item) => {
    const option = document.createElement("option");
    option.value = item.key;
    option.textContent = item.is_default
      ? `${item.name}（默认档案）`
      : item.name;
    els.profileSelect.appendChild(option);
  });

  if (!list.length) {
    const option = document.createElement("option");
    option.textContent = "没有可用档案";
    option.disabled = true;
    els.profileSelect.appendChild(option);
    return false;
  }

  const initial = list[0].key;
  els.profileSelect.value = initial;
  setProfile(initial);
  return true;
}

/** 切换档案：先确认丢弃未保存的草稿，再加载新档案的配置。 */
async function switchProfile(next) {
  if (next === getProfile()) return;
  if (state.dirty) {
    const ok = await askConfirm(
      "切换档案会丢弃当前未保存的更改，确认切换吗？",
      "切换",
    );
    if (!ok) {
      els.profileSelect.value = getProfile();
      return;
    }
  }
  setProfile(next);
  state.dirty = false;
  await load();
}

els.profileSelect.addEventListener("change", (e) => {
  switchProfile(e.target.value);
});

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
  setStatus("没有可用档案", "err");
}