(function () {
  "use strict";

  var DATA_URL = "data/paper-data.v1.json";
  var CHART_TASKS = ["task1_econ", "task1_finance", "task2_overall", "task3"];
  var DETAIL_TASKS = ["task1_econ", "task1_finance", "task2_overall", "task2_sign_mismatch", "task3"];
  var SCENE_GESTURE_QUIET_MS = 520;
  var SCENE_POST_GESTURE_GUARD_MS = 900;
  var TASK_LABELS = {
    task1_econ: "Task 1 · Economics",
    task1_finance: "Task 1 · Finance",
    task2_overall: "Task 2 · Context shift",
    task2_sign_mismatch: "Task 2 · Sign-switch subset",
    task3: "Task 3 · Misleading evidence"
  };
  var TASK_SHORT = {
    task1_econ: "T1 Econ",
    task1_finance: "T1 Finance",
    task2_overall: "T2",
    task3: "T3"
  };
  var state = {
    data: null,
    previousFocus: null,
    scenePagingLocked: false,
    scenePagingLastInput: 0,
    scenePagingTarget: 0,
    scenePagingCooldownUntil: 0,
    sceneUnlockTimer: null,
  };

  var familyChart = document.getElementById("family-chart");
  var tooltip = document.getElementById("chart-tooltip");
  var dialog = document.getElementById("model-detail-dialog");
  var dialogClose = dialog && dialog.querySelector("[data-dialog-close]");

  function escapeHtml(value) {
    return String(value == null ? "" : value)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;")
      .replace(/'/g, "&#039;");
  }

  function pct(value) {
    var parsed = Number(value);
    if (!Number.isFinite(parsed)) return null;
    return parsed <= 1 ? parsed * 100 : parsed;
  }

  function number(value, digits) {
    var parsed = Number(value);
    return Number.isFinite(parsed) ? parsed.toFixed(digits == null ? 1 : digits) : "—";
  }

  function comma(value) {
    var parsed = Number(value);
    return Number.isFinite(parsed) ? parsed.toLocaleString("en-US") : "—";
  }

  function accessKey(model) {
    return String(model.access || "").toLowerCase().indexOf("closed") >= 0 ? "closed" : "open";
  }

  function accessLabel(model) {
    return accessKey(model) === "closed" ? "Closed-source" : "Open-weight";
  }

  function modelName(model) {
    return model.display_name || model.name || model.id;
  }

  function compactModelName(model) {
    var name = modelName(model);
    var family = String(model.family || "");
    if (family === "OpenAI") return name.replace(/^GPT-/i, "");
    if (family && name.toLowerCase().indexOf(family.toLowerCase()) === 0) {
      return name.slice(family.length).replace(/^[-\s]+/, "") || name;
    }
    return name;
  }

  function scoreFor(model, task, metric) {
    var metrics = model.metrics || model.scores || {};
    var taskData = metrics[task];
    if (!taskData && task === "task2_sign_mismatch") taskData = metrics.task2_mismatch;
    return taskData ? pct(taskData[metric || "accuracy"]) : null;
  }

  function signLabel(sign) {
    var key = String(sign || "").toLowerCase();
    var labels = state.data && state.data.meta && state.data.meta.sign_labels;
    return labels && labels[key] ? labels[key] : key === "positive" ? "+" : key === "negative" ? "−" : key ? key[0].toUpperCase() + key.slice(1) : "—";
  }

  function updateStats(data) {
    var stats = data.stats || {};
    var values = {
      triplets: stats.causal_triplets || stats.triplets,
      papers: stats.source_papers || stats.papers,
      models: stats.evaluated_models || (data.models || []).length
    };
    Object.keys(values).forEach(function (key) {
      var target = document.querySelector('[data-stat="' + key + '"]');
      if (target && values[key] != null) target.textContent = comma(values[key]);
    });
    (data.tasks || []).forEach(function (task) {
      var target = document.querySelector('[data-task-count="' + task.id + '"]');
      if (target) target.textContent = comma(task.instances);
    });
  }

  function familyGroups(models) {
    var groups = [];
    var byName = new Map();
    models.forEach(function (model) {
      var family = model.family || "Other";
      if (!byName.has(family)) {
        var group = { family: family, models: [] };
        byName.set(family, group);
        groups.push(group);
      }
      byName.get(family).models.push(model);
    });
    return groups;
  }

  function chartBar(model, task) {
    var score = scoreFor(model, task, "accuracy");
    var tooltipText = modelName(model) + " · " + TASK_SHORT[task] + " · " + number(score) + "% accuracy";
    return '<i class="accuracy-bar ' + task.replace(/_/g, "-") + '" data-accuracy-bar data-task="' + task + '" ' +
      'data-tooltip="' + escapeHtml(tooltipText) + '" style="--score:' + number(score, 2) + '%" role="meter" ' +
      'aria-label="' + escapeHtml(tooltipText) + '" aria-valuemin="0" aria-valuemax="100" aria-valuenow="' + number(score, 1) + '">' +
      '<em>' + number(score) + '</em></i>';
  }

  function modelCluster(model) {
    var scoreText = CHART_TASKS.map(function (task) {
      return TASK_SHORT[task] + " " + number(scoreFor(model, task, "accuracy")) + "%";
    }).join(", ");
    return '<button class="model-cluster" type="button" data-model-id="' + escapeHtml(model.id) + '" ' +
      'data-tooltip="' + escapeHtml(modelName(model) + " · " + scoreText) + '" ' +
      'aria-label="Open ' + escapeHtml(modelName(model) + " details. " + scoreText) + '">' +
      '<span class="model-bars">' + CHART_TASKS.map(function (task) { return chartBar(model, task); }).join("") + '</span>' +
      '<strong><span class="model-name-full">' + escapeHtml(modelName(model)) + '</span><span class="model-name-short">' + escapeHtml(compactModelName(model)) + '</span></strong>' +
      '<small>' + escapeHtml(accessLabel(model)) + '</small></button>';
  }

  function renderFamilyChart(data) {
    if (!familyChart) return;
    var groups = familyGroups(data.models || []);
    familyChart.innerHTML = groups.map(function (group, index) {
      return '<section class="family-panel" data-family-panel="' + escapeHtml(group.family) + '" data-family-index="' + index + '" ' +
        'style="--model-count:' + group.models.length + '" aria-label="' + escapeHtml(group.family) + ' family, ' + group.models.length + ' models">' +
        '<header><span>' + String(index + 1).padStart(2, "0") + '</span><h3>' + escapeHtml(group.family) + '</h3><p>' + group.models.length + ' model' + (group.models.length === 1 ? '' : 's') + '</p></header>' +
        '<div class="family-models" style="--model-count:' + group.models.length + '">' + group.models.map(modelCluster).join("") + '</div></section>';
    }).join("");
    bindChartInteractions(data.models || []);
  }

  function positionTooltip(event, target) {
    if (!tooltip || tooltip.hidden) return;
    var rect = target.getBoundingClientRect();
    var x = event && Number.isFinite(event.clientX) ? event.clientX + 12 : rect.left + Math.min(rect.width, 170);
    var y = event && Number.isFinite(event.clientY) ? event.clientY + 12 : rect.top - tooltip.offsetHeight - 8;
    tooltip.style.left = Math.max(10, Math.min(x, window.innerWidth - tooltip.offsetWidth - 10)) + "px";
    tooltip.style.top = Math.max(10, Math.min(y, window.innerHeight - tooltip.offsetHeight - 10)) + "px";
  }

  function showTooltip(target, event) {
    if (!tooltip || !target) return;
    tooltip.textContent = target.dataset.tooltip || "";
    tooltip.hidden = false;
    positionTooltip(event, target);
  }

  function hideTooltip() {
    if (tooltip) tooltip.hidden = true;
  }

  function bindChartInteractions(models) {
    var lookup = new Map(models.map(function (model) { return [model.id, model]; }));
    familyChart.querySelectorAll("[data-model-id]").forEach(function (cluster) {
      cluster.addEventListener("click", function () { openModel(lookup.get(cluster.dataset.modelId), cluster); });
      cluster.addEventListener("pointermove", function (event) {
        var bar = event.target.closest("[data-accuracy-bar]");
        showTooltip(bar || cluster, event);
      });
      cluster.addEventListener("pointerleave", hideTooltip);
      cluster.addEventListener("blur", hideTooltip);
    });
  }

  function openModel(model, trigger) {
    if (!model || !dialog) return;
    hideTooltip();
    state.previousFocus = trigger || document.activeElement;
    document.getElementById("model-detail-title").textContent = modelName(model);
    document.getElementById("model-detail-meta").textContent = (model.family || "Model") + " · " + accessLabel(model);
    document.getElementById("model-detail-body").innerHTML = '<div class="scorecard-grid">' + DETAIL_TASKS.map(function (task) {
      var accuracy = scoreFor(model, task, "accuracy");
      var macroF1 = scoreFor(model, task, "macro_f1");
      return '<article class="scorecard"><strong>' + escapeHtml(TASK_LABELS[task]) + '</strong>' +
        '<div class="scorecard-metrics"><span>Accuracy<b>' + number(accuracy) + '</b></span>' +
        '<span>Macro F1<b>' + number(macroF1) + '</b></span></div></article>';
    }).join("") + '</div>';
    if (typeof dialog.showModal === "function") dialog.showModal();
    else { dialog.setAttribute("open", ""); dialog.setAttribute("aria-modal", "true"); }
    window.requestAnimationFrame(function () { dialogClose.focus(); });
  }

  function closeDialog() {
    if (!dialog || !dialog.hasAttribute("open")) return;
    if (typeof dialog.close === "function") dialog.close();
    else dialog.removeAttribute("open");
    if (state.previousFocus && typeof state.previousFocus.focus === "function") state.previousFocus.focus();
  }

  function bindDialog() {
    if (!dialog) return;
    dialogClose.addEventListener("click", closeDialog);
    dialog.addEventListener("click", function (event) { if (event.target === dialog) closeDialog(); });
    dialog.addEventListener("cancel", function () {
      window.setTimeout(function () {
        if (state.previousFocus && typeof state.previousFocus.focus === "function") state.previousFocus.focus();
      }, 0);
    });
    dialog.addEventListener("close", function () {
      window.setTimeout(function () {
        if (state.previousFocus && typeof state.previousFocus.focus === "function") state.previousFocus.focus();
      }, 0);
    });
    document.addEventListener("keydown", function (event) {
      if (event.key === "Escape" && dialog.hasAttribute("open")) closeDialog();
    });
  }

  function renderTransfer(data) {
    var transfer = data.transfer || {};
    var target = document.getElementById("transfer-chart");
    if (target) target.innerHTML = (transfer.groups || []).map(function (group) {
      return '<article class="transfer-row"><strong>' + escapeHtml(group.label) + '</strong><div>' +
        '<span style="--value:' + Number(group.overall_accuracy_pct) + '%">Overall ' + number(group.overall_accuracy_pct) + '</span>' +
        '<span style="--value:' + Number(group.sign_mismatch_accuracy_pct) + '%">Sign-switch ' + number(group.sign_mismatch_accuracy_pct) + '</span>' +
        '</div><b>−' + number(group.drop_pp) + ' pp</b></article>';
    }).join("");
    var distribution = document.getElementById("transfer-distribution");
    if (distribution) distribution.innerHTML = (transfer.prediction_distribution || []).map(function (row) {
      return '<article class="distribution-card"><strong>' + escapeHtml(row.label) + '</strong><div class="stacked-bar" aria-label="' +
        escapeHtml(number(row.correct_pct) + '% correct, ' + number(row.source_sign_error_pct) + '% source-sign error, ' + number(row.other_error_pct) + '% other error') + '">' +
        '<i class="correct" style="width:' + Number(row.correct_pct) + '%"></i>' +
        '<i class="source-error" style="width:' + Number(row.source_sign_error_pct) + '%"></i>' +
        '<i class="other-error" style="width:' + Number(row.other_error_pct) + '%"></i></div>' +
        '<div class="distribution-legend"><span>Correct ' + number(row.correct_pct) + '</span><span>Source cue ' + number(row.source_sign_error_pct) + '</span><span>Other ' + number(row.other_error_pct) + '</span></div></article>';
    }).join("");
  }

  function renderSigns(data) {
    var means = data.sign_accuracy && data.sign_accuracy.mean_across_tasks || {};
    var target = document.getElementById("sign-chart");
    if (!target) return;
    target.innerHTML = ["positive", "negative", "none", "mixed"].map(function (sign) {
      var value = Number(means[sign]);
      return '<div><span>' + escapeHtml(signLabel(sign)) + '</span><i aria-hidden="true"><b style="--value:' + value + '%"></b></i><strong>' + number(value) + '</strong></div>';
    }).join("");
  }

  function bindSceneNavigation() {
    var sections = Array.from(document.querySelectorAll("[data-scene]"));
    var links = Array.from(document.querySelectorAll("[data-scene-link]"));
    if (!("IntersectionObserver" in window)) return;
    var observer = new IntersectionObserver(function (entries) {
      var visible = entries.filter(function (entry) { return entry.isIntersecting; })
        .sort(function (a, b) { return b.intersectionRatio - a.intersectionRatio; })[0];
      if (!visible) return;
      links.forEach(function (link) {
        if (link.dataset.sceneLink === visible.target.dataset.scene) link.setAttribute("aria-current", "step");
        else link.removeAttribute("aria-current");
      });
    }, { rootMargin: "-30% 0px -50%", threshold: [0, 0.2, 0.5, 0.8] });
    sections.forEach(function (section) { observer.observe(section); });
  }

  function bindScenePaging() {
    var scenes = Array.from(document.querySelectorAll("main > .scene"));
    if (!scenes.length) return;

    function headerHeight() {
      var header = document.querySelector(".paper-nav");
      return header ? header.getBoundingClientRect().height : 0;
    }

    function currentSceneIndex() {
      var anchor = headerHeight();
      var closest = 0;
      var distance = Infinity;
      scenes.forEach(function (scene, index) {
        var nextDistance = Math.abs(scene.getBoundingClientRect().top - anchor);
        if (nextDistance < distance) {
          distance = nextDistance;
          closest = index;
        }
      });
      return closest;
    }

    function sceneAtViewport() {
      var probe = document.elementFromPoint(window.innerWidth / 2, Math.min(window.innerHeight - 2, headerHeight() + 12));
      var scene = probe && probe.closest && probe.closest(".scene");
      return scene || scenes[currentSceneIndex()];
    }

    function isFreeScrollScene(scene) {
      return scene && scene.id === "benchmark" && window.matchMedia("(max-width: 900px)").matches;
    }

    function releasePaging() {
      window.scrollTo({ top: state.scenePagingTarget, behavior: "auto" });
      window.requestAnimationFrame(function () {
        window.requestAnimationFrame(function () {
          document.documentElement.classList.remove("scene-paging");
          state.scenePagingLocked = false;
          state.scenePagingCooldownUntil = Math.max(
            state.scenePagingCooldownUntil,
            performance.now() + SCENE_POST_GESTURE_GUARD_MS
          );
        });
      });
    }

    function scheduleRelease() {
      if (state.sceneUnlockTimer) window.clearTimeout(state.sceneUnlockTimer);
      var elapsed = performance.now() - state.scenePagingLastInput;
      state.sceneUnlockTimer = window.setTimeout(releasePaging, Math.max(100, SCENE_GESTURE_QUIET_MS - elapsed));
    }

    function pageTo(index) {
      if (index < 0 || index >= scenes.length) return false;
      state.scenePagingLocked = true;
      state.scenePagingLastInput = performance.now();
      state.scenePagingTarget = Math.max(0, scenes[index].offsetTop - headerHeight());
      document.documentElement.classList.add("scene-paging");
      window.scrollTo({
        top: state.scenePagingTarget,
        behavior: window.matchMedia("(prefers-reduced-motion: reduce)").matches ? "auto" : "smooth"
      });
      scheduleRelease();
      return true;
    }

    window.addEventListener("wheel", function (event) {
      if (event.ctrlKey || Math.abs(event.deltaX) >= Math.abs(event.deltaY) || Math.abs(event.deltaY) < 8) return;
      if (dialog && dialog.hasAttribute("open")) return;
      if (!state.scenePagingLocked && isFreeScrollScene(sceneAtViewport())) return;
      if (state.scenePagingLocked) {
        event.preventDefault();
        state.scenePagingLastInput = performance.now();
        state.scenePagingCooldownUntil = state.scenePagingLastInput + SCENE_POST_GESTURE_GUARD_MS;
        scheduleRelease();
        return;
      }
      if (performance.now() < state.scenePagingCooldownUntil) {
        event.preventDefault();
        state.scenePagingCooldownUntil = performance.now() + SCENE_POST_GESTURE_GUARD_MS;
        return;
      }
      var direction = event.deltaY > 0 ? 1 : -1;
      if (pageTo(currentSceneIndex() + direction)) event.preventDefault();
    }, { passive: false });
  }

  function initializeData(data) {
    state.data = data;
    updateStats(data);
    renderFamilyChart(data);
    renderTransfer(data);
    renderSigns(data);
    document.documentElement.dataset.dataReady = "true";
  }

  function loadData() {
    fetch(DATA_URL, { cache: "no-store" })
      .then(function (response) {
        if (!response.ok) throw new Error("Paper data request failed: " + response.status);
        return response.json();
      })
      .then(initializeData)
      .catch(function () {
        if (familyChart) familyChart.innerHTML = '<p class="empty-state">Interactive data is unavailable. Please use the paper PDF for the complete results.</p>';
        document.documentElement.dataset.dataReady = "false";
      });
  }

  bindDialog();
  bindSceneNavigation();
  bindScenePaging();
  loadData();
}());
