/** 确认框：全站唯一实现，调用方拿到 Promise<boolean>。 */

const els = {
  confirmOverlay: document.getElementById("confirm-overlay"),
  confirmText: document.getElementById("confirm-text"),
  confirmOk: document.getElementById("confirm-ok"),
  confirmCancel: document.getElementById("confirm-cancel"),
};

export function askConfirm(message, okLabel = "删除") {
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
