/** 列表渲染与拖动排序。 */

import { sections, state, maxOf } from "../utils/model.js";
import { preview } from "../utils/dom.js";

/** 渲染某个列表。key 为 "rules" 或 "thoughts"。 */
export function renderList(key) {
  const sec = sections[key];
  const items = sec.items;

  sec.listEl.innerHTML = "";

  if (items.length === 0) {
    const hint = document.createElement("p");
    hint.className = "empty-hint";
    hint.textContent = sec.emptyHint;
    sec.listEl.appendChild(hint);
  } else {
    items.forEach((item, index) => {
      sec.listEl.appendChild(buildRow(key, item, index));
    });
  }

  const max = maxOf(key);
  sec.counterEl.textContent = `${items.length} / ${max} 条`;
  sec.addEl.disabled = items.length >= max;
}

/** 组装单行；onOpen 在点击行时回调。 */
function buildRow(key, item, index) {
  const sec = sections[key];
  const row = document.createElement("div");
  row.className = "rule-row" + (item.enabled ? "" : " is-off");

  const check = document.createElement("input");
  check.type = "checkbox";
  check.className = "row-check";
  check.checked = item.enabled;
  check.addEventListener("click", (e) => e.stopPropagation());
  check.addEventListener("change", () => {
    sec.items[index].enabled = check.checked;
    row.classList.toggle("is-off", !check.checked);
    state.dirty = true;
    document.dispatchEvent(new CustomEvent("list:dirty"));
  });

  const main = document.createElement("div");
  main.className = "row-main";

  const name = document.createElement("div");
  name.className = "row-name";
  name.textContent = sec.rowName(item);

  const meta = document.createElement("div");
  meta.className = "row-meta";
  sec.renderMeta(meta, item);

  const prev = document.createElement("div");
  prev.className = "row-preview";
  prev.textContent = preview(item.content);

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
  row.addEventListener("click", () => {
    document.dispatchEvent(
      new CustomEvent("list:open", { detail: { key, index } }),
    );
  });
  attachDrag(key, row, index);

  return row;
}

/** 拖动排序，两个列表共用。 */
function attachDrag(key, row, index) {
  const sec = sections[key];

  row.addEventListener("dragstart", (e) => {
    state.drag[key] = index;
    row.classList.add("is-dragging");
    e.dataTransfer.effectAllowed = "move";
  });
  row.addEventListener("dragend", () => {
    row.classList.remove("is-dragging");
    state.drag[key] = -1;
    sec.listEl.querySelectorAll(".is-drop-target").forEach((el) => {
      el.classList.remove("is-drop-target");
    });
  });
  row.addEventListener("dragover", (e) => {
    if (state.drag[key] < 0 || state.drag[key] === index) return;
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
    const from = state.drag[key];
    if (from < 0 || from === index) return;
    const moved = sec.items.splice(from, 1)[0];
    sec.items.splice(index, 0, moved);
    state.drag[key] = -1;
    renderList(key);
    state.dirty = true;
    document.dispatchEvent(new CustomEvent("list:dirty"));
  });
}