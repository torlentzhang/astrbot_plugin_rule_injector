/** 与业务无关的通用工具。 */

/** 生成 8 位随机 id，仅用于前端临时标识。 */
export function newId() {
  return Math.random().toString(16).slice(2, 10);
}

/** 把正文压成单行摘要，供列表预览。 */
export function preview(content) {
  const flat = (content || "").replace(/\s+/g, " ").trim();
  return flat || "（内容为空）";
}

/** 生成「N 字」的小标签节点。 */
export function sizeNode(content) {
  const span = document.createElement("span");
  span.textContent = `${(content || "").length} 字`;
  return span;
}
