/** 抽屉的打开、关闭与字段同步。 */

import { sections, state, maxOf } from "./config.js";
import { renderList } from "./list.js";

/** 同步抽屉里的字数统计。 */
export function syncChars(key) {
  const d = sections[key].drawer;
  d.chars.textContent = `${d.content.value.length} 字`;
  if (d.exampleChars) {
    d.exampleChars.textContent = `${d.example.value.length} 字`;
  }
}

export function openDrawer(key, index) {
  const sec = sections[key];
  const d = sec.drawer;
  const item = sec.items[index];
  if (!item) return;

  state.editing[key] = index;
  d.title.textContent = item.name || sec.drawerTitle;
  d.name.value = item.name || "";
  if (d.scope) d.scope.value = item.scope || "all";
  if (d.keyword) d.keyword.value = item.keyword || "";
  d.content.value = item.content || "";
  if (d.example) d.example.value = item.example_thought || "";
  syncChars(key);

  d.root.classList.add("open");
  d.overlay.classList.add("open");
  d.root.setAttribute("aria-hidden", "false");
  d.name.focus();
}

export function closeDrawer(key) {
  const d = sections[key].drawer;
  d.root.classList.remove("open");
  d.overlay.classList.remove("open");
  d.root.setAttribute("aria-hidden", "true");
  state.editing[key] = -1;
}

/** 取出抽屉里当前填的值。 */
export function readDrawer(key) {
  const sec = sections[key];
  const d = sec.drawer;
  const out = { name: d.name.value.trim(), content: d.content.value };
  if (d.scope) out.scope = d.scope.value;
  if (d.keyword) out.keyword = d.keyword.value.trim();
  if (d.example) out.example_thought = d.example.value.trim();
  return out;
}

/** 新增一条，写进内存并打开抽屉。 */
export function addItem(key) {
  const sec = sections[key];
  const max = maxOf(key);
  if (sec.items.length >= max) {
    document.dispatchEvent(
      new CustomEvent("ui:status", {
        detail: { text: `最多 ${max} 条`, kind: "err" },
      }),
    );
    return;
  }
  sec.items.push(sec.newItem({ defaultThoughtRule: state.defaultThoughtRule }));
  renderList(key);
  openDrawer(key, sec.items.length - 1);
}