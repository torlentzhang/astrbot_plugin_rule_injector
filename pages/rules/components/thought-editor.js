/**
 * 「示例与预览」视图：集中编辑一问一答与每段念头，并预览实际注入的两部分。
 * 数据仍归属 sections.thoughts，这里只渲染输入框并消费预览接口。
 */

import { sections, state } from "../utils/model.js";
import { post } from "../utils/bridge.js";
import { preview as summary } from "../utils/dom.js";
import { readExample } from "./rule-drawer.js";

function status(text, kind) {
  document.dispatchEvent(
    new CustomEvent("ui:status", { detail: { text, kind } }),
  );
}

/** 与后端拼装同口径：启用且内容非空的链才参与示例。 */
function activeChains() {
  return sections.thoughts.items.filter(
    (item) => item.enabled && (item.content || "").trim(),
  );
}

/** 按当前启用的链渲染念头输入框，keyword 直接做标签名。 */
export function renderExampleThoughts() {
  const host = sections.thoughts.exampleView.thoughtsEl;
  host.innerHTML = "";

  const chains = activeChains();
  if (!chains.length) {
    const hint = document.createElement("p");
    hint.className = "empty-hint";
    hint.textContent = "还没有启用的思维链，先在「自定义思维链」里添加。";
    host.appendChild(hint);
    return;
  }

  chains.forEach((chain) => {
    const row = document.createElement("div");
    row.className = "example-thought-row";

    const head = document.createElement("div");
    head.className = "thought-row-head";

    const tag = document.createElement("span");
    tag.className = "keyword-tag";
    tag.textContent = `<${chain.keyword}>`;

    const name = document.createElement("span");
    name.className = "thought-row-name";
    name.textContent = chain.name || chain.keyword;
    head.append(tag, name);

    const inputId = `example-thought-${chain.id}`;
    const label = document.createElement("label");
    label.className = "field-label";
    label.htmlFor = inputId;
    label.textContent = "示例念头";

    const input = document.createElement("textarea");
    input.id = inputId;
    input.className = "text-area text-area-short";
    input.maxLength = state.limits.max_example_thought_chars || 500;
    input.spellcheck = false;
    input.placeholder = `写一句 <${chain.keyword}> 里的真实念头`;
    input.value = chain.example_thought || "";
    input.addEventListener("input", () => {
      // 写回共享内存，保存时由 saveAll("thoughts") 一并落盘
      chain.example_thought = input.value.trim();
      state.dirty = true;
      document.dispatchEvent(new CustomEvent("list:dirty"));
    });

    const hint = document.createElement("span");
    hint.className = "field-hint";
    hint.textContent = `留空时复用规则内容：${summary(chain.content)}`;

    row.append(head, label, input, hint);
    host.appendChild(row);
  });
}

function currentScene() {
  for (const radio of sections.thoughts.exampleView.scenes) {
    if (radio.checked) return radio.value;
  }
  return "group";
}

function blockSection(title, text) {
  const wrap = document.createElement("section");
  wrap.className = "preview-section";

  const heading = document.createElement("h3");
  heading.className = "preview-section-title";
  heading.textContent = title;

  const pre = document.createElement("pre");
  pre.className = "snippet";
  pre.textContent = text || "（无内容）";

  wrap.append(heading, pre);
  return wrap;
}

function contextsSection(contexts) {
  const wrap = document.createElement("section");
  wrap.className = "preview-section";

  const heading = document.createElement("h3");
  heading.className = "preview-section-title";
  heading.textContent = "少样本示例（注入 contexts，不写会话历史）";

  if (!contexts || !contexts.length) {
    const empty = document.createElement("p");
    empty.className = "footnote footnote-top";
    empty.textContent = "（无少样本：没有启用的思维链）";
    wrap.append(heading, empty);
    return wrap;
  }

  wrap.appendChild(heading);
  contexts.forEach((msg) => {
    const role = document.createElement("div");
    role.className = "preview-role";
    role.textContent = msg.role === "user" ? "用户" : "助手";

    const pre = document.createElement("pre");
    pre.className = "snippet";
    pre.textContent = msg.content || "";

    wrap.append(role, pre);
  });
  return wrap;
}

/** 拉取后端拼装结果；不复制前端拼装逻辑，保证所见即所发。 */
async function runPreview() {
  const view = sections.thoughts.exampleView;
  view.previewBtn.disabled = true;
  status("生成预览…");
  try {
    const data = await post("preview", {
      scene: currentScene(),
      draft: {
        rules: sections.rules.items,
        thought_chains: sections.thoughts.items,
        thought_example: readExample(),
      },
    });
    view.body.innerHTML = "";
    view.body.append(
      blockSection("系统提示词末尾追加块", data.system_prompt_block),
      contextsSection(data.contexts),
    );
    view.source.textContent =
      data.source === "draft" ? "按当前草稿预览（未保存）" : "按已保存配置预览";
    status("预览已生成", "ok");
  } catch (err) {
    status("预览失败：" + (err && err.message ? err.message : String(err)), "err");
  } finally {
    view.previewBtn.disabled = false;
  }
}

/** 绑定预览弹窗与本页保存按钮；saveFn 由入口传入，避免反向依赖。 */
export function initExamples(saveFn) {
  const view = sections.thoughts.exampleView;

  view.previewBtn.addEventListener("click", () => {
    view.dialog.showModal();
    runPreview();
  });
  view.saveEl.addEventListener("click", () => saveFn("thoughts", view.saveEl));

  view.close.addEventListener("click", () => view.dialog.close());
  view.done.addEventListener("click", () => view.dialog.close());
  view.scenes.forEach((radio) => {
    radio.addEventListener("change", () => {
      if (view.dialog.open) runPreview();
    });
  });
}
