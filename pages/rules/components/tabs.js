/** Tab 切换：面板显隐与工具栏按钮组切换。 */

export function initTabs(onSwitch) {
  document.querySelectorAll(".tab").forEach((tab) => {
    tab.addEventListener("click", () => {
      const target = tab.dataset.tab;

      document.querySelectorAll(".tab").forEach((t) => {
        const on = t === tab;
        t.classList.toggle("is-active", on);
        t.setAttribute("aria-selected", on ? "true" : "false");
      });

      document.querySelectorAll(".tab-panel").forEach((panel) => {
        panel.classList.toggle("is-active", panel.dataset.panel === target);
      });

      document.querySelectorAll(".toolbar-actions").forEach((group) => {
        group.hidden = group.dataset.for !== target;
      });

      if (onSwitch) onSwitch(target);
    });
  });
}