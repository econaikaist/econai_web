(function () {
  "use strict";

  var DATA_URL = "data/paper-data.v1.json";
  var TASK_ORDER = ["task2_overall", "task2_sign_mismatch", "task1_econ", "task1_finance", "task3"];
  var TASK_LABELS = {
    task1_econ: "Task 1 · Economics",
    task1_finance: "Task 1 · Finance",
    task2_overall: "Task 2 · Overall",
    task2_sign_mismatch: "Task 2 · Sign-switch",
    task3: "Task 3 · Misleading evidence"
  };
  var state = {
    data: null,
    task: "task2_overall",
    metric: "accuracy",
    access: "all",
    family: "all",
    exampleIndex: 0,
    guess: null,
    previousFocus: null
  };

  var body = document.body;
  var contextLab = document.getElementById("context-lab");
  var modelChart = document.getElementById("model-chart");
  var chartStatus = document.getElementById("model-chart-status");
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
    var number = Number(value);
    if (!Number.isFinite(number)) return null;
    return number <= 1 ? number * 100 : number;
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
    return accessKey(model) === "closed" ? "Closed-source" : "Open-source";
  }

  function modelName(model) {
    return model.display_name || model.name || model.id;
  }

  function modelMetrics(model) {
    return model.metrics || model.scores || {};
  }

  function scoreFor(model, task, metric) {
    var metrics = modelMetrics(model);
    var taskData = metrics[task];
    if (!taskData && task === "task2_sign_mismatch") taskData = metrics.task2_mismatch;
    if (!taskData) return null;
    var raw = taskData[metric];
    if (raw == null && metric === "macro_f1") raw = taskData.f1;
    return pct(raw);
  }

  function setMode(mode, updateUrl) {
    var next = mode === "results" ? "results" : "explore";
    body.dataset.mode = next;
    document.querySelectorAll("[data-view-mode]").forEach(function (button) {
      button.setAttribute("aria-pressed", String(button.dataset.viewMode === next));
    });
    if (contextLab) contextLab.hidden = next === "results";
    if (updateUrl && window.history && window.URL) {
      var url = new URL(window.location.href);
      if (next === "results") url.searchParams.set("view", "results");
      else url.searchParams.delete("view");
      window.history.replaceState({}, "", url.pathname + url.search + url.hash);
    }
  }

  function bindModeSwitch() {
    document.querySelectorAll("[data-view-mode]").forEach(function (button) {
      button.addEventListener("click", function () { setMode(button.dataset.viewMode, true); });
    });
    var requested = new URLSearchParams(window.location.search).get("view");
    setMode(requested === "results" ? "results" : "explore", false);
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

  function populateFilters(data) {
    var familySelect = document.getElementById("family-filter");
    var families = Array.from(new Set((data.models || []).map(function (model) { return model.family; }).filter(Boolean))).sort();
    familySelect.innerHTML = '<option value="all">All families</option>' + families.map(function (family) {
      return '<option value="' + escapeHtml(family) + '">' + escapeHtml(family) + '</option>';
    }).join("");
  }

  function taskDescription(task) {
    var tasks = (state.data && state.data.tasks) || [];
    var base = task.indexOf("task1_") === 0 ? "task1" : task.indexOf("task2_") === 0 ? "task2" : task;
    return tasks.find(function (item) { return item.id === base; });
  }

  function renderModels() {
    if (!state.data || !modelChart) return;
    var models = (state.data.models || []).filter(function (model) {
      return (state.access === "all" || accessKey(model) === state.access) &&
        (state.family === "all" || model.family === state.family) &&
        scoreFor(model, state.task, state.metric) != null;
    }).sort(function (a, b) {
      return scoreFor(b, state.task, state.metric) - scoreFor(a, state.task, state.metric);
    });

    if (!models.length) {
      modelChart.innerHTML = '<p class="empty-state">No models match these filters.</p>';
      chartStatus.textContent = "0 models shown.";
      return;
    }

    modelChart.innerHTML = models.map(function (model) {
      var score = scoreFor(model, state.task, state.metric);
      var tooltipText = modelName(model) + " · " + TASK_LABELS[state.task] + " · " +
        (state.metric === "accuracy" ? "Accuracy " : "Macro F1 ") + number(score) + "%";
      return '<button class="model-row" type="button" data-model-id="' + escapeHtml(model.id) + '" ' +
        'data-tooltip="' + escapeHtml(tooltipText) + '" aria-label="Open ' + escapeHtml(tooltipText) + ' details">' +
        '<span class="model-identity"><strong>' + escapeHtml(modelName(model)) + '</strong><small>' +
        escapeHtml(model.family || "Other") + ' · ' + accessLabel(model) + '</small></span>' +
        '<span class="bar-track" aria-hidden="true"><i style="--value:' + score.toFixed(2) + '%"></i></span>' +
        '<b>' + number(score) + '</b></button>';
    }).join("");

    bindModelRows(models);
    var detail = taskDescription(state.task);
    var taskN = detail && state.task === "task2_sign_mismatch" ? detail.sign_mismatch_instances : detail && detail.instances;
    chartStatus.textContent = models.length + " models · " + TASK_LABELS[state.task] + " · " +
      (state.metric === "accuracy" ? "Accuracy" : "Macro F1") + (taskN ? " · n=" + comma(taskN) : "");
    var summary = document.getElementById("results-summary");
    if (summary && detail) summary.textContent = detail.research_question || detail.description;
  }

  function positionTooltip(event, target) {
    if (!tooltip || tooltip.hidden) return;
    var rect = target.getBoundingClientRect();
    var x = event && Number.isFinite(event.clientX) ? event.clientX + 12 : rect.left + Math.min(rect.width, 220);
    var y = event && Number.isFinite(event.clientY) ? event.clientY + 12 : rect.top - tooltip.offsetHeight - 8;
    var maxX = window.innerWidth - tooltip.offsetWidth - 10;
    var maxY = window.innerHeight - tooltip.offsetHeight - 10;
    tooltip.style.left = Math.max(10, Math.min(x, maxX)) + "px";
    tooltip.style.top = Math.max(10, Math.min(y, maxY)) + "px";
  }

  function showTooltip(target, event) {
    if (!tooltip) return;
    tooltip.textContent = target.dataset.tooltip || "";
    tooltip.hidden = false;
    positionTooltip(event, target);
  }

  function hideTooltip() {
    if (tooltip) tooltip.hidden = true;
  }

  function bindModelRows(models) {
    var lookup = new Map(models.map(function (model) { return [model.id, model]; }));
    modelChart.querySelectorAll("[data-model-id]").forEach(function (row) {
      row.addEventListener("click", function () { openModel(lookup.get(row.dataset.modelId), row); });
      row.addEventListener("pointerenter", function (event) { showTooltip(row, event); });
      row.addEventListener("pointermove", function (event) { positionTooltip(event, row); });
      row.addEventListener("pointerleave", hideTooltip);
      row.addEventListener("focus", function () { showTooltip(row); });
      row.addEventListener("blur", hideTooltip);
    });
  }

  function openModel(model, trigger) {
    if (!model || !dialog) return;
    hideTooltip();
    state.previousFocus = trigger || document.activeElement;
    document.getElementById("model-detail-title").textContent = modelName(model);
    document.getElementById("model-detail-meta").textContent = (model.family || "Model") + " · " + accessLabel(model);
    document.getElementById("model-detail-body").innerHTML = '<div class="scorecard-grid">' + TASK_ORDER.map(function (task) {
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
    document.addEventListener("keydown", function (event) {
      if (event.key === "Escape" && dialog.hasAttribute("open")) closeDialog();
    });
  }

  function bindResultControls() {
    var taskButtons = Array.from(document.querySelectorAll("[data-task]"));
    taskButtons.forEach(function (button, index) {
      button.addEventListener("click", function () {
        state.task = button.dataset.task;
        taskButtons.forEach(function (item) {
          var selected = item === button;
          item.setAttribute("aria-selected", String(selected));
          item.tabIndex = selected ? 0 : -1;
        });
        renderModels();
      });
      button.addEventListener("keydown", function (event) {
        if (event.key !== "ArrowLeft" && event.key !== "ArrowRight") return;
        event.preventDefault();
        var offset = event.key === "ArrowRight" ? 1 : -1;
        taskButtons[(index + offset + taskButtons.length) % taskButtons.length].focus();
      });
    });
    document.querySelectorAll("[data-metric]").forEach(function (button) {
      button.addEventListener("click", function () {
        state.metric = button.dataset.metric;
        document.querySelectorAll("[data-metric]").forEach(function (item) {
          item.setAttribute("aria-pressed", String(item === button));
        });
        renderModels();
      });
    });
    document.getElementById("access-filter").addEventListener("change", function (event) {
      state.access = event.target.value;
      renderModels();
    });
    document.getElementById("family-filter").addEventListener("change", function (event) {
      state.family = event.target.value;
      renderModels();
    });
  }

  function signLabel(sign) {
    var key = String(sign || "").toLowerCase();
    var labels = state.data && state.data.meta && state.data.meta.sign_labels;
    return labels && labels[key] ? labels[key] : key === "positive" ? "+" : key === "negative" ? "−" : key ? key[0].toUpperCase() + key.slice(1) : "—";
  }

  function transitionLabel(value) {
    return String(value || "context switch").split("_").map(function (part) {
      return signLabel(part);
    }).join(" → ");
  }

  function renderExample(index) {
    var examples = state.data.examples || [];
    var example = examples[index];
    if (!example) return;
    state.exampleIndex = index;
    state.guess = null;
    var source = example.source || {};
    var target = example.target || {};
    var stage = document.getElementById("context-stage");
    var select = document.getElementById("case-select");
    select.dataset.activeCaseId = example.id;
    stage.dataset.activeCaseId = example.id;
    stage.innerHTML = '<div class="case-topline"><span>' + escapeHtml(example.domain || "Benchmark") + '</span>' +
      '<span>' + escapeHtml(transitionLabel(example.transition)) + '</span></div>' +
      '<h3>' + escapeHtml(target.treatment || source.treatment) + ' → ' + escapeHtml(target.outcome || source.outcome) + '</h3>' +
      '<div class="case-contexts"><section class="case-context source-context"><p>Source · ' + escapeHtml(source.year || "") + '</p>' +
      '<strong>' + escapeHtml(source.context) + '</strong></section>' +
      '<div class="relation"><span>Source cue</span><b>' + escapeHtml(signLabel(source.sign)) + '</b><span>Predict target</span></div>' +
      '<section class="case-context target-context"><p>Target · ' + escapeHtml(target.year || "") + '</p>' +
      '<strong>' + escapeHtml(target.context) + '</strong></section></div>' +
      '<p class="case-question">What is the target effect sign?</p>' +
      '<div class="guess-row" role="group" aria-label="Choose the target effect sign">' +
      ["positive", "negative", "none", "mixed"].map(function (sign) {
        return '<button type="button" data-sign-choice="' + sign + '" aria-pressed="false">' + escapeHtml(signLabel(sign)) + '</button>';
      }).join("") + '<button class="reveal-button" type="button" data-case-reveal>Reveal</button></div>' +
      '<div class="case-result" data-case-result hidden></div>';
    bindExampleControls(example);
  }

  function bindExampleControls(example) {
    var stage = document.getElementById("context-stage");
    var choices = stage.querySelectorAll("[data-sign-choice]");
    choices.forEach(function (button) {
      button.addEventListener("click", function () {
        state.guess = button.dataset.signChoice;
        choices.forEach(function (item) { item.setAttribute("aria-pressed", String(item === button)); });
        stage.querySelector("[data-case-result]").hidden = true;
      });
    });
    stage.querySelector("[data-case-reveal]").addEventListener("click", function () {
      var result = stage.querySelector("[data-case-result]");
      var targetSign = String(example.target && example.target.sign || "").toLowerCase();
      var correct = state.guess && state.guess.toLowerCase() === targetSign;
      result.innerHTML = (state.guess ? '<strong>' + (correct ? "Matched." : "Context switch.") + '</strong> ' : "") +
        'Target sign: <strong>' + escapeHtml(signLabel(targetSign)) + '</strong>. ' +
        escapeHtml(example.selection && example.selection.reason || "The target setting determines the benchmark label.");
      result.hidden = false;
      result.focus && result.focus();
    });
  }

  function renderExamples(data) {
    var select = document.getElementById("case-select");
    var examples = data.examples || [];
    select.innerHTML = examples.map(function (example, index) {
      var target = example.target || {};
      return '<option value="' + index + '" data-case-id="' + escapeHtml(example.id) + '">' +
        String(index + 1).padStart(2, "0") + ' · ' + escapeHtml(target.treatment || example.domain || "Case") + '</option>';
    }).join("");
    select.addEventListener("change", function () { renderExample(Number(select.value)); });
    if (examples.length) renderExample(0);
  }

  function renderTransfer(data) {
    var transfer = data.transfer || {};
    var target = document.getElementById("transfer-chart");
    target.innerHTML = (transfer.groups || []).map(function (group) {
      return '<article class="transfer-row"><strong>' + escapeHtml(group.label) + '</strong><div>' +
        '<span style="--value:' + Number(group.overall_accuracy_pct) + '%">Overall ' + number(group.overall_accuracy_pct) + '</span>' +
        '<span style="--value:' + Number(group.sign_mismatch_accuracy_pct) + '%">Sign-switch ' + number(group.sign_mismatch_accuracy_pct) + '</span>' +
        '</div><b>−' + number(group.drop_pp) + ' pp</b></article>';
    }).join("");
    document.getElementById("transfer-distribution").innerHTML = (transfer.prediction_distribution || []).map(function (row) {
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
    document.getElementById("sign-chart").innerHTML = ["positive", "negative", "none", "mixed"].map(function (sign) {
      var value = Number(means[sign]);
      return '<div><span>' + escapeHtml(signLabel(sign)) + '</span><i aria-hidden="true"><b style="--value:' + value + '%"></b></i><strong>' + number(value) + '</strong></div>';
    }).join("");
  }

  function renderCalibration(data) {
    var calibration = data.calibration || {};
    var ece = calibration.ece_by_category || {};
    var abstention = calibration.abstention_unknown_pct || {};
    var target = document.getElementById("calibration-chart");
    target.innerHTML = '<p>' + escapeHtml(calibration.model_id || "Model") + ' · expected calibration error. Lower is better.</p>' +
      Object.keys(ece).map(function (domain) {
        return '<section class="ece-domain"><strong>' + escapeHtml(domain) + ' · unknown ' + number(abstention[domain]) + '%</strong>' +
          '<div class="ece-list">' + ["positive", "negative", "none", "mixed"].map(function (sign) {
            var value = Number(ece[domain][sign]);
            return '<span style="--heat:' + Math.min(1, value) + '">' + escapeHtml(signLabel(sign)) + '<b>' + number(value, 3) + '</b></span>';
          }).join("") + '</div></section>';
      }).join("");
  }

  function initializeData(data) {
    state.data = data;
    updateStats(data);
    populateFilters(data);
    renderExamples(data);
    renderModels();
    renderTransfer(data);
    renderSigns(data);
    renderCalibration(data);
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
        if (chartStatus) chartStatus.textContent = "Interactive data is unavailable; showing the static paper snapshot.";
        document.documentElement.dataset.dataReady = "false";
      });
  }

  bindModeSwitch();
  bindDialog();
  bindResultControls();
  loadData();
}());
