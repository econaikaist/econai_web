const DATA_URL = new URL('../data/paper-data.v2.json', import.meta.url);
const SVG_NS = 'http://www.w3.org/2000/svg';
const RELEASE_POINT_SPACING = 48;
const RELEASE_POINT_RADIUS = 22;

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

function signedTone(value) {
    const number = Number(value);
    if (number > 0) return 'is-intervention';
    if (number < 0) return 'is-market';
    return 'is-neutral';
}

function biasDirection(value) {
    const number = Number(value);
    if (number > 0) return 'Intervention-oriented';
    if (number < 0) return 'Market-oriented';
    return 'Balanced';
}

function gapDirection(value) {
    const number = Number(value);
    if (number > 0) return 'Intervention-aligned advantage';
    if (number < 0) return 'Market-aligned advantage';
    return 'No accuracy advantage';
}

function exampleDirection(value) {
    const number = Number(value);
    if (number > 0) return 'Intervention-Ex advantage';
    if (number < 0) return 'Market-Ex advantage';
    return 'No example advantage';
}

function signCategoryClass(sign) {
    if (sign === '+') return 'sign-positive';
    if (sign === '-') return 'sign-negative';
    if (sign === 'None') return 'sign-none';
    return 'sign-mixed';
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

function metricCard(label, value, className = '', direction = '') {
    return `
        <div class="metric-card ${className}">
            <dt>${escapeHtml(label)}</dt>
            <dd>${value}</dd>
            ${direction ? `<span class="metric-direction">${escapeHtml(direction)}</span>` : ''}
        </div>`;
}

function svgElement(tag, attributes = {}, text = '') {
    const element = document.createElementNS(SVG_NS, tag);
    Object.entries(attributes).forEach(([name, value]) => element.setAttribute(name, value));
    if (text) element.textContent = text;
    return element;
}

function pointDistance(first, second) {
    return Math.hypot(first.x - second.x, first.y - second.y);
}

function layoutReleasePoints(points, bounds) {
    const placed = [];
    const radiusStep = 8;
    const angleCount = 36;
    const maxRadius = Math.ceil(Math.hypot(
        bounds.maxX - bounds.minX,
        bounds.maxY - bounds.minY,
    ));

    points.forEach((point, pointIndex) => {
        let selected = null;
        const phase = ((pointIndex * 137.508) % 360) * (Math.PI / 180);

        for (let radius = 0; radius <= maxRadius && !selected; radius += radiusStep) {
            const candidates = radius === 0
                ? [{ x: point.actualX, y: point.actualY }]
                : Array.from({ length: angleCount }, (_, angleIndex) => {
                    const angle = phase + (angleIndex / angleCount) * Math.PI * 2;
                    return {
                        x: point.actualX + Math.cos(angle) * radius,
                        y: point.actualY + Math.sin(angle) * radius,
                    };
                });

            selected = candidates.find((candidate) => (
                candidate.x >= bounds.minX
                && candidate.x <= bounds.maxX
                && candidate.y >= bounds.minY
                && candidate.y <= bounds.maxY
                && placed.every((other) => pointDistance(candidate, other) >= RELEASE_POINT_SPACING)
            )) || null;
        }

        if (!selected) {
            throw new Error(`Unable to place independent release-chart control for ${point.model.id}.`);
        }

        const displayPoint = { x: selected.x, y: selected.y };
        placed.push(displayPoint);
        point.displayX = displayPoint.x;
        point.displayY = displayPoint.y;
    });

    return points;
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
    const releaseChart = document.getElementById('release-chart');
    const releaseLegend = document.getElementById('release-family-legend');
    const biasRankingList = document.getElementById('bias-ranking-list');
    const aggregateSubfieldRows = [...document.querySelectorAll('.subfield-row')];
    const aggregateSubfieldDetail = document.getElementById('subfield-detail');

    if (!tooltip || !dialog || !releaseChart || !biasRankingList || !aggregateSubfieldDetail) {
        throw new Error('Interactive paper UI containers are missing.');
    }

    let lastDialogTrigger = null;
    let chartResizeTimer;
    let quickDetailContext = null;
    let pinnedSubfieldRow = null;

    function hideQuickDetail() {
        tooltip.hidden = true;
        quickDetailContext = null;
    }

    function showQuickDetail(trigger, model, releaseView = false) {
        quickDetailContext = { trigger, model, releaseView };
        const overview = model.overview;
        tooltip.innerHTML = `
            <header class="quick-detail-header">
                <strong>${escapeHtml(fullModelName(model))}</strong>
                ${releaseView ? `<time datetime="${escapeHtml(model.release_date)}">${escapeHtml(formatDate(model.release_date))}</time>` : ''}
            </header>
            <dl class="quick-detail-grid">
                <div><dt>Intervention-aligned</dt><dd>${formatPercent(overview.intervention_accuracy)}</dd></div>
                <div><dt>Market-aligned</dt><dd>${formatPercent(overview.market_accuracy)}</dd></div>
                <div class="is-gap-neutral"><dt>Accuracy gap</dt><dd>${escapeHtml(formatSigned(overview.accuracy_gap_pp, ' pp'))}<small>${escapeHtml(gapDirection(overview.accuracy_gap_pp))}</small></dd></div>
                <div class="${signedTone(overview.b_dir_pct)}"><dt aria-label="B dir">B<sub>dir</sub></dt><dd>${escapeHtml(formatSigned(overview.b_dir_pct))}<small>${escapeHtml(biasDirection(overview.b_dir_pct))}</small></dd></div>
            </dl>`;
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
                ${metricCard('Views agree', formatPercent(overview.non_contested_accuracy))}
                ${metricCard('Views differ', formatPercent(overview.contested_accuracy))}
                ${metricCard('Intervention-aligned truth', formatPercent(overview.intervention_accuracy), 'intervention-metric')}
                ${metricCard('Market-aligned truth', formatPercent(overview.market_accuracy), 'market-metric')}
                ${metricCard('Accuracy gap', `${escapeHtml(formatSigned(overview.accuracy_gap_pp))}<small>pp</small>`, 'is-gap-neutral', gapDirection(overview.accuracy_gap_pp))}
                ${metricCard('Error-direction bias, B dir', escapeHtml(formatSigned(overview.b_dir_pct)), signedTone(overview.b_dir_pct), biasDirection(overview.b_dir_pct))}
            </dl>
            <div class="metric-definition-grid">
                <section><strong>Views agree</strong><p aria-label="Intervention expectation equals market expectation"><span aria-hidden="true">Expectation<sub>intervention</sub> = Expectation<sub>market</sub></span></p></section>
                <section><strong>Views differ</strong><p aria-label="Intervention expectation does not equal market expectation"><span aria-hidden="true">Expectation<sub>intervention</sub> ≠ Expectation<sub>market</sub></span></p></section>
                <section><strong>Accuracy gap</strong><p aria-label="Intervention-aligned truth accuracy minus market-aligned truth accuracy"><span aria-hidden="true">Acc<sub>intervention</sub> − Acc<sub>market</sub></span></p></section>
                <section><strong aria-label="B dir">B<sub aria-hidden="true">dir</sub></strong><p aria-label="One hundred times intervention-leaning errors minus market-leaning errors, divided by all prediction errors"><span aria-hidden="true">100 × (Errors<sub>intervention</sub> − Errors<sub>market</sub>) / Errors<sub>total</sub></span></p></section>
            </div>
            <p class="definition-hint">Intervention-aligned truth or market-aligned truth means the published effect matches that expectation.</p>`;
    }

    function iclTargetCard(title, values, alignmentClass) {
        const conditions = [
            ['None', values.none, 'is-neutral'],
            ['Views agree', values.non_contested, 'is-neutral'],
            ['Intervention-Ex', values.intervention_ex, 'is-intervention'],
            ['Market-Ex', values.market_ex, 'is-market'],
        ];
        return `
            <section class="icl-target-card ${alignmentClass}">
                <h3>${escapeHtml(title)}</h3>
                <dl class="icl-condition-grid">
                    ${conditions.map(([label, value, className]) => `
                        <div class="${className}"><dt>${escapeHtml(label)}</dt><dd>${formatPercent(value)}</dd></div>`).join('')}
                </dl>
                <div class="icl-delta ${signedTone(values.delta_example)}"><span aria-label="Delta example">Δ<sub>example</sub></span><strong>${escapeHtml(formatSigned(values.delta_example, ' pp'))}<small>${escapeHtml(exampleDirection(values.delta_example))}</small></strong></div>
            </section>`;
    }

    function renderIcl(model) {
        document.getElementById('model-panel-icl').innerHTML = `
            <section class="formula-card icl-formula-card">
                <span>Example contrast</span>
                <p aria-label="Delta example equals Intervention-Ex accuracy minus Market-Ex accuracy for the same target"><span aria-hidden="true">Δ<sub>example</sub> = Acc<sub>Intervention-Ex</sub> − Acc<sub>Market-Ex</sub></span></p>
            </section>
            <p class="icl-definition">None uses no in-context example. Views agree uses an example for which the perspectives predict the same sign. Example conditions use matched subsets; assess conditions within each target.</p>
            <div class="icl-targets">
                ${iclTargetCard('Intervention-aligned truth', model.icl.intervention_truth, 'intervention-target')}
                ${iclTargetCard('Market-aligned truth', model.icl.market_truth, 'market-target')}
            </div>`;
    }

    function renderExamples(model) {
        const cards = data.examples.map((example) => {
            const output = example.model_outputs.find((row) => row.model_id === model.id);
            const correctness = output.correct ? 'Correct' : 'Incorrect';
            const signChip = (label, sign, identityClass = '') => `
                <div class="example-sign-chip ${signCategoryClass(sign)} ${identityClass}"><dt>${escapeHtml(label)}</dt><dd>${escapeHtml(signLabel(sign))}</dd></div>`;
            return `
                <article class="example-card">
                    <header class="example-card-header">
                        <h3>${escapeHtml(example.treatment)} → ${escapeHtml(example.outcome)}</h3>
                        <span class="correctness-badge ${output.correct ? 'correct' : 'incorrect'}">${correctness}</span>
                    </header>
                    <p class="example-context"><strong>Study context</strong>${escapeHtml(example.context)}</p>
                    <div class="example-blocks">
                        <section class="example-reference-block">
                            <span class="example-block-label">Reference</span>
                            <dl class="example-signs">
                                ${signChip('Empirical sign', example.empirical_sign)}
                                ${signChip('Intervention expectation', example.intervention_sign, 'perspective-intervention')}
                                ${signChip('Market expectation', example.market_sign, 'perspective-market')}
                            </dl>
                            <a class="example-source" href="${escapeHtml(example.paper_url)}" target="_blank" rel="noopener noreferrer">Original study: ${escapeHtml(example.title)} <span aria-hidden="true">↗</span></a>
                        </section>
                        <section class="example-model-block">
                            <span class="example-block-label">Selected model</span>
                            <dl class="example-signs example-model-sign">
                                ${signChip('Prediction', output.predicted_sign)}
                            </dl>
                            <div class="example-rationale">
                                <strong>Full model-generated rationale</strong>
                                <p>${escapeHtml(output.rationale)}</p>
                            </div>
                        </section>
                    </div>
                </article>`;
        });
        document.getElementById('model-panel-examples').innerHTML = `
            <p class="icl-definition">Reference evidence and the selected model's returned prediction are shown side by side.</p>
            <div class="example-list">${cards.join('')}</div>`;
    }

    function renderModelSubfields(model) {
        const panel = document.getElementById('model-panel-subfields');
        const subfields = Array.isArray(model.subfields) ? model.subfields : [];
        if (!subfields.length) {
            panel.innerHTML = '<p class="model-subfield-empty">Subfield results are unavailable for this model.</p>';
            return;
        }
        panel.innerHTML = `
            <div class="model-subfield-columns" aria-hidden="true"><span>Subfield</span><span>Intervention</span><span>Market</span><span>Gap</span></div>
            <ul class="model-subfield-list">
                ${subfields.map((subfield) => `
                    <li class="model-subfield-card">
                        <header><h3>${escapeHtml(subfield.name)}</h3><span>n=${escapeHtml(subfield.n_triplets)}</span></header>
                        <dl>
                            <div class="is-intervention"><dt class="visually-hidden">Intervention-aligned accuracy</dt><dd>${formatPercent(subfield.intervention_accuracy)}</dd></div>
                            <div class="is-market"><dt class="visually-hidden">Market-aligned accuracy</dt><dd>${formatPercent(subfield.market_accuracy)}</dd></div>
                            <div class="${signedTone(subfield.accuracy_gap_pp)}"><dt class="visually-hidden">Accuracy gap</dt><dd>${escapeHtml(formatSigned(subfield.accuracy_gap_pp, ' pp'))}<span class="visually-hidden">, ${escapeHtml(gapDirection(subfield.accuracy_gap_pp))}</span></dd></div>
                        </dl>
                    </li>`).join('')}
            </ul>`;
    }

    function openModel(modelId, trigger) {
        const model = modelsById.get(modelId);
        if (!model) return;
        dialog.dataset.modelId = modelId;
        lastDialogTrigger = trigger || document.activeElement;
        dialogFamily.textContent = `${model.family} · ${model.access}-source model`;
        dialogTitle.textContent = fullModelName(model);
        dialogRelease.textContent = `Official release: ${formatDate(model.release_date)}`;
        renderOverview(model);
        renderIcl(model);
        renderExamples(model);
        renderModelSubfields(model);
        activateTab('overview');
        hideQuickDetail();
        if (!dialog.open) dialog.showModal();
        window.requestAnimationFrame(() => dialog.querySelector('[data-dialog-close]').focus());
    }

    dialog.querySelector('[data-dialog-close]').addEventListener('click', () => dialog.close());
    dialog.addEventListener('close', () => {
        if (!dialog.open) {
            delete dialog.dataset.modelId;
            if (lastDialogTrigger?.isConnected) lastDialogTrigger.focus();
        }
    });
    dialog.addEventListener('click', (event) => {
        if (event.target === dialog) dialog.close();
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

    function renderBiasRanking() {
        const ordered = [...data.models].sort((first, second) => (
            second.overview.b_dir_pct - first.overview.b_dir_pct
            || fullModelName(first).localeCompare(fullModelName(second))
        ));
        const maxMagnitude = Math.max(20, ...ordered.map((model) => Math.abs(model.overview.b_dir_pct)));
        biasRankingList.innerHTML = ordered.map((model, index) => {
            const score = model.overview.b_dir_pct;
            const direction = biasDirection(score);
            const width = (Math.abs(score) / maxMagnitude) * 50;
            return `
                <li>
                    <button class="bias-ranking-row ${signedTone(score)}" type="button" data-model-id="${escapeHtml(model.id)}" aria-label="Rank ${index + 1} of 20, ${escapeHtml(fullModelName(model))}, B dir ${escapeHtml(formatSigned(score))}, ${direction}. Open model details.">
                        <span class="bias-rank" aria-hidden="true">${index + 1}</span>
                        <span class="bias-model-name">${escapeHtml(fullModelName(model))}</span>
                        <span class="bias-diverging-track" aria-hidden="true"><i class="bias-zero-line"></i><i class="bias-value-bar" style="--bias-width:${width}%"></i></span>
                        <strong>${escapeHtml(formatSigned(score))}</strong>
                        <span class="bias-direction">${direction}</span>
                    </button>
                </li>`;
        }).join('');
        biasRankingList.querySelectorAll('.bias-ranking-row').forEach((button) => {
            const model = modelsById.get(button.dataset.modelId);
            button.setAttribute('aria-describedby', tooltip.id);
            button.addEventListener('mouseenter', () => showQuickDetail(button, model));
            button.addEventListener('mouseleave', hideQuickDetail);
            button.addEventListener('focus', () => showQuickDetail(button, model));
            button.addEventListener('blur', hideQuickDetail);
            button.addEventListener('click', () => openModel(model.id, button));
        });
    }

    function renderAggregateSubfieldDetail(row, pinned = false) {
        if (!row) {
            aggregateSubfieldDetail.innerHTML = `
                <span class="subfield-detail-kicker">Subfield detail</span>
                <strong>Select a subfield</strong>
                <p>Hover, focus, or activate a row to inspect its sample and accuracy-gap direction.</p>`;
            return;
        }
        const name = row.dataset.subfieldName;
        const sampleSize = Number(row.dataset.sampleSize);
        const interventionAccuracy = Number(row.dataset.interventionAccuracy);
        const marketAccuracy = Number(row.dataset.marketAccuracy);
        const gap = Number(row.dataset.gap);
        aggregateSubfieldDetail.innerHTML = `
            <span class="subfield-detail-kicker">${pinned ? 'Pinned selection' : 'Preview'}</span>
            <strong>${escapeHtml(name)}</strong>
            <dl>
                <div><dt>Directional cases</dt><dd>n=${escapeHtml(sampleSize)}</dd></div>
                <div class="is-intervention"><dt>Intervention-aligned</dt><dd>${formatPercent(interventionAccuracy)}</dd></div>
                <div class="is-market"><dt>Market-aligned</dt><dd>${formatPercent(marketAccuracy)}</dd></div>
                <div class="${signedTone(gap)}"><dt>Accuracy gap</dt><dd>${escapeHtml(formatSigned(gap, ' pp'))}</dd></div>
            </dl>`;
    }

    function initializeAggregateSubfields() {
        aggregateSubfieldRows.forEach((row) => {
            const name = row.dataset.subfieldName;
            const gap = Number(row.dataset.gap);
            row.setAttribute('aria-label', `${name}: accuracy gap ${formatSigned(gap, ' percentage points')}. Show subfield detail.`);
            const preview = () => renderAggregateSubfieldDetail(row, row === pinnedSubfieldRow);
            const restore = () => renderAggregateSubfieldDetail(pinnedSubfieldRow, Boolean(pinnedSubfieldRow));
            row.addEventListener('mouseenter', preview);
            row.addEventListener('mouseleave', restore);
            row.addEventListener('focus', preview);
            row.addEventListener('blur', restore);
            row.addEventListener('click', () => {
                const nextPinned = pinnedSubfieldRow === row ? null : row;
                aggregateSubfieldRows.forEach((candidate) => {
                    const selected = candidate === nextPinned;
                    candidate.classList.toggle('is-pinned', selected);
                    candidate.setAttribute('aria-expanded', String(selected));
                });
                pinnedSubfieldRow = nextPinned;
                renderAggregateSubfieldDetail(pinnedSubfieldRow, Boolean(pinnedSubfieldRow));
            });
            row.addEventListener('keydown', (event) => {
                if (event.key !== 'Escape' || !pinnedSubfieldRow) return;
                event.preventDefault();
                pinnedSubfieldRow.classList.remove('is-pinned');
                pinnedSubfieldRow.setAttribute('aria-expanded', 'false');
                pinnedSubfieldRow = null;
                renderAggregateSubfieldDetail(null);
                row.focus();
            });
        });
        renderAggregateSubfieldDetail(null);
    }

    function renderLegend() {
        releaseLegend.innerHTML = Object.entries(FAMILY_STYLES).map(([family, style]) => `
            <span class="release-legend-item">
                <i class="release-legend-mark family-marker-${style.marker}" style="--family-color:${style.color}" aria-hidden="true"></i>${escapeHtml(family)}
            </span>`).join('');
    }

    function renderReleaseChart() {
        const focusedReleaseModelId = document.activeElement?.classList.contains('release-point-button')
            ? document.activeElement.dataset.modelId
            : null;
        const dialogTriggerModelId = dialog.open
            && lastDialogTrigger?.classList?.contains('release-point-button')
            ? lastDialogTrigger.dataset.modelId
            : null;
        if (focusedReleaseModelId) hideQuickDetail();
        releaseChart.dataset.pointLayoutReady = 'false';
        const width = Math.max(240, Math.round(releaseChart.clientWidth));
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
        const releasePoints = layoutReleasePoints(data.models.map((model) => ({
            model,
            actualX: xScale(Date.parse(`${model.release_date}T00:00:00Z`)),
            actualY: yScale(model.overview.b_dir_pct),
        })), {
            minX: Math.max(margin.left, RELEASE_POINT_RADIUS),
            maxX: Math.min(width - margin.right, width - RELEASE_POINT_RADIUS),
            minY: Math.max(margin.top, RELEASE_POINT_RADIUS),
            maxY: Math.min(height - margin.bottom, height - RELEASE_POINT_RADIUS),
        });
        const releasePointsById = new Map(releasePoints.map((point) => [point.model.id, point]));

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
                'text-anchor': width < 520 && index === xTickCount - 1 ? 'end' : 'middle',
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
                const point = releasePointsById.get(model.id);
                return `${point.actualX},${point.actualY}`;
            }).join(' ');
            const line = svgElement('polyline', {
                points,
                class: 'release-family-line',
                stroke: FAMILY_STYLES[family].color,
            });
            svg.appendChild(line);
        });

        const leaderLayer = svgElement('g', {
            class: 'release-leader-layer',
            'aria-hidden': 'true',
        });
        releasePoints.forEach((point) => {
            const displacement = Math.hypot(
                point.displayX - point.actualX,
                point.displayY - point.actualY,
            );
            if (displacement < 1) return;
            leaderLayer.appendChild(svgElement('line', {
                x1: point.actualX,
                y1: point.actualY,
                x2: point.displayX,
                y2: point.displayY,
                class: 'release-leader-line',
                'data-model-id': point.model.id,
            }));
            leaderLayer.appendChild(svgElement('circle', {
                cx: point.actualX,
                cy: point.actualY,
                r: 3,
                class: 'release-anchor-dot',
                'data-model-id': point.model.id,
            }));
        });
        svg.appendChild(leaderLayer);
        releaseChart.appendChild(svg);

        releasePoints.forEach((point) => {
            const { model } = point;
            const style = FAMILY_STYLES[model.family];
            const button = document.createElement('button');
            button.type = 'button';
            button.className = `release-point-button family-marker-${style.marker}`;
            button.dataset.modelId = model.id;
            button.dataset.actualX = point.actualX.toFixed(3);
            button.dataset.actualY = point.actualY.toFixed(3);
            button.dataset.displayX = point.displayX.toFixed(3);
            button.dataset.displayY = point.displayY.toFixed(3);
            button.style.left = `${point.displayX}px`;
            button.style.top = `${point.displayY}px`;
            button.style.setProperty('--family-color', style.color);
            button.setAttribute('aria-label', `${fullModelName(model)}, released ${formatDate(model.release_date)}, B dir ${formatSigned(model.overview.b_dir_pct)}. Open details.`);
            button.setAttribute('aria-describedby', tooltip.id);
            button.addEventListener('mouseenter', () => showQuickDetail(button, model, true));
            button.addEventListener('mouseleave', hideQuickDetail);
            button.addEventListener('focus', () => showQuickDetail(button, model, true));
            button.addEventListener('blur', hideQuickDetail);
            button.addEventListener('click', () => openModel(model.id, button));
            releaseChart.appendChild(button);
            if (dialogTriggerModelId === model.id) lastDialogTrigger = button;
        });
        releaseChart.dataset.minimumPointSpacing = String(RELEASE_POINT_SPACING);
        releaseChart.dataset.layoutGeneration = String(
            Number(releaseChart.dataset.layoutGeneration || 0) + 1,
        );
        releaseChart.dataset.pointLayoutReady = 'true';
        if (focusedReleaseModelId) {
            releaseChart.querySelector(
                `.release-point-button[data-model-id="${focusedReleaseModelId}"]`,
            )?.focus({ preventScroll: true });
        }
    }

    enhanceMainResults();
    renderBiasRanking();
    initializeAggregateSubfields();
    renderLegend();
    renderReleaseChart();

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
