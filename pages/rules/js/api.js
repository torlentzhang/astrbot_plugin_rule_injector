/** 单条保存、删除，以及整体保存（顺序 + 启用状态）。 */

import { sections, state } from "./config.js";
import { post } from "./bridge.js";
import { renderList } from "./list.js";
import { closeDrawer, readDrawer } from "./drawer.js";

function status(text, kind) {
  document.dispatchEvent(
    new CustomEvent("ui:status", { detail: { text, kind } }),
  );
}

/** 抽屉里的「保存」。 */
export async function saveItem(key) {
  const sec = sections[key];
  const index = state.editing[key];
  if (index < 0 || !sec.items[index]) return;

  const draft = readDrawer(key);
  if (sec.drawer.keyword && !draft.keyword) {
    status("关键词不能为空", "err");
    return;
  }

  const payload = {
    id: sec.items[index].id,
    name: draft.name,
    content: draft.content,
  };
  if (draft.scope) payload.scope = draft.scope;
  if (draft.keyword) payload.keyword = draft.keyword;
  if (draft.example_thought !== undefined) {
    payload.example_thought = draft.example_thought;
  }

  sec.drawer.done.disabled = true;
  status("保存中…");
  try {
    const data = await post(sec.api.save, payload);
    if (Array.isArray(data[sec.api.bulkKey])) {
      sec.items = data[sec.api.bulkKey];
    }
    renderList(key);
    status("已保存", "ok");
    closeDrawer(key);
  } catch (err) {
    status("保存失败：" + (err && err.message ? err.message : String(err)), "err");
  } finally {
    sec.drawer.done.disabled = false;
  }
}

/** 抽屉里的「删除」。 */
export async function deleteItem(key, confirmFn) {
  const sec = sections[key];
  const index = state.editing[key];
  if (index < 0) return;

  const item = sec.items[index];
  const ok = await confirmFn(`确认删除「${sec.rowName(item)}」吗？`);
  if (!ok) return;

  try {
    const data = await post(sec.api.remove, { id: item.id });
    if (Array.isArray(data[sec.api.bulkKey])) sec.items = data[sec.api.bulkKey];
    closeDrawer(key);
    renderList(key);
    status("已删除", "ok");
  } catch (err) {
    status("删除失败：" + (err && err.message ? err.message : String(err)), "err");
  }
}

/** 工具栏的「保存」：提交顺序与启用状态。 */
export async function saveAll(key) {
  const sec = sections[key];
  const payload = sec.items.map((item) => {
    const out = {
      id: item.id,
      name: (item.name || "").trim(),
      enabled: !!item.enabled,
      content: item.content || "",
    };
    if (item.scope !== undefined) out.scope = item.scope || "all";
    if (item.keyword !== undefined) out.keyword = item.keyword || "";
    if (item.example_thought !== undefined) {
      out.example_thought = item.example_thought || "";
    }
    return out;
  });

  sec.saveEl.disabled = true;
  status("保存中…");
  try {
    const data = await post(sec.api.bulk, { [sec.api.bulkKey]: payload });
    state.dirty = false;
    const count = typeof data.count === "number" ? data.count : payload.length;
    status(`已保存（${count} 条）`, "ok");
    if (Array.isArray(data[sec.api.bulkKey])) {
      sec.items = data[sec.api.bulkKey];
      renderList(key);
    }
  } catch (err) {
    status("保存失败：" + (err && err.message ? err.message : String(err)), "err");
  } finally {
    sec.saveEl.disabled = false;
  }
}