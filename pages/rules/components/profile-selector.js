/** 档案下拉：加载档案列表，并在切换前确认丢弃未保存的草稿。 */

import { get, setProfile, getProfile } from "../utils/bridge.js";
import { state } from "../utils/model.js";
import { askConfirm } from "./confirm-dialog.js";

const els = {
  profileSelect: document.getElementById("profile-select"),
};

/** 由入口注入重新加载配置的回调，避免与入口循环依赖。 */
let loadFn = async () => {};

/** 绑定下拉事件；load 为档案切换后重新加载配置的回调。 */
export function initProfileSelector(load) {
  loadFn = load;
  els.profileSelect.addEventListener("change", (e) => {
    switchProfile(e.target.value);
  });
}

/** 拉取档案列表并填充下拉框，默认选中第一个。 */
export async function loadProfiles() {
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
  await loadFn();
}
