/** 与 AstrBot 插件页桥接的薄封装。 */

export const bridge = window.AstrBotPluginView || window.AstrBotPluginPage;

/** 当前配置文件 key，由入口加载配置文件列表后写入。 */
let currentProfile = "";

export function setProfile(key) {
  currentProfile = key || "";
}

export function getProfile() {
  return currentProfile;
}

/** 剥掉桥接层可能包的 { data: ... } 外壳。 */
export function unwrap(payload) {
  if (payload && typeof payload === "object" && "data" in payload) return payload.data;
  return payload;
}

/** 调接口并解包；data.ok === false 时抛出业务错误。 */
export async function post(route, body = {}) {
  const payload = { ...body, profile: currentProfile };
  const data = unwrap(await bridge.apiPost(route, payload)) || {};
  if (data.ok === false) throw new Error(data.error || "请求被拒绝");
  return data;
}

export async function get(route, params = {}) {
  return unwrap(await bridge.apiGet(route, params)) || {};
}
