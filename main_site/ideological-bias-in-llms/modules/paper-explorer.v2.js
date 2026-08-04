const DATA_URL = new URL('../data/paper-data.v2.json', import.meta.url);
const SVG_NS = 'http://www.w3.org/2000/svg';

const FAMILY_STYLES = {
    OpenAI: { color: '#004191', marker: 'circle' },
    Claude: { color: '#7655b5', marker: 'diamond' },
    Gemini: { color: '#0f766e', marker: 'square' },
    Grok: { color: '#c65b13', marker: 'triangle' },
    Llama: { color: '#a13d5d', marker: 'pentagon' },
    Qwen: { color: '#4b6fae', marker: 'hexagon' },
};

function escapeHtml(value) {
    return String(value)
        .replaceAll('&', '&amp;')
        .replaceAll('<', '&lt;')
        .replaceAll('>', '&gt;')
        .replaceAll('"', '&quot;')
        .replaceAll("'", '&#039;');
}

function formatOne(value) {
    return Number(value).toFixed(1);
}

function formatPercent(value) {
    return `${formatOne(value)}%`;
}

function formatSigned(value, suffix = '') {
    const number = Number(value);
    const sign = number > 0 ? '+' : number < 0 ? '−' : '';
    return `${sign}${formatOne(Math.abs(number))}${suffix}`;
}

function fullModelName(model) {
    return `${model.family} ${model.display_name}`;
}

function formatDate(date) {
    return new Intl.DateTimeFormat('en', {
        year: 'numeric',
        month: 'short',
        day: 'numeric',
        timeZone: 'UTC',
    }).format(new Date(`${date}T00:00:00Z`));
}

function signLabel(sign) {
    const labels = {
        '+': 'Positive (+)',
        '-': 'Negative (−)',
        None: 'No significant effect',
        mixed: 'Mixed',
    };
    return labels[sign] || String(sign);
}

function metricCard(label, value, className = '') {
    return `
        <div class="metric-card ${className}">
            <dt>${escapeHtml(label)}</dt>
            <dd>${value}</dd>
        </div>`;
}

function svgElement(tag, attributes = {}, text = '') {
    const element = document.createElementNS(SVG_NS, tag);
    Object.entries(attributes).forEach(([name, value]) => element.setAttribute(name, value));
    if (text) element.textContent = text;
    return element;
}

function ensurePaperBaseline(data) {
    if (data.schema_version !== '2.0.0' || data.dataset_version !== 'arxiv-v2-20-models') {
        throw new Error('Unexpected paper-data schema or dataset version.');
    }
    if (!Array.isArray(data.models) || data.models.length !== 20) {
        throw new Error('The public paper baseline must contain exactly 20 models.');
    }
    if (data.models.some((model) => !model.reported_in_paper || /opus-4-8/i.test(model.id))) {
        throw new Error('The dataset includes a model outside the public arXiv v2 baseline.');
    }
    if (data.models.some((model) => !model.release_date || !model.release_date_source?.url)) {
        throw new Error('Every release-chart model needs an official date and source.');
    }
}

export async function initPaperExplorer({ announce }) {
    const response = await fetch(DATA_URL);
    if (!response.ok) throw new Error(`Paper data request failed (${response.status}).`);
    const data = await response.json();
    ensurePaperBaseline(data);

    const modelsById = new Map(data.models.map((model) => [model.id, model]));
    const tooltip = document.getElementById('model-quick-detail');
    const dialog = document.getElementById('model-detail-dialog');
    const dialogTitle = document.getElementById('model-detail-title');
    const dialogFamily = document.getElementById('model-detail-family');
    const dialogRelease = document.getElementById('model-detail-release');
    const releaseSourceLink = document.getElementById('model-release-source');
    const compareToggle = document.getElementById('model-compare-toggle');
    const compareTray = document.getElementById('compare-tray');
    const compareGrid = document.getElementById('compare-grid');
    const compareClear = document.getElementById('compare-clear');
    const compareSort = document.getElementById('compare-sort');
    const releaseChart = document.getElementById('release-chart');
    const releaseLegend = document.getElementById('release-family-legend');
    const releaseTable = document.getElementById('release-data-table');
    const mobileQuery = window.matchMedia('(max-width: 680px)');

    if (!tooltip || !dialog || !releaseChart) {
        throw new Error('Interactive paper UI containers are missing.');
    }

    let currentModelId = null;
    let lastDialogTrigger = null;
    let comparedModelIds = [];
    let chartResizeTimer;
    let quickDetailContext = null;

    function hideQuickDetail() {
        tooltip.hidden = true;
        quickDetailContext = null;
    }

    function showQuickDetail(trigger, model, releaseView = false) {
        quickDetailContext = { trigger, model, releaseView };
        const overview = model.overview;
        tooltip.innerHTML = releaseView
            ? `<strong>${escapeHtml(fullModelName(model))}</strong>
               <span>${escapeHtml(formatDate(model.release_date))} · <em>B</em><sub>dir</sub> ${escapeHtml(formatSigned(overview.b_dir_pct))}</span>`
            : `<strong>${escapeHtml(fullModelName(model))}</strong>
               <span>Intervention ${formatPercent(overview.intervention_accuracy)} · Market ${formatPercent(overview.market_accuracy)}</span>
               <span>Gap ${escapeHtml(formatSigned(overview.accuracy_gap_pp, ' pp'))} · <em>B</em><sub>dir</sub> ${escapeHtml(formatSigned(overview.b_dir_pct))}</span>`;
        tooltip.hidden = false;

        const triggerRect = trigger.getBoundingClientRect();
        const tooltipRect = tooltip.getBoundingClientRect();
        const gutter = 10;
        let left = triggerRect.left + triggerRect.width / 2 - tooltipRect.width / 2;
        left = Math.max(gutter, Math.min(left, window.innerWidth - tooltipRect.width - gutter));
        let top = triggerRect.top - tooltipRect.height - 8;
        if (top < gutter) top = triggerRect.bottom + 8;
        tooltip.style.left = `${left}px`;
        tooltip.style.top = `${top}px`;
    }

    function activateTab(name, moveFocus = false) {
        const tabs = [...dialog.querySelectorAll('[data-model-tab]')];
        const panels = [...dialog.querySelectorAll('[data-model-panel]')];
        tabs.forEach((tab) => {
            const active = tab.dataset.modelTab === name;
            tab.setAttribute('aria-selected', String(active));
            tab.tabIndex = active ? 0 : -1;
            if (active && moveFocus) tab.focus();
        });
        panels.forEach((panel) => {
            panel.hidden = panel.dataset.modelPanel !== name;
        });
    }

    function renderOverview(model) {
        const overview = model.overview;
        document.getElementById('model-panel-overview').innerHTML = `
            <dl class="metric-grid">
                ${metricCard('Non-contested accuracy', formatPercent(overview.non_contested_accuracy))}
                ${metricCard('Contested accuracy', formatPercent(overview.contested_accuracy))}
                ${metricCard('Intervention-truth', formatPercent(overview.intervention_accuracy), 'intervention-metric')}
                ${metricCard('Market-truth', formatPercent(overview.market_accuracy), 'market-metric')}
                ${metricCard('Accuracy gap', `${escapeHtml(formatSigned(overview.accuracy_gap_pp))}<small>pp</small>`)}
                ${metricCard('Error-direction bias, B_dir', escapeHtml(formatSigned(overview.b_dir_pct)))}
            </dl>
            <p class="metric-definition">Non-contested and contested accuracy use the paper's Table 5 subsets. Accuracy gap = intervention-truth accuracy − market-truth accuracy. <em>B</em><sub>dir</sub> = 100 × (intervention-leaning errors − market-leaning errors) / directional errors.</p>`;
    }

    function iclTargetCard(title, values) {
        const conditions = [
            ['None', values.none],
            ['Non-contested', values.non_contested],
            ['Intervention-Ex', values.intervention_ex],
            ['Market-Ex', values.market_ex],
        ];
        return `
            <section class="icl-target-card">
                <h3>${escapeHtml(title)}</h3>
                <dl class="icl-condition-grid">
                    ${conditions.map(([label, value]) => `
                        <div><dt>${escapeHtml(label)}</dt><dd>${formatPercent(value)}</dd></div>`).join('')}
                </dl>
                <div class="icl-delta"><span>Δ<sub>example</sub></span><strong>${escapeHtml(formatSigned(values.delta_example, ' pp'))}</strong></div>
            </section>`;
    }

    function renderIcl(model) {
        document.getElementById('model-panel-icl').innerHTML = `
            <p class="icl-definition"><strong>Δ<sub>example</sub></strong> = Intervention-Ex accuracy − Market-Ex accuracy for the same target side. “None” is no in-context example; “Non-contested” uses an example on which the two economic perspectives agree. Example-condition rows use matched subsets, so compare conditions within a target rather than treating them as one shared denominator.</p>
            <div class="icl-targets">
                ${iclTargetCard('Intervention-truth target', model.icl.intervention_truth)}
                ${iclTargetCard('Market-truth target', model.icl.market_truth)}
            </div>`;
    }

    function renderExamples(model) {
        const cards = data.examples.map((example) => {
            const output = example.model_outputs.find((row) => row.model_id === model.id);
            const correctness = output.correct ? 'Correct' : 'Incorrect';
            return `
                <article class="example-card">
                    <header class="example-card-header">
                        <div>
                            <span class="example-id">${escapeHtml(example.case_id)}</span>
                            <h3>${escapeHtml(example.treatment)} → ${escapeHtml(example.outcome)}</h3>
                        </div>
                        <span class="correctness-badge ${output.correct ? 'correct' : 'incorrect'}">${correctness}</span>
                    </header>
                    <p class="example-context">${escapeHtml(example.context_summary)}</p>
                    <dl class="example-signs">
                        <div><dt>Empirical sign</dt><dd>${escapeHtml(signLabel(example.empirical_sign))}</dd></div>
                        <div><dt>Intervention expectation</dt><dd>${escapeHtml(signLabel(example.intervention_sign))}</dd></div>
                        <div><dt>Market expectation</dt><dd>${escapeHtml(signLabel(example.market_sign))}</dd></div>
                        <div><dt>Model prediction</dt><dd>${escapeHtml(signLabel(output.predicted_sign))}</dd></div>
                    </dl>
                    <p class="example-explanation"><strong>Short model-generated explanation:</strong> ${escapeHtml(output.explanation)}</p>
                    <a class="example-source" href="${escapeHtml(example.paper_url)}" target="_blank" rel="noopener noreferrer">Original study: ${escapeHtml(example.title)} <span aria-hidden="true">↗</span></a>
                </article>`;
        });
        document.getElementById('model-panel-examples').innerHTML = `
            <p class="icl-definition">Two representative public cases are shown as short editorial summaries. Explanations are brief excerpts from the returned rationale; prompts, source-paper prose, and hidden chain-of-thought are not displayed.</p>
            <div class="example-list">${cards.join('')}</div>`;
    }

    function refreshCompareToggle() {
        if (!currentModelId) return;
        const selected = comparedModelIds.includes(currentModelId);
        compareToggle.textContent = selected ? 'Remove from compare' : 'Add to compare';
        compareToggle.setAttribute('aria-pressed', String(selected));
    }

    function openModel(modelId, trigger) {
        const model = modelsById.get(modelId);
        if (!model) return;
        currentModelId = modelId;
        lastDialogTrigger = trigger || document.activeElement;
        dialogFamily.textContent = `${model.family} · ${model.access}-source model`;
        dialogTitle.textContent = fullModelName(model);
        dialogRelease.textContent = `Official release: ${formatDate(model.release_date)}`;
        releaseSourceLink.href = model.release_date_source.url;
        releaseSourceLink.setAttribute('aria-label', `Open official release source for ${fullModelName(model)}`);
        renderOverview(model);
        renderIcl(model);
        renderExamples(model);
        activateTab('overview');
        refreshCompareToggle();
        hideQuickDetail();
        if (!dialog.open) dialog.showModal();
        window.requestAnimationFrame(() => dialog.querySelector('[data-dialog-close]').focus());
    }

    dialog.querySelector('[data-dialog-close]').addEventListener('click', () => dialog.close());
    dialog.addEventListener('close', () => {
        if (!dialog.open) {
            currentModelId = null;
            if (lastDialogTrigger?.isConnected) lastDialogTrigger.focus();
        }
    });
    dialog.addEventListener('keydown', (event) => {
        if (event.key !== 'Tab') return;
        const focusable = [...dialog.querySelectorAll(
            'button:not([disabled]), a[href], select:not([disabled]), input:not([disabled]), [tabindex]:not([tabindex="-1"])',
        )].filter((element) => !element.hidden && element.getClientRects().length > 0);
        if (!focusable.length) return;
        const first = focusable[0];
        const last = focusable[focusable.length - 1];
        if (event.shiftKey && document.activeElement === first) {
            event.preventDefault();
            last.focus();
        } else if (!event.shiftKey && document.activeElement === last) {
            event.preventDefault();
            first.focus();
        } else if (!dialog.contains(document.activeElement)) {
            event.preventDefault();
            first.focus();
        }
    });

    const tabs = [...dialog.querySelectorAll('[data-model-tab]')];
    tabs.forEach((tab, index) => {
        tab.addEventListener('click', () => activateTab(tab.dataset.modelTab));
        tab.addEventListener('keydown', (event) => {
            const keys = ['ArrowLeft', 'ArrowRight', 'Home', 'End'];
            if (!keys.includes(event.key)) return;
            event.preventDefault();
            let nextIndex = index;
            if (event.key === 'ArrowLeft') nextIndex = (index - 1 + tabs.length) % tabs.length;
            if (event.key === 'ArrowRight') nextIndex = (index + 1) % tabs.length;
            if (event.key === 'Home') nextIndex = 0;
            if (event.key === 'End') nextIndex = tabs.length - 1;
            activateTab(tabs[nextIndex].dataset.modelTab, true);
        });
    });

    function enhanceMainResults() {
        document.querySelectorAll('.model-family-group[tabindex]').forEach((group) => {
            group.removeAttribute('tabindex');
        });
        const rows = [...document.querySelectorAll('.model-score-row')];
        if (rows.length !== data.models.length) {
            throw new Error(`Expected 20 static model rows; found ${rows.length}.`);
        }
        rows.forEach((row, index) => {
            const model = data.models[index];
            row.dataset.modelId = model.id;
            const button = document.createElement('button');
            button.type = 'button';
            button.className = 'model-open-button';
            button.dataset.modelId = model.id;
            button.setAttribute('aria-label', `Open detailed results for ${fullModelName(model)}`);
            button.setAttribute('aria-describedby', tooltip.id);
            button.addEventListener('mouseenter', () => showQuickDetail(button, model));
            button.addEventListener('mouseleave', hideQuickDetail);
            button.addEventListener('focus', () => showQuickDetail(button, model));
            button.addEventListener('blur', hideQuickDetail);
            button.addEventListener('click', () => openModel(model.id, button));
            row.prepend(button);
        });
    }

    function maxComparedModels() {
        return mobileQuery.matches ? 2 : 3;
    }

    function syncCompareUrl() {
        const url = new URL(window.location.href);
        if (comparedModelIds.length) url.searchParams.set('compare', comparedModelIds.join(','));
        else url.searchParams.delete('compare');
        window.history.replaceState({}, '', `${url.pathname}${url.search}${url.hash}`);
    }

    function updateComparedClasses() {
        document.querySelectorAll('[data-model-id]').forEach((element) => {
            const selected = comparedModelIds.includes(element.dataset.modelId);
            if (element.classList.contains('model-score-row') || element.classList.contains('release-point-button')) {
                element.classList.toggle('is-compared', selected);
            }
        });
    }

    function compareCard(model) {
        const overview = model.overview;
        return `
            <article class="compare-card" data-compare-model="${escapeHtml(model.id)}">
                <h3>${escapeHtml(fullModelName(model))}</h3>
                <button class="compare-remove" type="button" data-remove-model="${escapeHtml(model.id)}" aria-label="Remove ${escapeHtml(fullModelName(model))} from comparison">×</button>
                <dl class="compare-metrics">
                    <div><dt>Non-contested</dt><dd>${formatPercent(overview.non_contested_accuracy)}</dd></div>
                    <div><dt>Contested</dt><dd>${formatPercent(overview.contested_accuracy)}</dd></div>
                    <div><dt>Intervention</dt><dd>${formatPercent(overview.intervention_accuracy)}</dd></div>
                    <div><dt>Market</dt><dd>${formatPercent(overview.market_accuracy)}</dd></div>
                    <div><dt>Gap</dt><dd>${escapeHtml(formatSigned(overview.accuracy_gap_pp, ' pp'))}</dd></div>
                    <div><dt>B_dir</dt><dd>${escapeHtml(formatSigned(overview.b_dir_pct))}</dd></div>
                </dl>
            </article>`;
    }

    function renderCompare() {
        compareTray.hidden = comparedModelIds.length === 0;
        let ordered = comparedModelIds.map((id) => modelsById.get(id)).filter(Boolean);
        const sortKey = compareSort.value;
        const keyMap = {
            intervention: 'intervention_accuracy',
            market: 'market_accuracy',
            gap: 'accuracy_gap_pp',
            b_dir: 'b_dir_pct',
        };
        if (keyMap[sortKey]) {
            ordered = [...ordered].sort((a, b) => b.overview[keyMap[sortKey]] - a.overview[keyMap[sortKey]]);
        }
        compareGrid.innerHTML = ordered.map(compareCard).join('');
        compareGrid.querySelectorAll('[data-remove-model]').forEach((button) => {
            button.addEventListener('click', () => toggleCompare(button.dataset.removeModel));
        });
        updateComparedClasses();
        refreshCompareToggle();
    }

    function setComparedModels(ids, shouldSync = true) {
        const unique = [...new Set(ids)].filter((id) => modelsById.has(id));
        comparedModelIds = unique.slice(0, maxComparedModels());
        if (shouldSync) syncCompareUrl();
        renderCompare();
    }

    function toggleCompare(modelId) {
        if (comparedModelIds.includes(modelId)) {
            setComparedModels(comparedModelIds.filter((id) => id !== modelId));
            announce(`${fullModelName(modelsById.get(modelId))} removed from comparison.`);
            return;
        }
        const limit = maxComparedModels();
        if (comparedModelIds.length >= limit) {
            announce(`Compare up to ${limit} models on ${mobileQuery.matches ? 'mobile' : 'desktop'}.`);
            return;
        }
        setComparedModels([...comparedModelIds, modelId]);
        announce(`${fullModelName(modelsById.get(modelId))} added to comparison.`);
    }

    compareToggle.addEventListener('click', () => {
        if (currentModelId) toggleCompare(currentModelId);
    });
    compareClear.addEventListener('click', () => {
        setComparedModels([]);
        announce('Model comparison cleared.');
    });
    compareSort.addEventListener('change', renderCompare);
    mobileQuery.addEventListener('change', () => {
        if (comparedModelIds.length > maxComparedModels()) {
            setComparedModels(comparedModelIds.slice(0, maxComparedModels()));
            announce('Comparison was limited to two models for the mobile layout.');
        } else {
            renderCompare();
        }
    });

    function renderLegend() {
        releaseLegend.innerHTML = Object.entries(FAMILY_STYLES).map(([family, style]) => `
            <span class="release-legend-item">
                <i class="release-legend-mark family-marker-${style.marker}" style="--family-color:${style.color}" aria-hidden="true"></i>${escapeHtml(family)}
            </span>`).join('');
    }

    function renderReleaseTable() {
        const ordered = [...data.models].sort((a, b) => a.release_date.localeCompare(b.release_date));
        releaseTable.innerHTML = `
            <table>
                <caption class="visually-hidden">Official release dates and paper-reported error-direction bias for 20 models</caption>
                <thead><tr><th>Model</th><th>Official release</th><th>Primary source</th><th>B_dir</th></tr></thead>
                <tbody>${ordered.map((model) => `
                    <tr>
                        <td>${escapeHtml(fullModelName(model))}</td>
                        <td><time datetime="${escapeHtml(model.release_date)}">${escapeHtml(formatDate(model.release_date))}</time></td>
                        <td><a href="${escapeHtml(model.release_date_source.url)}" target="_blank" rel="noopener noreferrer">${escapeHtml(model.release_date_source.title)}</a></td>
                        <td>${escapeHtml(formatSigned(model.overview.b_dir_pct))}</td>
                    </tr>`).join('')}</tbody>
            </table>`;
    }

    function renderReleaseChart() {
        if (document.activeElement?.classList.contains('release-point-button')) hideQuickDetail();
        const width = Math.max(280, Math.round(releaseChart.clientWidth));
        const height = width < 520 ? 450 : 510;
        const margin = {
            top: 28,
            right: width < 520 ? 12 : 24,
            bottom: 58,
            left: width < 520 ? 50 : 70,
        };
        const plotWidth = width - margin.left - margin.right;
        const plotHeight = height - margin.top - margin.bottom;
        const dates = data.models.map((model) => Date.parse(`${model.release_date}T00:00:00Z`));
        const day = 24 * 60 * 60 * 1000;
        const xMin = Math.min(...dates) - 28 * day;
        const xMax = Math.max(...dates) + 28 * day;
        const yMin = -10;
        const yMax = 20;
        const xScale = (date) => margin.left + ((date - xMin) / (xMax - xMin)) * plotWidth;
        const yScale = (value) => margin.top + ((yMax - value) / (yMax - yMin)) * plotHeight;

        releaseChart.textContent = '';
        const svg = svgElement('svg', {
            class: 'release-chart-svg',
            viewBox: `0 0 ${width} ${height}`,
            width,
            height,
            'aria-hidden': 'true',
        });

        [-10, -5, 0, 5, 10, 15, 20].forEach((tick) => {
            const y = yScale(tick);
            svg.appendChild(svgElement('line', {
                x1: margin.left,
                x2: width - margin.right,
                y1: y,
                y2: y,
                class: tick === 0 ? 'release-zero-line' : 'release-grid-line',
            }));
            svg.appendChild(svgElement('text', {
                x: margin.left - 9,
                y: y + 4,
                'text-anchor': 'end',
                class: 'release-tick-label',
            }, tick > 0 ? `+${tick}` : String(tick)));
        });

        const xTickCount = width < 520 ? 4 : 6;
        for (let index = 0; index < xTickCount; index += 1) {
            const ratio = index / (xTickCount - 1);
            const timestamp = xMin + ratio * (xMax - xMin);
            const x = xScale(timestamp);
            svg.appendChild(svgElement('line', {
                x1: x,
                x2: x,
                y1: margin.top,
                y2: height - margin.bottom,
                class: 'release-grid-line',
            }));
            const tickDate = new Date(timestamp);
            const label = new Intl.DateTimeFormat('en', {
                month: 'short',
                year: '2-digit',
                timeZone: 'UTC',
            }).format(tickDate);
            svg.appendChild(svgElement('text', {
                x,
                y: height - margin.bottom + 24,
                'text-anchor': 'middle',
                class: 'release-tick-label',
            }, label));
        }

        svg.appendChild(svgElement('text', {
            x: margin.left + plotWidth / 2,
            y: height - 12,
            'text-anchor': 'middle',
            class: 'release-axis-label',
        }, 'First official public release'));
        svg.appendChild(svgElement('text', {
            x: 16,
            y: margin.top + plotHeight / 2,
            transform: `rotate(-90 16 ${margin.top + plotHeight / 2})`,
            'text-anchor': 'middle',
            class: 'release-axis-label',
        }, 'Error-direction bias, B_dir'));

        Object.keys(FAMILY_STYLES).forEach((family) => {
            const familyModels = data.models
                .filter((model) => model.family === family)
                .sort((a, b) => a.release_date.localeCompare(b.release_date));
            const points = familyModels.map((model) => {
                const x = xScale(Date.parse(`${model.release_date}T00:00:00Z`));
                const y = yScale(model.overview.b_dir_pct);
                return `${x},${y}`;
            }).join(' ');
            const line = svgElement('polyline', {
                points,
                class: 'release-family-line',
                stroke: FAMILY_STYLES[family].color,
            });
            svg.appendChild(line);
        });
        releaseChart.appendChild(svg);

        data.models.forEach((model) => {
            const style = FAMILY_STYLES[model.family];
            const button = document.createElement('button');
            const x = xScale(Date.parse(`${model.release_date}T00:00:00Z`));
            const y = yScale(model.overview.b_dir_pct);
            button.type = 'button';
            button.className = `release-point-button family-marker-${style.marker}`;
            button.dataset.modelId = model.id;
            button.style.left = `${x}px`;
            button.style.top = `${y}px`;
            button.style.setProperty('--family-color', style.color);
            button.setAttribute('aria-label', `${fullModelName(model)}, released ${formatDate(model.release_date)}, B dir ${formatSigned(model.overview.b_dir_pct)}. Open details.`);
            button.setAttribute('aria-describedby', tooltip.id);
            button.addEventListener('mouseenter', () => showQuickDetail(button, model, true));
            button.addEventListener('mouseleave', hideQuickDetail);
            button.addEventListener('focus', () => showQuickDetail(button, model, true));
            button.addEventListener('blur', hideQuickDetail);
            button.addEventListener('click', () => openModel(model.id, button));
            releaseChart.appendChild(button);
        });
        updateComparedClasses();
    }

    function initializeCompareFromUrl() {
        const raw = new URL(window.location.href).searchParams.get('compare') || '';
        const requested = raw.split(',').map((id) => id.trim()).filter(Boolean);
        const valid = [...new Set(requested)].filter((id) => modelsById.has(id));
        const limited = valid.slice(0, maxComparedModels());
        setComparedModels(limited, false);
        if (requested.join(',') !== limited.join(',')) syncCompareUrl();
    }

    enhanceMainResults();
    renderLegend();
    renderReleaseTable();
    renderReleaseChart();
    initializeCompareFromUrl();

    if ('ResizeObserver' in window) {
        const observer = new ResizeObserver(() => {
            window.clearTimeout(chartResizeTimer);
            chartResizeTimer = window.setTimeout(renderReleaseChart, 100);
        });
        observer.observe(releaseChart);
    } else {
        window.addEventListener('resize', () => {
            window.clearTimeout(chartResizeTimer);
            chartResizeTimer = window.setTimeout(renderReleaseChart, 100);
        });
    }

    window.addEventListener('scroll', () => {
        const context = quickDetailContext;
        if (context && document.activeElement === context.trigger) {
            showQuickDetail(context.trigger, context.model, context.releaseView);
        } else {
            hideQuickDetail();
        }
    }, { passive: true });
}
