const pendingActions = new Set();
let activeDrawer = null;
let previouslyFocused = null;

const focusableSelector = [
  "a[href]",
  "button:not([disabled])",
  "input:not([disabled])",
  "textarea:not([disabled])",
  "select:not([disabled])",
  '[tabindex]:not([tabindex="-1"])'
].join(",");

function setBusy(button, busy, busyLabel) {
  if (!button) return;
  if (busy) {
    button.dataset.originalLabel = button.textContent;
    button.textContent = busyLabel;
    button.disabled = true;
    button.setAttribute("aria-busy", "true");
    return;
  }
  button.textContent = button.dataset.originalLabel || button.textContent;
  button.disabled = false;
  button.removeAttribute("aria-busy");
}

function showToast(message, kind = "success") {
  const region = document.querySelector("#toast-region");
  if (!region) return;
  const toast = document.createElement("div");
  toast.className = `toast${kind === "error" ? " is-error" : ""}`;
  toast.textContent = message;
  region.append(toast);
  window.setTimeout(() => toast.remove(), 4200);
}

async function readPayload(response) {
  const contentType = response.headers.get("content-type") || "";
  if (!contentType.includes("application/json")) return {};
  return response.json();
}

function errorMessage(payload, fallback) {
  if (typeof payload?.detail === "string") return payload.detail;
  if (Array.isArray(payload?.detail)) {
    return payload.detail.map((item) => item.msg || "输入有误").join("；");
  }
  return fallback;
}

function drawerFocusables(drawer) {
  return [...drawer.querySelectorAll(focusableSelector)].filter(
    (node) => node.offsetParent !== null
  );
}

function openDrawer(drawerId, trigger = document.activeElement) {
  const drawer = document.getElementById(drawerId);
  if (!drawer) return;
  if (activeDrawer && activeDrawer !== drawer) closeDrawer(activeDrawer, false);
  previouslyFocused = trigger instanceof HTMLElement ? trigger : null;
  activeDrawer = drawer;
  drawer.setAttribute("aria-hidden", "false");
  document.body.classList.add("has-overlay");
  window.requestAnimationFrame(() => {
    const panel = drawer.querySelector(".drawer-panel");
    const firstField = drawer.querySelector("input:checked, textarea, input, button");
    (firstField || panel)?.focus();
  });
}

function closeDrawer(drawer = activeDrawer, restoreFocus = true) {
  if (!drawer) return;
  drawer.setAttribute("aria-hidden", "true");
  if (drawer === activeDrawer) activeDrawer = null;
  document.body.classList.remove("has-overlay");
  if (restoreFocus) previouslyFocused?.focus();
}

function trapDrawerFocus(event) {
  if (!activeDrawer || event.key !== "Tab") return;
  const nodes = drawerFocusables(activeDrawer);
  if (!nodes.length) return;
  const first = nodes[0];
  const last = nodes[nodes.length - 1];
  if (event.shiftKey && document.activeElement === first) {
    event.preventDefault();
    last.focus();
  } else if (!event.shiftKey && document.activeElement === last) {
    event.preventDefault();
    first.focus();
  }
}

document.addEventListener("click", (event) => {
  const opener = event.target.closest("[data-open-drawer]");
  if (opener) {
    openDrawer(opener.dataset.openDrawer, opener);
    return;
  }
  if (event.target.closest("[data-close-drawer]")) closeDrawer();
});

document.addEventListener("keydown", (event) => {
  if (event.key === "Escape" && activeDrawer) {
    event.preventDefault();
    closeDrawer();
    return;
  }
  trapDrawerFocus(event);
});

const taskForm = document.querySelector("#task-form");
const requestField = document.querySelector("#request");
const modePlaceholders = {
  fixed_topic: "例如：面向有 Python 基础的开发者，解释 Agent 工程中的恢复机制",
  data_driven_article: "例如：根据近 30 天数据，找出值得继续深挖的选题并生成文章",
  weekly_plan: "例如：为开发者 Agent 账号规划下周 5 篇内容，兼顾增长与专业深度"
};

taskForm?.addEventListener("change", (event) => {
  if (event.target.name === "mode" && requestField) {
    requestField.placeholder = modePlaceholders[event.target.value] || "";
  }
});

taskForm?.addEventListener("submit", async (event) => {
  event.preventDefault();
  if (pendingActions.has("create-task")) return;
  const submit = taskForm.querySelector('button[type="submit"]');
  const errorNode = taskForm.querySelector("[data-form-error]");
  const data = new FormData(taskForm);
  const mode = data.get("mode");
  const request = String(data.get("request") || "").trim();
  errorNode.textContent = "";

  if (request.length < 3) {
    errorNode.textContent = "请至少输入 3 个字，说明本次要解决的内容问题。";
    requestField?.focus();
    return;
  }

  pendingActions.add("create-task");
  setBusy(submit, true, "正在创建…");
  try {
    const response = await fetch("/api/v1/tasks", {
      method: "POST",
      headers: {"Content-Type": "application/json"},
      body: JSON.stringify({
        mode,
        request,
        topic: mode === "fixed_topic" ? request : null
      })
    });
    const payload = await readPayload(response);
    if (!response.ok) throw new Error(errorMessage(payload, "创建任务失败"));
    showToast("内容任务已创建");
    closeDrawer();
    window.setTimeout(() => window.location.reload(), 500);
  } catch (error) {
    errorNode.textContent = error.message || "创建任务失败，请稍后重试。";
  } finally {
    pendingActions.delete("create-task");
    setBusy(submit, false);
  }
});

const metricsFile = document.querySelector("#metrics-file");
const selectedFile = document.querySelector("#selected-file");
metricsFile?.addEventListener("change", () => {
  selectedFile.textContent = metricsFile.files?.[0]?.name || "尚未选择文件";
});

const importForm = document.querySelector("#import-form");
importForm?.addEventListener("submit", async (event) => {
  event.preventDefault();
  if (pendingActions.has("import-metrics")) return;
  const submit = importForm.querySelector('button[type="submit"]');
  const errorNode = importForm.querySelector("[data-form-error]");
  const file = metricsFile?.files?.[0];
  errorNode.textContent = "";

  if (!file) {
    errorNode.textContent = "请先选择 CSV 或 XLSX 数据文件。";
    metricsFile?.focus();
    return;
  }

  pendingActions.add("import-metrics");
  setBusy(submit, true, "正在导入…");
  try {
    const body = new FormData();
    body.append("file", file);
    const response = await fetch("/api/v1/metrics/import", {method: "POST", body});
    const payload = await readPayload(response);
    if (!response.ok) throw new Error(errorMessage(payload, "导入数据失败"));
    showToast(`已导入 ${payload.imported ?? 0} 条运营记录`);
    closeDrawer();
    window.setTimeout(() => window.location.reload(), 650);
  } catch (error) {
    errorNode.textContent = error.message || "导入数据失败，请检查文件格式。";
  } finally {
    pendingActions.delete("import-metrics");
    setBusy(submit, false);
  }
});

document.querySelectorAll("[data-task-run]").forEach((button) => {
  button.addEventListener("click", async () => {
    const taskId = button.dataset.taskId;
    const actionKey = `run:${taskId}`;
    if (!taskId || pendingActions.has(actionKey)) return;
    pendingActions.add(actionKey);
    setBusy(button, true, "运行中…");
    try {
      const response = await fetch(`/api/v1/tasks/${encodeURIComponent(taskId)}/run`, {
        method: "POST"
      });
      const payload = await readPayload(response);
      if (!response.ok) throw new Error(errorMessage(payload, "任务运行失败"));
      showToast("任务已完成本轮运行");
      window.setTimeout(() => window.location.reload(), 500);
    } catch (error) {
      showToast(error.message || "任务运行失败，请稍后重试。", "error");
      setBusy(button, false);
      pendingActions.delete(actionKey);
    }
  });
});

document.querySelectorAll("[data-task-delete]").forEach((button) => {
  button.addEventListener("click", async () => {
    const taskId = button.dataset.taskId;
    if (!taskId || !window.confirm("确认删除此任务及本地产物？微信端内容不会被删除。")) {
      return;
    }
    const actionKey = `delete:${taskId}`;
    if (pendingActions.has(actionKey)) return;
    pendingActions.add(actionKey);
    setBusy(button, true, "删除中…");
    try {
      const response = await fetch(`/api/v1/tasks/${encodeURIComponent(taskId)}`, {
        method: "DELETE"
      });
      const payload = await readPayload(response);
      if (!response.ok) throw new Error(errorMessage(payload, "删除任务失败"));
      showToast("任务已删除");
      window.setTimeout(() => window.location.reload(), 300);
    } catch (error) {
      showToast(error.message || "删除任务失败，请稍后重试。", "error");
      setBusy(button, false);
      pendingActions.delete(actionKey);
    }
  });
});

const previewDialog = document.querySelector("#preview-dialog");
const previewFrame = document.querySelector("#preview-frame");

document.querySelectorAll("[data-task-preview]").forEach((button) => {
  button.addEventListener("click", async () => {
    const taskId = button.dataset.taskId;
    const actionKey = `preview:${taskId}`;
    if (!taskId || pendingActions.has(actionKey)) return;
    pendingActions.add(actionKey);
    setBusy(button, true, "读取中…");
    try {
      const response = await fetch(
        `/api/v1/tasks/${encodeURIComponent(taskId)}/preview`
      );
      const payload = await readPayload(response);
      if (!response.ok) throw new Error(errorMessage(payload, "暂时无法读取预览"));
      previewFrame.srcdoc = payload.html || "<p>暂无可预览内容</p>";
      previewDialog.showModal();
    } catch (error) {
      showToast(error.message || "暂时无法读取预览。", "error");
    } finally {
      pendingActions.delete(actionKey);
      setBusy(button, false);
    }
  });
});

document.querySelector("[data-close-preview]")?.addEventListener("click", () => {
  previewDialog?.close();
});

previewDialog?.addEventListener("click", (event) => {
  if (event.target === previewDialog) previewDialog.close();
});

const titleDialog = document.querySelector("#title-dialog");
const titleCandidates = document.querySelector("#title-candidates");

function renderTitleCandidates(taskId, proposal) {
  titleCandidates.textContent = "";
  const candidates = proposal?.candidates || [];
  if (!candidates.length) {
    showToast("没有生成标题候选", "error");
    return;
  }
  for (const candidate of candidates) {
    const card = document.createElement("button");
    card.type = "button";
    card.className = "title-candidate";
    const title = document.createElement("strong");
    title.textContent = candidate.title;
    const rationale = document.createElement("small");
    rationale.textContent = candidate.rationale || "";
    card.append(title, rationale);
    card.addEventListener("click", async () => {
      const actionKey = `choose-title:${taskId}`;
      if (pendingActions.has(actionKey)) return;
      pendingActions.add(actionKey);
      card.disabled = true;
      try {
        const choose = await fetch(
          `/api/v1/tasks/${encodeURIComponent(taskId)}/choose-title`,
          {
            method: "POST",
            headers: {"Content-Type": "application/json"},
            body: JSON.stringify({title: candidate.title})
          }
        );
        const payload = await readPayload(choose);
        if (!choose.ok) throw new Error(errorMessage(payload, "保存标题失败"));
        showToast("标题已选定");
        titleDialog.close();
        window.setTimeout(() => window.location.reload(), 500);
      } catch (error) {
        showToast(error.message || "保存标题失败。", "error");
        card.disabled = false;
      } finally {
        pendingActions.delete(actionKey);
      }
    });
    titleCandidates.append(card);
  }
}

document.querySelectorAll("[data-propose-titles]").forEach((button) => {
  button.addEventListener("click", async () => {
    const taskId = button.dataset.taskId;
    const actionKey = `titles:${taskId}`;
    if (!taskId || pendingActions.has(actionKey)) return;
    pendingActions.add(actionKey);
    setBusy(button, true, "生成中…");
    try {
      const response = await fetch(
        `/api/v1/tasks/${encodeURIComponent(taskId)}/propose-titles`,
        {method: "POST"}
      );
      const payload = await readPayload(response);
      if (!response.ok) throw new Error(errorMessage(payload, "标题生成失败"));
      renderTitleCandidates(taskId, payload);
      titleDialog.showModal();
    } catch (error) {
      showToast(error.message || "标题生成失败，请稍后重试。", "error");
    } finally {
      pendingActions.delete(actionKey);
      setBusy(button, false);
    }
  });
});

document.querySelector("[data-close-title]")?.addEventListener("click", () => {
  titleDialog?.close();
});

titleDialog?.addEventListener("click", (event) => {
  if (event.target === titleDialog) titleDialog.close();
});

const pushDraftDialog = document.querySelector("#push-draft-dialog");
const pushDraftCover = document.querySelector("#push-draft-cover");
const pushDraftFileName = document.querySelector("#push-draft-file-name");
const pushDraftMediaId = document.querySelector("#push-draft-media-id");
const pushDraftError = document.querySelector("[data-push-draft-error]");
let pushDraftTaskId = null;

document.querySelectorAll("[data-push-draft]").forEach((button) => {
  button.addEventListener("click", () => {
    pushDraftTaskId = button.dataset.taskId;
    if (pushDraftCover) pushDraftCover.value = "";
    if (pushDraftMediaId) pushDraftMediaId.value = "";
    if (pushDraftFileName) pushDraftFileName.textContent = "未选择文件";
    if (pushDraftError) pushDraftError.textContent = "";
    pushDraftDialog?.showModal();
  });
});

pushDraftCover?.addEventListener("change", () => {
  if (pushDraftFileName) {
    pushDraftFileName.textContent = pushDraftCover.files?.[0]?.name || "未选择文件";
  }
  if (pushDraftError) pushDraftError.textContent = "";
});

document.querySelectorAll("[data-close-push-draft]").forEach((button) => {
  button.addEventListener("click", () => pushDraftDialog?.close());
});

pushDraftDialog?.addEventListener("click", (event) => {
  if (event.target === pushDraftDialog) pushDraftDialog.close();
});

document.querySelector("[data-confirm-push-draft]")?.addEventListener("click", async (event) => {
  const taskId = pushDraftTaskId;
  const actionKey = `push-draft:${taskId}`;
  const confirm = event.currentTarget;
  if (!taskId || pendingActions.has(actionKey)) return;
  pendingActions.add(actionKey);
  setBusy(confirm, true, "推送中…");
  if (pushDraftError) pushDraftError.textContent = "";
  try {
    let thumbMediaId = pushDraftMediaId?.value.trim() || "";
    const coverFile = pushDraftCover?.files?.[0];
    if (coverFile) {
      const body = new FormData();
      body.append("file", coverFile);
      const upload = await fetch("/api/v1/media/cover", {method: "POST", body});
      const uploadPayload = await readPayload(upload);
      if (!upload.ok) throw new Error(errorMessage(uploadPayload, "封面上传失败"));
      thumbMediaId = uploadPayload.media_id || "";
    }
    if (!thumbMediaId) {
      throw new Error("请选择封面图片或填写封面素材编号。");
    }
    const response = await fetch(
      `/api/v1/tasks/${encodeURIComponent(taskId)}/push-draft`,
      {
        method: "POST",
        headers: {"Content-Type": "application/json"},
        body: JSON.stringify({thumb_media_id: thumbMediaId})
      }
    );
    const payload = await readPayload(response);
    if (!response.ok) throw new Error(errorMessage(payload, "推送到草稿箱失败"));
    showToast("已写入微信草稿箱");
    pushDraftDialog?.close();
    window.setTimeout(() => window.location.reload(), 500);
  } catch (error) {
    if (pushDraftError) {
      pushDraftError.textContent = error.message || "推送到草稿箱失败，请稍后重试。";
    }
  } finally {
    pendingActions.delete(actionKey);
    setBusy(confirm, false);
  }
});

document.querySelectorAll("[data-create-plan-task]").forEach((button) => {
  button.addEventListener("click", async () => {
    const planId = button.dataset.planId;
    const topic = button.dataset.topic;
    const purpose = button.dataset.purpose || topic;
    const actionKey = `plan-task:${topic}`;
    if (!planId || !topic || pendingActions.has(actionKey)) return;
    pendingActions.add(actionKey);
    setBusy(button, true, "创建中…");
    try {
      const response = await fetch("/api/v1/tasks", {
        method: "POST",
        headers: {"Content-Type": "application/json"},
        body: JSON.stringify({
          mode: "fixed_topic",
          topic,
          request: purpose,
          plan_id: planId
        })
      });
      const payload = await readPayload(response);
      if (!response.ok) throw new Error(errorMessage(payload, "创建任务失败"));
      showToast("已建任务，可到「内容任务」运行");
      window.setTimeout(() => window.location.reload(), 500);
    } catch (error) {
      showToast(error.message || "创建任务失败。", "error");
      setBusy(button, false);
      pendingActions.delete(actionKey);
    }
  });
});

const reviewDataNode = document.querySelector("#review-data");
const reviewFrame = document.querySelector("#review-frame");
const reviewMarkdown = document.querySelector("#review-markdown");

if (reviewDataNode && reviewMarkdown) {
  let reviewData = {};
  try {
    reviewData = JSON.parse(reviewDataNode.textContent) || {};
  } catch (_) {
    reviewData = {};
  }
  if (reviewFrame && reviewData.html) {
    reviewFrame.srcdoc = reviewData.html || "<p>暂无可预览内容</p>";
  }
  reviewMarkdown.value = reviewData.final_markdown || "";

  const saveButton = document.querySelector("#save-final");
  const markReviewedButton = document.querySelector("#mark-reviewed");
  const repurposeButton = document.querySelector("#repurpose");
  const diffBox = document.querySelector("#diff-box");
  const diffSummary = document.querySelector("#diff-summary");
  const diffList = document.querySelector("#diff-list");

  function renderDiff(diff) {
    if (!diffBox) return;
    diffBox.hidden = false;
    const parts = [];
    if (diff.title_changed) parts.push("标题已修改");
    if (diff.deleted_paragraph_count) parts.push(`删除或重写 ${diff.deleted_paragraph_count} 段`);
    if (diff.added_paragraph_count) parts.push(`新增 ${diff.added_paragraph_count} 段`);
    parts.push(`整体改写率 ${(diff.replacement_rate * 100).toFixed(1)}%`);
    diffSummary.textContent = parts.join(" · ");
    diffList.textContent = "";
    const rules = diff.reusable_rules || [];
    if (!rules.length) rules.push("未提取到可复用改写规则");
    rules.forEach((rule) => {
      const item = document.createElement("li");
      item.textContent = rule;
      diffList.append(item);
    });
  }

  saveButton?.addEventListener("click", async () => {
    const actionKey = "save-final";
    if (pendingActions.has(actionKey)) return;
    pendingActions.add(actionKey);
    setBusy(saveButton, true, "保存中…");
    try {
      const response = await fetch(
        `/api/v1/articles/${encodeURIComponent(saveButton.dataset.taskId)}/final-version`,
        {
          method: "POST",
          headers: {"Content-Type": "application/json"},
          body: JSON.stringify({
            generated_markdown: reviewData.generated_markdown || "",
            final_markdown: reviewMarkdown.value
          })
        }
      );
      const payload = await readPayload(response);
      if (!response.ok) throw new Error(errorMessage(payload, "保存终稿失败"));
      renderDiff(payload);
      showToast("终稿已保存，差异已计算");
    } catch (error) {
      showToast(error.message || "保存终稿失败。", "error");
    } finally {
      pendingActions.delete(actionKey);
      setBusy(saveButton, false);
    }
  });

  markReviewedButton?.addEventListener("click", async () => {
    const actionKey = "mark-reviewed";
    if (pendingActions.has(actionKey)) return;
    pendingActions.add(actionKey);
    setBusy(markReviewedButton, true, "提交中…");
    try {
      const response = await fetch(
        `/api/v1/articles/${encodeURIComponent(markReviewedButton.dataset.taskId)}/mark-reviewed`,
        {method: "POST"}
      );
      const payload = await readPayload(response);
      if (!response.ok) throw new Error(errorMessage(payload, "标记失败"));
      showToast("已标记人工审阅完成");
      window.setTimeout(() => window.location.reload(), 600);
    } catch (error) {
      showToast(error.message || "标记失败。", "error");
      setBusy(markReviewedButton, false);
      pendingActions.delete(actionKey);
    }
  });

  repurposeButton?.addEventListener("click", async () => {
    const actionKey = "repurpose";
    if (pendingActions.has(actionKey)) return;
    pendingActions.add(actionKey);
    setBusy(repurposeButton, true, "生成中…");
    try {
      const response = await fetch(
        `/api/v1/articles/${encodeURIComponent(repurposeButton.dataset.taskId)}/repurpose`,
        {method: "POST"}
      );
      const payload = await readPayload(response);
      if (!response.ok) throw new Error(errorMessage(payload, "内容复用生成失败"));
      renderRepurpose(payload);
    } catch (error) {
      showToast(error.message || "内容复用失败。", "error");
    } finally {
      pendingActions.delete(actionKey);
      setBusy(repurposeButton, false);
    }
  });
}

function renderRepurpose(content) {
  const panel = document.querySelector("#repurpose-panel");
  const box = document.querySelector("#repurpose-content");
  if (!panel || !box) return;
  panel.hidden = false;
  box.textContent = "";
  const blocks = [
    ["视频号脚本", content.video_script],
    ["小红书文案", content.xiaohongshu_post],
    ["朋友圈转发语", content.moments_blurb]
  ];
  for (const [label, text] of blocks) {
    const card = document.createElement("div");
    card.className = "repurpose-card";
    const head = document.createElement("h3");
    head.textContent = label;
    const pre = document.createElement("pre");
    pre.textContent = text || "";
    card.append(head, pre);
    box.append(card);
  }
}

/* Safe GenUI: data-only components, rendered with DOM APIs (never innerHTML). */
function genuiElement(node) {
  const type = node?.type || "text";
  if (type === "divider") return document.createElement("hr");
  const element = document.createElement(type === "action" ? "button" : "article");
  element.className = `genui-node is-${type} tone-${node?.tone || "neutral"}`;
  if (type === "action") {
    element.type = "button";
    element.textContent = node.label || "继续操作";
    const allowed = new Set(["open_review", "copy_article", "show_sources", "show_quality"]);
    if (!allowed.has(node.action)) element.disabled = true;
    element.addEventListener("click", async () => {
      if (node.action === "copy_article") {
        await navigator.clipboard.writeText(reviewMarkdown?.value || "");
        showToast("文章终稿已复制");
      } else if (node.action === "open_review") {
        reviewMarkdown?.focus();
      } else if (node.action === "show_sources") {
        reviewFrame?.scrollIntoView({behavior: "smooth", block: "center"});
      } else if (node.action === "show_quality") {
        document.querySelector("#genui-stage")?.scrollIntoView({behavior: "smooth"});
      }
    });
    return element;
  }
  if (node.title) {
    const title = document.createElement("h3");
    title.textContent = node.title;
    element.append(title);
  }
  if (type === "metric") {
    const value = document.createElement("strong");
    value.textContent = node.value || "—";
    const label = document.createElement("small");
    label.textContent = node.label || "指标";
    element.append(value, label);
  } else if (type === "check") {
    const marker = document.createElement("span");
    marker.className = "genui-check-marker";
    marker.textContent = node.checked ? "✓" : "·";
    const label = document.createElement("span");
    label.textContent = node.label || "检查项";
    element.append(marker, label);
  } else if (node.content || node.label) {
    const copy = document.createElement("p");
    copy.textContent = node.content || node.label;
    element.append(copy);
  }
  for (const child of node.items || []) element.append(genuiElement(child));
  return element;
}

async function loadGenui() {
  const stage = document.querySelector("[data-genui-task]");
  const canvas = document.querySelector("#genui-canvas");
  if (!stage || !canvas) return;
  try {
    const response = await fetch(
      `/api/v1/tasks/${encodeURIComponent(stage.dataset.genuiTask)}/genui`
    );
    if (!response.ok) return;
    const documentSpec = await response.json();
    canvas.textContent = "";
    const intro = document.createElement("header");
    intro.className = "genui-intro";
    const title = document.createElement("h2");
    title.textContent = documentSpec.title;
    intro.append(title);
    if (documentSpec.summary) {
      const summary = document.createElement("p");
      summary.textContent = documentSpec.summary;
      intro.append(summary);
    }
    canvas.append(intro);
    for (const node of documentSpec.nodes || []) canvas.append(genuiElement(node));
    stage.hidden = false;
  } catch (_) {
    stage.hidden = true;
  }
}

/* ------------------------------------------------------------------ *
 * Task step timeline (live progress, like Codex / Claude Code)
 * ------------------------------------------------------------------ */

function formatDuration(ms) {
  if (ms == null) return "";
  if (ms < 1000) return `${ms}ms`;
  return `${(ms / 1000).toFixed(1)}s`;
}

function renderSteps(box, report) {
  box.hidden = false;
  box.textContent = "";
  const running = report.status === "running";
  const head = document.createElement("div");
  head.className = "steps-head";
  head.textContent = running
    ? "正在运行，执行详情："
    : `本轮运行完成，共 ${report.steps.length} 步 · 总耗时 ${formatDuration(report.total_duration_ms)}`;
  box.append(head);
  const list = document.createElement("ol");
  list.className = "steps-list";
  for (const step of report.steps) {
    const item = document.createElement("li");
    item.className = `step-row is-${step.status}`;
    const dot = document.createElement("span");
    dot.className = "step-dot";
    dot.setAttribute("aria-hidden", "true");
    dot.textContent = step.status === "running" ? "…" : step.status === "done" ? "✓" : "✗";
    const copy = document.createElement("span");
    copy.className = "step-copy";
    const label = document.createElement("strong");
    label.textContent = step.label || step.node;
    copy.append(label);
    if (step.message) {
      const message = document.createElement("small");
      message.textContent = step.message;
      copy.append(message);
    }
    item.append(dot, copy);
    const time = document.createElement("time");
    time.textContent = step.status === "running" ? "进行中" : formatDuration(step.duration_ms);
    item.append(time);
    list.append(item);
  }
  box.append(list);
  if (!running) {
    const note = document.createElement("p");
    note.className = "steps-done";
    note.textContent = "本轮运行已结束，页面即将刷新以展示最新产物。";
    box.append(note);
    window.setTimeout(() => window.location.reload(), 1800);
  }
}

function pollTaskSteps() {
  document.querySelectorAll("[data-task-steps]").forEach((box) => {
    const taskId = box.dataset.taskSteps;
    if (!taskId) return;
    const poll = async () => {
      try {
        const response = await fetch(`/api/v1/tasks/${encodeURIComponent(taskId)}/steps`);
        if (!response.ok) {
          box.hidden = true;
          return;
        }
        const report = await response.json();
        if (report.status === "running") {
          renderSteps(box, report);
          window.setTimeout(poll, 2000);
        } else {
          renderSteps(box, report);
        }
      } catch (_) {
        box.hidden = true;
      }
    };
    poll();
  });
}

/* ------------------------------------------------------------------ *
 * Skills registry (Agent 能力页)
 * ------------------------------------------------------------------ */

document.querySelectorAll("[data-skill-toggle]").forEach((button) => {
  button.addEventListener("click", async () => {
    const name = button.dataset.skillName;
    const enabled = button.dataset.skillEnabled !== "1";
    const actionKey = `skill:${name}`;
    if (!name || pendingActions.has(actionKey)) return;
    pendingActions.add(actionKey);
    button.disabled = true;
    try {
      const response = await fetch(`/api/v1/skills/${encodeURIComponent(name)}`, {
        method: "PATCH",
        headers: {"Content-Type": "application/json"},
        body: JSON.stringify({enabled})
      });
      const payload = await readPayload(response);
      if (!response.ok) throw new Error(errorMessage(payload, "切换失败"));
      button.dataset.skillEnabled = enabled ? "1" : "0";
      button.classList.toggle("is-on", enabled);
      button.setAttribute("aria-pressed", String(enabled));
      button.querySelector(".switch-label").textContent = enabled ? "已启用" : "已停用";
      showToast(`Skill「${payload.title}」已${enabled ? "启用" : "停用"}，下次运行任务生效`);
    } catch (error) {
      showToast(error.message || "切换失败，请稍后重试。", "error");
    } finally {
      button.disabled = false;
      pendingActions.delete(actionKey);
    }
  });
});

/* ------------------------------------------------------------------ *
 * MCP servers (Agent 能力页)
 * ------------------------------------------------------------------ */

function mcpRow(name) {
  return document.querySelector(`[data-mcp-row="${CSS.escape(name)}"]`);
}

function setMcpSwitch(button, enabled) {
  button.dataset.mcpEnabled = enabled ? "1" : "0";
  button.classList.toggle("is-on", enabled);
  button.setAttribute("aria-pressed", String(enabled));
  button.querySelector(".switch-label").textContent = enabled ? "已启用" : "已停用";
}

async function mcpProbe(name) {
  const row = mcpRow(name);
  const probeButton = row?.querySelector("[data-mcp-probe]");
  const actionKey = `mcp-probe:${name}`;
  if (pendingActions.has(actionKey)) return;
  pendingActions.add(actionKey);
  if (probeButton) setBusy(probeButton, true, "探测中…");
  try {
    const response = await fetch(`/api/v1/mcp/servers/${encodeURIComponent(name)}/probe`, {
      method: "POST"
    });
    const payload = await readPayload(response);
    if (!response.ok) throw new Error(errorMessage(payload, "探测失败"));
    const count = (payload.tools || []).length;
    showToast(`MCP「${name}」${payload.status === "available" ? `已连接，${count} 个工具` : "不可用"}`);
    window.setTimeout(() => window.location.reload(), 800);
  } catch (error) {
    showToast(error.message || "探测失败。", "error");
  } finally {
    if (probeButton) setBusy(probeButton, false);
    pendingActions.delete(actionKey);
  }
}

document.querySelectorAll("[data-mcp-probe]").forEach((button) => {
  button.addEventListener("click", () => mcpProbe(button.dataset.mcpName));
});

document.querySelector("#mcp-probe-all")?.addEventListener("click", async () => {
  const names = [...document.querySelectorAll("[data-mcp-probe]")].map(
    (button) => button.dataset.mcpName
  );
  for (const name of names) {
    await mcpProbe(name);
  }
});

document.querySelectorAll("[data-mcp-toggle]").forEach((button) => {
  button.addEventListener("click", async () => {
    const name = button.dataset.mcpName;
    const enabled = button.dataset.mcpEnabled !== "1";
    const actionKey = `mcp-toggle:${name}`;
    if (!name || pendingActions.has(actionKey)) return;
    pendingActions.add(actionKey);
    button.disabled = true;
    try {
      const response = await fetch(`/api/v1/mcp/servers/${encodeURIComponent(name)}`, {
        method: "PATCH",
        headers: {"Content-Type": "application/json"},
        body: JSON.stringify({enabled})
      });
      const payload = await readPayload(response);
      if (!response.ok) throw new Error(errorMessage(payload, "切换失败"));
      setMcpSwitch(button, enabled);
      showToast(`MCP 服务器「${payload.name}」已${enabled ? "启用" : "停用"}`);
    } catch (error) {
      showToast(error.message || "切换失败。", "error");
    } finally {
      button.disabled = false;
      pendingActions.delete(actionKey);
    }
  });
});

const mcpToolsDialog = document.querySelector("#mcp-tools-dialog");
const mcpToolsBody = document.querySelector("#mcp-tools-body");

document.querySelectorAll("[data-mcp-tools]").forEach((button) => {
  button.addEventListener("click", async () => {
    const name = button.dataset.mcpName;
    const actionKey = `mcp-tools:${name}`;
    if (!name || pendingActions.has(actionKey)) return;
    pendingActions.add(actionKey);
    setBusy(button, true, "读取中…");
    try {
      const response = await fetch(`/api/v1/mcp/servers/${encodeURIComponent(name)}/tools`);
      const payload = await readPayload(response);
      if (!response.ok) throw new Error(errorMessage(payload, "读取工具失败"));
      renderMcpTools(name, payload.tools || []);
      mcpToolsDialog?.showModal();
    } catch (error) {
      showToast(error.message || "读取工具列表失败。", "error");
    } finally {
      setBusy(button, false);
      pendingActions.delete(actionKey);
    }
  });
});

function renderMcpTools(name, tools) {
  if (!mcpToolsBody) return;
  mcpToolsBody.textContent = "";
  if (!tools.length) {
    const empty = document.createElement("p");
    empty.className = "page-summary";
    empty.textContent = "该服务器没有暴露任何工具。";
    mcpToolsBody.append(empty);
    return;
  }
  const heading = document.createElement("p");
  heading.className = "page-summary";
  heading.textContent = `${name} 暴露了 ${tools.length} 个工具（只读展示，调用请使用 API）。`;
  mcpToolsBody.append(heading);
  const list = document.createElement("div");
  list.className = "mcp-tools-list";
  for (const tool of tools) {
    const card = document.createElement("article");
    card.className = "mcp-tool-card";
    const title = document.createElement("h3");
    title.textContent = tool.name || "未命名工具";
    card.append(title);
    if (tool.description) {
      const description = document.createElement("p");
      description.textContent = tool.description;
      card.append(description);
    }
    list.append(card);
  }
  mcpToolsBody.append(list);
}

document.querySelectorAll("[data-close-mcp-tools]").forEach((button) => {
  button.addEventListener("click", () => mcpToolsDialog?.close());
});

mcpToolsDialog?.addEventListener("click", (event) => {
  if (event.target === mcpToolsDialog) mcpToolsDialog.close();
});

pollTaskSteps();
loadGenui();
