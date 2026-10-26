(() => {
  "use strict";
  const generate = document.getElementById("space-generate");
  const form = document.getElementById("space-restore-form");
  if (!generate || !form) return;
  const codeBox = document.getElementById("space-recovery-code");
  const saveMessage = document.getElementById("space-save-message");
  const restoreMessage = document.getElementById("space-restore-message");
  const restoreInput = document.getElementById("space-restore-code");

  // A private operator handoff can use a URL fragment: it never reaches server logs.
  if (location.hash.startsWith("#restore=")) {
    const code = location.hash.slice(9);
    history.replaceState(null, "", location.pathname);
    if (/^wxspace_[A-Za-z0-9_-]{43}$/.test(code)) {
      restoreInput.value = code;
      restoreMessage.textContent = "已填入恢复码，点击按钮进入你的空间。";
    }
  }

  async function post(path, payload) {
    const response = await fetch(path, {
      method: "POST", credentials: "same-origin",
      headers: {"Content-Type": "application/json"}, body: JSON.stringify(payload),
    });
    const data = await response.json();
    if (!response.ok) throw new Error(typeof data.detail === "string" ? data.detail : "操作失败，请稍后重试");
    return data;
  }

  generate.addEventListener("click", async () => {
    if (generate.dataset.hasRecovery === "true" &&
        !confirm("更换后旧恢复码和其他设备的凭证会失效。确定更换？")) return;
    generate.disabled = true;
    saveMessage.textContent = "正在生成…";
    try {
      const data = await post("/api/v1/space/recovery", {});
      codeBox.value = data.recovery_code;
      document.getElementById("space-code-panel").hidden = false;
      generate.dataset.hasRecovery = "true";
      generate.textContent = "更换恢复码";
      saveMessage.textContent = "恢复码已生成，请复制或下载保存。";
    } catch (error) { saveMessage.textContent = error.message; }
    finally { generate.disabled = false; }
  });

  document.getElementById("space-copy").addEventListener("click", async () => {
    try {
      await navigator.clipboard.writeText(codeBox.value);
      saveMessage.textContent = "已复制，请保存到安全位置。";
    } catch {
      codeBox.focus(); codeBox.select();
      saveMessage.textContent = "请手动复制选中的恢复码。";
    }
  });
  document.getElementById("space-download").addEventListener("click", () => {
    const body = "微信公众号运营助手 · 私人空间恢复码\n\n" + codeBox.value +
      "\n\n打开 " + location.origin + "/space ，输入此码恢复。\n请勿分享；拿到恢复码的人可以访问空间全部内容。\n";
    const url = URL.createObjectURL(new Blob([body], {type: "text/plain;charset=utf-8"}));
    const link = document.createElement("a");
    link.href = url; link.download = "微信运营助手-空间恢复码.txt"; link.click();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  });
  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    const button = form.querySelector("button[type=submit]");
    button.disabled = true;
    restoreMessage.textContent = "正在恢复…";
    try {
      await post("/api/v1/space/restore", {recovery_code: restoreInput.value.trim()});
      restoreInput.value = "";
      location.replace("/tasks");
    } catch (error) {
      restoreMessage.textContent = error.message;
      button.disabled = false;
    }
  });
})();
