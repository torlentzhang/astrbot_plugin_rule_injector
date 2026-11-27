/**
 * 两个列表的差异集中在这里。
 * 渲染、拖动、抽屉、保存都只认这份配置，不认具体是哪个列表。
 */

import { newId, sizeNode } from "./dom.js";

const SCOPE_LABEL = { group: "仅群聊", private: "仅私聊", all: "通用" };

function el(id) {
  return document.getElementById(id);
}

export const sections = {
  rules: {
    items: [],
    listEl: el("rule-list"),
    counterEl: el("counter"),
    addEl: el("add"),
    saveEl: el("save"),
    api: { save: "rule", remove: "rule/delete", bulk: "config", bulkKey: "rules" },
    maxKey: "max_rules",
    defaultMax: 10,
    emptyHint: "还没有规则，点右上角「新增规则」开始。",
    drawerTitle: "编辑规则",
    drawer: {
      root: el("drawer"),
      overlay: el("drawer-overlay"),
      title: el("drawer-title"),
      name: el("d-name"),
      scope: el("d-scope"),
      keyword: null,
      content: el("d-content"),
      chars: el("d-chars"),
      done: el("d-done"),
      del: el("d-delete"),
      close: el("drawer-close"),
      deleteLabel: "删除这条规则",
    },
    rowName: (r) => r.name || "未命名规则",
    renderMeta(meta, item) {
      const tag = document.createElement("span");
      tag.className = "scope-tag " + (item.scope || "all");
      tag.textContent = SCOPE_LABEL[item.scope] || "通用";
      meta.append(tag, sizeNode(item.content));
    },
    newItem: () => ({
      id: newId(),
      name: "",
      enabled: true,
      scope: "all",
      content: "",
    }),
  },

  thoughts: {
    items: [],
    listEl: el("thought-list"),
    counterEl: el("thought-counter"),
    addEl: el("add-thought"),
    saveEl: el("save-thoughts"),
    example: {
      user: el("example-user"),
      reply: el("example-reply"),
    },
    // 「示例与预览」是 thoughts 的第二视图，数据与保存仍归 thoughts
    exampleView: {
      thoughtsEl: el("example-thoughts"),
      previewBtn: el("preview-btn"),
      saveEl: el("save-examples"),
      dialog: el("preview-dialog"),
      body: el("preview-body"),
      source: el("preview-source"),
      close: el("preview-close"),
      done: el("preview-done"),
      scenes: document.querySelectorAll('input[name="preview-scene"]'),
    },
    api: {
      save: "thought",
      remove: "thought/delete",
      bulk: "thoughts",
      bulkKey: "thought_chains",
    },
    maxKey: "max_thought_chains",
    defaultMax: 5,
    emptyHint: "还没有思维链，点右上角「新增思维链」开始。",
    drawerTitle: "编辑思维链",
    drawer: {
      root: el("tdrawer"),
      overlay: el("tdrawer-overlay"),
      title: el("tdrawer-title"),
      name: el("t-name"),
      scope: null,
      keyword: el("t-keyword"),
      content: el("t-content"),
      chars: el("t-chars"),
      example: null,
      exampleChars: null,
      done: el("t-done"),
      del: el("t-delete"),
      close: el("tdrawer-close"),
      deleteLabel: "删除这条思维链",
    },
    rowName: (r) => r.name || r.keyword || "未命名思维链",
    renderMeta(meta, item) {
      const tag = document.createElement("span");
      tag.className = "scope-tag all";
      tag.textContent = `关键词 ${item.keyword}`;
      meta.append(tag, sizeNode(item.content));
    },
    newItem: ({ defaultThoughtRule } = {}) => ({
      id: newId(),
      name: "",
      keyword: "思维链",
      enabled: true,
      content: defaultThoughtRule || "",
      example_thought: "",
    }),
  },
};

/** 运行时状态，跨模块共享。 */
export const state = {
  limits: {},
  defaultThoughtRule: "",
  thoughtExample: { user: "", reply: "" },
  dirty: false,
  editing: { rules: -1, thoughts: -1 },
  drag: { rules: -1, thoughts: -1 },
};

/** 取某个列表的数量上限。 */
export function maxOf(key) {
  return state.limits[sections[key].maxKey] || sections[key].defaultMax;
}