const DATA_URL = new URL('../data/paper-data.v2.json?v=20260811a', import.meta.url);
const EXTENSION_DATA_URL = new URL('../data/website-experiment-results.v1.json?v=20260811a', import.meta.url);
const BENCHMARK_FAMILY_ORDER = ['OpenAI', 'Claude', 'Gemini', 'Grok', 'Llama', 'Qwen'];
const MAIN_EXCLUDED_CONDITIONS = new Set([
    // Minimum-setting reruns of models already represented by their paper result.
    'oa_gpt5_nano_minimal',
    'oa_gpt5_mini_minimal',
    'an_sonnet46_disabled_low',
    'an_opus46_disabled_low',
    'gg_gemini3_minimal',
]);

const MAIN_MODEL_GROUPS = [
    {
        key: 'openai-compact', family: 'OpenAI', label: 'OpenAI · compact',
        resultKeys: [
            'paper:gpt-4o-mini', 'paper:gpt-5-nano', 'paper:gpt-5-mini',
            'new:oa_gpt54_nano_none', 'new:oa_gpt54_mini_none', 'new:oa_gpt56_luna_none',
        ],
    },
    {
        key: 'openai-flagship', family: 'OpenAI', label: 'OpenAI · flagship',
        resultKeys: [
            'paper:gpt-4o', 'paper:gpt-5-2', 'new:oa_gpt54_none', 'new:oa_gpt55_none',
            'new:oa_gpt56_terra_none', 'new:oa_gpt56_sol_none',
        ],
    },
    {
        key: 'claude', family: 'Claude', label: 'Claude',
        resultKeys: [
            'paper:claude-haiku-4-5', 'paper:claude-sonnet-4-6',
            'paper:claude-opus-4-6', 'new:an_opus47_disabled_low',
            'new:an_opus48_disabled_low', 'new:an_fable5_adaptive_low',
            'new:an_sonnet5_disabled_low', 'new:an_opus5_disabled_low',
        ],
    },
    {
        key: 'gemini', family: 'Gemini', label: 'Gemini',
        resultKeys: [
            'paper:gemini-2-5-flash', 'paper:gemini-3-flash',
            'new:gg_gemini31lite_minimal', 'new:gg_gemini35_minimal', 'new:gg_gemini36_minimal',
        ],
    },
    {
        key: 'grok', family: 'Grok', label: 'Grok',
        resultKeys: [
            'paper:grok-3-mini', 'paper:grok-3', 'paper:grok-4-1-fast',
            'new:or_grok420_reasoning_disabled',
            'new:or_grok43_none', 'new:or_grok45_low',
        ],
    },
    {
        key: 'llama', family: 'Llama', label: 'Llama',
        resultKeys: [
            'paper:llama-3-1-8b', 'paper:llama-3-2-1b', 'paper:llama-3-2-3b',
            'paper:llama-3-3-70b', 'new:local_llama4_scout_17b_16e_w4a16',
        ],
    },
    {
        key: 'qwen-compact', family: 'Qwen', label: 'Qwen · compact / medium',
        resultKeys: [
            'paper:qwen-3-8b', 'paper:qwen-3-14b',
            'new:local_qwen35_0_8b_nf4', 'new:local_qwen35_2b_w4_bf16',
            'new:local_qwen35_4b_awq', 'new:local_qwen35_9b_awq',
        ],
    },
    {
        key: 'qwen-large', family: 'Qwen', label: 'Qwen · large / MoE',
        resultKeys: [
            'paper:qwen-3-32b', 'new:local_qwen35_27b_gptq',
            'new:local_qwen35_35b_a3b_gptq', 'new:local_qwen36_27b_gptq',
            'new:local_qwen36_35b_a3b_awq',
        ],
    },
];

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
    if (number > 0) return 'Intervention-truth advantage';
    if (number < 0) return 'Market-truth advantage';
    return 'No accuracy advantage';
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

function ensurePaperBaseline(data) {
    if (data.schema_version !== '2.1.0' || data.dataset_version !== 'colm-camera-ready-20-models') {
        throw new Error('Unexpected paper-data schema or dataset version.');
    }
    if (!Array.isArray(data.models) || data.models.length !== 20) {
        throw new Error('The camera-ready paper baseline must contain exactly 20 models.');
    }
    const denominators = data.denominators;
    if (
        denominators?.benchmark_total !== 10490
        || denominators?.contested_pool !== 1056
        || denominators?.directional_total !== 878
        || denominators?.intervention_truth !== 507
        || denominators?.market_truth !== 371
        || denominators?.sensitive_neither !== 178
    ) {
        throw new Error('Unexpected camera-ready paper denominators.');
    }
    if (data.models.some((model) => !model.reported_in_paper || /opus-4-8/i.test(model.id))) {
        throw new Error('The dataset includes a model outside the camera-ready paper baseline.');
    }
    if (data.models.some((model) => !model.release_date || !model.release_date_source?.url)) {
        throw new Error('Every release-chart model needs an official date and source.');
    }
}

function ensureUpdatedResults(data) {
    const denominators = data?.evaluation?.denominators;
    const mainResults = data?.main_benchmark?.results;
    const sweeps = data?.reasoning_effort_sweeps?.sweeps;
    if (data?.schema_version !== 'website-experiment-results.v1') {
        throw new Error('Unexpected updated-results schema.');
    }
    if (
        denominators?.contested !== 1056
        || denominators?.directional !== 878
        || denominators?.intervention_truth !== 507
        || denominators?.market_truth !== 371
        || denominators?.neither_truth !== 178
    ) {
        throw new Error('Unexpected updated-results denominators.');
    }
    if (!Array.isArray(mainResults) || mainResults.length !== 32) {
        throw new Error('The new-evaluation panel must contain 32 conditions.');
    }
    if (!Array.isArray(sweeps) || sweeps.length !== 4) {
        throw new Error('The reasoning-effort analysis must contain four model sweeps.');
    }
    if (sweeps.reduce((count, sweep) => count + (sweep.results?.length || 0), 0) !== 17) {
        throw new Error('The reasoning-effort analysis must contain 17 conditions.');
    }
}

function experimentSettingLabel(setting, compact = false) {
    if (Object.hasOwn(setting, 'reasoning_effort')) {
        return compact ? setting.reasoning_effort : `reasoning ${setting.reasoning_effort}`;
    }
    if (Object.hasOwn(setting, 'reasoning_enabled')) {
        const label = setting.reasoning_enabled ? 'enabled' : 'disabled';
        return compact ? label : `reasoning ${label}`;
    }
    if (Object.hasOwn(setting, 'thinking_level')) {
        return compact ? setting.thinking_level : `thinking ${setting.thinking_level}`;
    }
    if (Object.hasOwn(setting, 'thinking')) {
        const label = `${setting.thinking} · ${setting.effort || 'default'}`;
        return compact ? label : `thinking ${label.replace(' · ', ' · effort ')}`;
    }
    if (Object.hasOwn(setting, 'quantization')) {
        return compact ? setting.quantization : `local ${setting.quantization}`;
    }
    return 'provider minimum';
}

function normalizedDisplayName(family, displayName) {
    const prefixes = {
        Claude: /^Claude\s+/,
        Gemini: /^Gemini\s+/,
        Grok: /^Grok\s+/,
        Llama: /^Llama\s+/,
        Qwen: /^Qwen\s+/,
    };
    return prefixes[family] ? displayName.replace(prefixes[family], '') : displayName;
}

function normalizeBenchmarkRows(paperData, experimentData) {
    const paperRows = paperData.models.map((model) => ({
        resultKey: `paper:${model.id}`,
        family: model.family,
        displayName: model.display_name,
        paperModelId: model.id,
        overall: model.overview.contested_accuracy,
        intervention: model.overview.intervention_accuracy,
        market: model.overview.market_accuracy,
        gap: model.overview.accuracy_gap_pp,
        bias: model.overview.b_dir_pct,
    }));
    const newRows = experimentData.main_benchmark.results
        .filter((result) => !MAIN_EXCLUDED_CONDITIONS.has(result.condition_key))
        .map((result) => ({
        resultKey: `new:${result.condition_key}`,
        family: result.family === 'GPT'
            ? 'OpenAI'
            : result.family === 'Claude'
                ? 'Claude'
                : result.family === 'Gemini'
                    ? 'Gemini'
                    : result.family === 'Grok'
                        ? 'Grok'
                        : result.family,
        displayName: normalizedDisplayName(
            result.family === 'GPT' ? 'OpenAI' : result.family,
            result.display_name,
        ),
        conditionKey: result.condition_key,
        conditionId: result.condition_id,
        provider: result.provider,
        modelId: result.model_id,
        canonicalModelId: result.canonical_model_id,
        setting: result.setting,
        overall: result.metrics.contested_accuracy_pct,
        intervention: result.metrics.intervention_accuracy_pct,
        market: result.metrics.market_accuracy_pct,
        gap: result.metrics.accuracy_gap_pp,
        bias: result.metrics.error_direction_bias_pct,
    }));
    const byKey = new Map([...paperRows, ...newRows].map((row) => [row.resultKey, row]));
    const ordered = MAIN_MODEL_GROUPS.flatMap((group) => (
        group.resultKeys.map((resultKey) => {
            const row = byKey.get(resultKey);
            if (!row) throw new Error(`Missing main-result model ${resultKey}.`);
            return { ...row, groupKey: group.key, groupLabel: group.label };
        })
    ));
    if (ordered.length !== 47 || new Set(ordered.map((row) => row.resultKey)).size !== 47) {
        throw new Error('The main-result view must contain exactly 47 unique models.');
    }
    return ordered;
}

function benchmarkRowMarkup(row) {
    const aria = `${row.family} ${row.displayName}: overall accuracy ${formatOne(row.overall)} percent, `
        + `intervention-truth accuracy ${formatOne(row.intervention)} percent, `
        + `market-truth accuracy ${formatOne(row.market)} percent, `
        + `gap ${formatSigned(row.gap)} percentage points, B dir ${formatSigned(row.bias)}.`;
    const paperAttribute = row.paperModelId
        ? ` data-paper-model-id="${escapeHtml(row.paperModelId)}"`
        : '';
    const conditionAttribute = row.conditionKey
        ? ` data-condition-key="${escapeHtml(row.conditionKey)}"`
        : '';
    return `
        <div class="model-score-row" role="group" aria-label="${escapeHtml(aria)}"
            data-result-key="${escapeHtml(row.resultKey)}"${paperAttribute}${conditionAttribute}>
            <div class="model-score-name" aria-hidden="true">
                <strong>${escapeHtml(row.displayName)}</strong>
            </div>
            <div class="model-score-bars" aria-hidden="true">
                <div class="model-score-track"><span class="model-score-fill intervention-score" style="--score:${row.intervention}%"><strong>${formatOne(row.intervention)}</strong></span></div>
                <div class="model-score-track"><span class="model-score-fill market-score" style="--score:${row.market}%"><strong>${formatOne(row.market)}</strong></span></div>
            </div>
            <strong class="model-gap ${row.gap >= 0 ? 'positive-gap' : 'negative-gap'}" aria-hidden="true">${escapeHtml(formatSigned(row.gap))}<small>pp</small></strong>
        </div>`;
}

function benchmarkGroupMarkup(rows, groupKeys, label) {
    const visible = rows.filter((row) => groupKeys.includes(row.groupKey));
    if (!visible.length) return '';
    const familyCount = new Set(visible.map((row) => row.family)).size;
    const groups = groupKeys.map((groupKey) => {
        const group = MAIN_MODEL_GROUPS.find((candidate) => candidate.key === groupKey);
        const groupRows = visible.filter((row) => row.groupKey === groupKey);
        if (!group || !groupRows.length) return '';
        const groupId = `model-group-${group.key}`;
        return `
            <section class="model-family-group" data-model-group="${escapeHtml(group.key)}" style="--models:${groupRows.length}" aria-labelledby="${groupId}" tabindex="0">
                <div class="model-family-heading">
                    <h4 id="${groupId}">${escapeHtml(group.label)}</h4>
                    <span>${groupRows.length} model${groupRows.length === 1 ? '' : 's'}</span>
                </div>
                <div class="model-family-scale" aria-hidden="true"><span>100</span><span>75</span><span>50</span><span>25</span><span>0</span></div>
                ${groupRows.map(benchmarkRowMarkup).join('')}
            </section>`;
    }).join('');
    return `
        <div class="model-source-heading">
            <strong>${escapeHtml(label)}</strong>
            <span>${visible.length} models · ${familyCount} ${familyCount === 1 ? 'family' : 'families'}</span>
        </div>
        ${groups}`;
}

const EFFORT_SERIES = {
    overall: { field: 'contested_accuracy_pct', label: 'Overall accuracy', shortLabel: 'Overall', color: '#0050a4', suffix: '%', marker: 'circle' },
    gap: { field: 'accuracy_gap_pp', label: 'Accuracy gap', shortLabel: 'Gap', color: '#0f766e', suffix: ' pp', signed: true, marker: 'square' },
    bias: { field: 'error_direction_bias_pct', label: 'B dir', shortLabel: 'Bdir', color: '#7655b5', suffix: '', signed: true, marker: 'diamond', dashed: true },
};

function effortMetricValue(row, metricKey) {
    const metric = EFFORT_SERIES[metricKey];
    const value = Number(row.metrics[metric.field]);
    return metric.signed ? formatSigned(value, metric.suffix) : `${formatOne(value)}${metric.suffix}`;
}

function effortMetricDomain(sweeps, metricKeys) {
    const keys = Array.isArray(metricKeys) ? metricKeys : [metricKeys];
    const values = sweeps.flatMap((sweep) => sweep.results.flatMap((row) => (
        keys.map((key) => Number(row.metrics[EFFORT_SERIES[key].field]))
    )));
    if (keys.every((key) => EFFORT_SERIES[key].signed)) {
        const bound = Math.max(5, Math.ceil((Math.max(...values.map(Math.abs)) + 2) / 5) * 5);
        return { min: -bound, max: bound };
    }
    const min = Math.max(0, Math.floor((Math.min(...values) - 4) / 5) * 5);
    const max = Math.min(100, Math.ceil((Math.max(...values) + 4) / 5) * 5);
    return { min, max: max === min ? min + 5 : max };
}

function effortPointPosition(index, count, value, domain) {
    const x = count === 1 ? 50 : 9 + (index / (count - 1)) * 82;
    const y = 8 + ((domain.max - value) / (domain.max - domain.min)) * 76;
    return { x, y };
}

function renderReasoningExplorer(experimentData) {
    const controls = document.getElementById('effort-explorer-controls');
    const grid = document.getElementById('reasoning-effort-grid');
    if (!controls || !grid) throw new Error('Reasoning-effort explorer containers are missing.');

    const sweeps = experimentData.reasoning_effort_sweeps.sweeps;
    const overallDomain = effortMetricDomain(sweeps, 'overall');
    const signedDomain = effortMetricDomain(sweeps, ['gap', 'bias']);
    const overallTicks = [overallDomain.max, (overallDomain.min + overallDomain.max) / 2, overallDomain.min];
    const signedTicks = [signedDomain.max, 0, signedDomain.min];

    controls.innerHTML = `
        <div class="effort-series-legend" role="list" aria-label="Reasoning-effort chart series">
            ${Object.entries(EFFORT_SERIES).map(([key, series]) => `
                <span role="listitem" data-effort-series="${key}"><i class="effort-series-key is-${series.marker}${series.dashed ? ' is-dashed' : ''}" style="--series-color:${series.color}" aria-hidden="true"></i>${escapeHtml(series.label)}</span>`).join('')}
        </div>`;

    function drawCharts() {
        grid.querySelectorAll('.effort-line-chart').forEach((chart) => {
            const canvas = chart.querySelector('canvas');
            const context = canvas.getContext('2d');
            const rect = canvas.getBoundingClientRect();
            const ratio = Math.max(1, window.devicePixelRatio || 1);
            canvas.width = Math.round(rect.width * ratio);
            canvas.height = Math.round(rect.height * ratio);
            context.setTransform(ratio, 0, 0, ratio, 0, 0);
            context.clearRect(0, 0, rect.width, rect.height);

            context.strokeStyle = '#dce4ee';
            context.lineWidth = 1;
            [8, 46, 84].forEach((yPercent) => {
                const y = rect.height * yPercent / 100;
                context.beginPath();
                context.moveTo(rect.width * 0.09, y);
                context.lineTo(rect.width * 0.91, y);
                context.stroke();
            });
            const zeroY = effortPointPosition(0, 1, 0, signedDomain).y;
            context.strokeStyle = '#8795a8';
            context.setLineDash([4, 4]);
            context.beginPath();
            context.moveTo(rect.width * 0.09, rect.height * zeroY / 100);
            context.lineTo(rect.width * 0.91, rect.height * zeroY / 100);
            context.stroke();
            context.setLineDash([]);

            Object.entries(EFFORT_SERIES).forEach(([metricKey, series]) => {
                const points = [...chart.querySelectorAll(`.effort-series-point[data-metric="${metricKey}"]`)];
                context.strokeStyle = series.color;
                context.fillStyle = series.color;
                context.lineWidth = metricKey === 'overall' ? 2.8 : 2.2;
                context.lineJoin = 'round';
                context.lineCap = 'round';
                context.setLineDash(series.dashed ? [6, 4] : []);
                context.beginPath();
                points.forEach((point, index) => {
                    const x = rect.width * Number(point.dataset.x) / 100;
                    const y = rect.height * Number(point.dataset.y) / 100;
                    if (index === 0) context.moveTo(x, y);
                    else context.lineTo(x, y);
                });
                context.stroke();
                context.setLineDash([]);
                points.forEach((point) => {
                    const x = rect.width * Number(point.dataset.x) / 100;
                    const y = rect.height * Number(point.dataset.y) / 100;
                    context.beginPath();
                    if (series.marker === 'square') context.rect(x - 3.5, y - 3.5, 7, 7);
                    else if (series.marker === 'diamond') {
                        context.moveTo(x, y - 5);
                        context.lineTo(x + 5, y);
                        context.lineTo(x, y + 5);
                        context.lineTo(x - 5, y);
                        context.closePath();
                    } else context.arc(x, y, 4, 0, Math.PI * 2);
                    context.fill();
                    context.strokeStyle = '#fff';
                    context.lineWidth = 1.5;
                    context.stroke();
                });
            });
        });
    }

    grid.innerHTML = sweeps.map((sweep) => {
            const family = sweep.family === 'GPT' ? 'OpenAI' : sweep.family;
            const color = FAMILY_STYLES[family]?.color || '#004191';
            const pointMarkup = sweep.results.map((row, index) => {
                const x = effortPointPosition(index, sweep.results.length, 0, { min: 0, max: 1 }).x;
                const setting = experimentSettingLabel(row.setting, true);
                const aria = `${sweep.display_name}, ${setting}: overall ${effortMetricValue(row, 'overall')}, gap ${effortMetricValue(row, 'gap')}, B dir ${effortMetricValue(row, 'bias')}.`;
                const seriesPoints = Object.entries(EFFORT_SERIES).map(([metricKey, series]) => {
                    const domain = metricKey === 'overall' ? overallDomain : signedDomain;
                    const y = effortPointPosition(index, sweep.results.length, Number(row.metrics[series.field]), domain).y;
                    return `<span class="effort-series-point" data-metric="${metricKey}" data-x="${x}" data-y="${y}" aria-hidden="true"></span>`;
                }).join('');
                return `
                    ${seriesPoints}
                    <button class="effort-setting-hit" type="button"
                        data-condition-key="${escapeHtml(row.condition_key)}" data-x="${x}"
                        style="--point-x:${x}%;--chart-color:${color}"
                        aria-label="${escapeHtml(aria)}">
                        <span class="effort-point-tooltip"><b>${escapeHtml(setting)}</b>
                            <span style="--series-color:${EFFORT_SERIES.overall.color}">Overall ${escapeHtml(effortMetricValue(row, 'overall'))}</span>
                            <span style="--series-color:${EFFORT_SERIES.gap.color}">Gap ${escapeHtml(effortMetricValue(row, 'gap'))}</span>
                            <span style="--series-color:${EFFORT_SERIES.bias.color}">B<sub>dir</sub> ${escapeHtml(effortMetricValue(row, 'bias'))}</span>
                        </span>
                    </button>`;
            }).join('');
            const accessibleRows = sweep.results.map((row) => `<div><dt>${escapeHtml(experimentSettingLabel(row.setting, true))}</dt><dd>Overall ${escapeHtml(effortMetricValue(row, 'overall'))}; gap ${escapeHtml(effortMetricValue(row, 'gap'))}; B dir ${escapeHtml(effortMetricValue(row, 'bias'))}</dd></div>`).join('');
            return `
                <article class="effort-line-chart" data-sweep-id="${escapeHtml(sweep.sweep_id)}" data-color="${color}" aria-labelledby="effort-title-${escapeHtml(sweep.sweep_id)}">
                    <header><h3 id="effort-title-${escapeHtml(sweep.sweep_id)}">${escapeHtml(sweep.display_name)}</h3><span>${sweep.results.length} settings</span></header>
                    <div class="effort-chart-stage">
                        <div class="effort-y-axis is-left" aria-hidden="true">${overallTicks.map((tick) => `<span>${escapeHtml(formatOne(tick))}</span>`).join('')}</div>
                        <div class="effort-y-axis is-right" aria-hidden="true">${signedTicks.map((tick) => `<span>${escapeHtml(formatSigned(tick))}</span>`).join('')}</div>
                        <canvas aria-hidden="true"></canvas>
                        <div class="effort-point-layer">${pointMarkup}</div>
                    </div>
                    <div class="effort-x-axis" aria-hidden="true">${sweep.results.map((row, index) => {
                        const x = effortPointPosition(index, sweep.results.length, 0, { min: 0, max: 1 }).x;
                        return `<span style="--label-x:${x}%">${escapeHtml(experimentSettingLabel(row.setting, true))}</span>`;
                    }).join('')}</div>
                    <dl class="visually-hidden effort-data-list" aria-label="${escapeHtml(`${sweep.display_name} overall accuracy, accuracy gap, and B dir by reasoning setting`)}">${accessibleRows}</dl>
                </article>`;
        }).join('');
    grid.dataset.metric = 'overall,gap,bias';
    grid.dataset.chartCount = String(sweeps.length);
    grid.dataset.pointCount = String(sweeps.reduce((sum, sweep) => sum + sweep.results.length, 0));
    window.requestAnimationFrame(drawCharts);
    const observer = new ResizeObserver(drawCharts);
    observer.observe(grid);
}

export async function initPaperExplorer({ announce }) {
    const extensionPromise = fetch(EXTENSION_DATA_URL)
        .then((response) => {
            if (!response.ok) throw new Error(`New evaluation data request failed (${response.status}).`);
            return response.json();
        })
        .then((extensionData) => {
            ensureUpdatedResults(extensionData);
            return extensionData;
        })
        .catch((error) => {
            console.error('New evaluation data could not be refreshed; the camera-ready fallback remains visible.', error);
            announce('New evaluation data are temporarily unavailable; verified camera-ready results remain visible.');
            return null;
        });
    const response = await fetch(DATA_URL);
    if (!response.ok) throw new Error(`Paper data request failed (${response.status}).`);
    const data = await response.json();
    ensurePaperBaseline(data);
    const extensionData = await extensionPromise;

    const modelsById = new Map(data.models.map((model) => [model.id, model]));
    const tooltip = document.getElementById('model-quick-detail');
    const dialog = document.getElementById('model-detail-dialog');
    const dialogTitle = document.getElementById('model-detail-title');
    const dialogFamily = document.getElementById('model-detail-family');
    const dialogRelease = document.getElementById('model-detail-release');
    const biasMap = document.getElementById('bias-map');
    const benchmarkChart = document.getElementById('model-benchmark-chart');
    const benchmarkHeading = document.getElementById('model-benchmark-heading');
    const benchmarkDescription = document.getElementById('model-benchmark-description');
    const aggregateSubfieldRows = [...document.querySelectorAll('.subfield-row')];
    const aggregateSubfieldDetail = document.getElementById('subfield-detail');

    if (!tooltip || !dialog || !biasMap || !benchmarkChart
        || !benchmarkHeading || !benchmarkDescription || !aggregateSubfieldDetail) {
        throw new Error('Interactive paper UI containers are missing.');
    }

    const mainModelRows = extensionData
        ? normalizeBenchmarkRows(data, extensionData)
        : data.models.map((model) => ({
            resultKey: `paper:${model.id}`,
            family: model.family,
            displayName: model.display_name,
            paperModelId: model.id,
            overall: model.overview.contested_accuracy,
            intervention: model.overview.intervention_accuracy,
            market: model.overview.market_accuracy,
            gap: model.overview.accuracy_gap_pp,
            bias: model.overview.b_dir_pct,
        }));
    const mainRowsByResultKey = new Map(mainModelRows.map((row) => [row.resultKey, row]));

    let lastDialogTrigger = null;
    let quickDetailContext = null;
    let pinnedSubfieldRow = null;

    function hideQuickDetail() {
        tooltip.hidden = true;
        quickDetailContext = null;
    }

    function hideQuickDetailFor(trigger, preserveFocus = false) {
        if (quickDetailContext?.trigger !== trigger) return;
        if (preserveFocus && document.activeElement === trigger) return;
        hideQuickDetail();
    }

    function canShowPointerDetail(trigger) {
        const focused = document.activeElement;
        return !focused
            || focused === document.body
            || focused === trigger
            || !focused.matches('.model-open-button, .bias-map-marker, .bias-scatter-marker');
    }

    function positionQuickDetail(trigger) {
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

    function showQuickDetail(trigger, model, releaseView = false) {
        quickDetailContext = { trigger, model, releaseView };
        const overview = model.overview;
        tooltip.innerHTML = `
            <header class="quick-detail-header">
                <strong>${escapeHtml(fullModelName(model))}</strong>
                ${releaseView ? `<time datetime="${escapeHtml(model.release_date)}">${escapeHtml(formatDate(model.release_date))}</time>` : ''}
            </header>
            <dl class="quick-detail-grid">
                <div><dt>Intervention-truth</dt><dd>${formatPercent(overview.intervention_accuracy)}</dd></div>
                <div><dt>Market-truth</dt><dd>${formatPercent(overview.market_accuracy)}</dd></div>
                <div class="${signedTone(overview.accuracy_gap_pp)}"><dt>Accuracy gap</dt><dd>${escapeHtml(formatSigned(overview.accuracy_gap_pp, ' pp'))}<small>${escapeHtml(gapDirection(overview.accuracy_gap_pp))}</small></dd></div>
                <div class="${signedTone(overview.b_dir_pct)}"><dt aria-label="B dir">B<sub>dir</sub></dt><dd>${escapeHtml(formatSigned(overview.b_dir_pct))}<small>${escapeHtml(biasDirection(overview.b_dir_pct))}</small></dd></div>
            </dl>`;
        tooltip.hidden = false;

        positionQuickDetail(trigger);
    }

    function showBiasDetail(trigger, row) {
        quickDetailContext = { trigger, row };
        tooltip.innerHTML = `
            <header class="quick-detail-header"><strong>${escapeHtml(`${row.family} ${row.displayName}`)}</strong></header>
            <dl class="quick-detail-grid">
                <div><dt>Overall</dt><dd>${formatPercent(row.overall)}</dd></div>
                <div class="${signedTone(row.bias)}"><dt aria-label="B dir">B<sub>dir</sub></dt><dd>${escapeHtml(formatSigned(row.bias))}<small>${escapeHtml(biasDirection(row.bias))}</small></dd></div>
                <div><dt>Intervention-truth</dt><dd>${formatPercent(row.intervention)}</dd></div>
                <div><dt>Market-truth</dt><dd>${formatPercent(row.market)}</dd></div>
                <div class="${signedTone(row.gap)}"><dt>Accuracy gap</dt><dd>${escapeHtml(formatSigned(row.gap, ' pp'))}<small>${escapeHtml(gapDirection(row.gap))}</small></dd></div>
            </dl>`;
        tooltip.hidden = false;
        positionQuickDetail(trigger);
    }

    function activateTab(name, moveFocus = false) {
        const tabs = [...dialog.querySelectorAll('[data-model-tab]')].filter((tab) => !tab.hidden);
        const resolvedName = tabs.some((tab) => tab.dataset.modelTab === name) ? name : 'overview';
        const panels = [...dialog.querySelectorAll('[data-model-panel]')];
        tabs.forEach((tab) => {
            const active = tab.dataset.modelTab === resolvedName;
            tab.setAttribute('aria-selected', String(active));
            tab.tabIndex = active ? 0 : -1;
            if (active && moveFocus) tab.focus();
        });
        panels.forEach((panel) => {
            panel.hidden = panel.dataset.modelPanel !== resolvedName;
        });
    }

    function renderOverview(model) {
        const overview = model.overview;
        document.getElementById('model-panel-overview').innerHTML = `
            <dl class="metric-grid">
                ${metricCard('Same-sign accuracy', formatPercent(overview.non_contested_accuracy))}
                ${metricCard('Different-sign accuracy', formatPercent(overview.contested_accuracy))}
                ${metricCard('Intervention-truth', formatPercent(overview.intervention_accuracy), 'intervention-metric')}
                ${metricCard('Market-truth', formatPercent(overview.market_accuracy), 'market-metric')}
                ${metricCard('Accuracy gap', `${escapeHtml(formatSigned(overview.accuracy_gap_pp))}<small>pp</small>`, signedTone(overview.accuracy_gap_pp), gapDirection(overview.accuracy_gap_pp))}
                ${metricCard('Error-direction bias, B dir', escapeHtml(formatSigned(overview.b_dir_pct)), signedTone(overview.b_dir_pct), biasDirection(overview.b_dir_pct))}
            </dl>
            <div class="metric-definition-grid">
                <section><strong>Same predicted sign</strong><p aria-label="Intervention-oriented sign equals market-oriented sign"><span aria-hidden="true">Sign<sub>intervention</sub> = Sign<sub>market</sub></span></p></section>
                <section><strong>Different predicted signs</strong><p aria-label="Intervention-oriented sign does not equal market-oriented sign"><span aria-hidden="true">Sign<sub>intervention</sub> ≠ Sign<sub>market</sub></span></p></section>
                <section><strong>Accuracy gap</strong><p aria-label="Intervention-truth accuracy minus market-truth accuracy"><span aria-hidden="true">Acc<sub>intervention</sub> − Acc<sub>market</sub></span></p></section>
                <section><strong aria-label="B dir">B<sub aria-hidden="true">dir</sub></strong><p aria-label="One hundred times intervention-leaning errors minus market-leaning errors, divided by all prediction errors"><span aria-hidden="true">100 × (Errors<sub>intervention</sub> − Errors<sub>market</sub>) / Errors<sub>total</sub></span></p></section>
            </div>
            <p class="definition-hint">Same-sign and different-sign accuracies group cases by whether the intervention-oriented and market-oriented perspectives predict the same or different causal signs.</p>`;
    }

    function renderUpdatedOverview(row) {
        document.getElementById('model-panel-overview').innerHTML = `
            <dl class="metric-grid updated-result-metrics">
                ${metricCard('Overall accuracy', formatPercent(row.overall))}
                ${metricCard('Intervention-truth', formatPercent(row.intervention), 'intervention-metric')}
                ${metricCard('Market-truth', formatPercent(row.market), 'market-metric')}
                ${metricCard('Accuracy gap', `${escapeHtml(formatSigned(row.gap))}<small>pp</small>`, signedTone(row.gap), gapDirection(row.gap))}
                ${metricCard('Error-direction bias, B dir', escapeHtml(formatSigned(row.bias)), signedTone(row.bias), biasDirection(row.bias))}
            </dl>
            <dl class="updated-result-provenance">
                <div><dt>Provider</dt><dd>${escapeHtml(row.provider)}</dd></div>
                <div><dt>Requested model</dt><dd><code>${escapeHtml(row.modelId)}</code></dd></div>
                <div><dt>Canonical model</dt><dd><code>${escapeHtml(row.canonicalModelId)}</code></dd></div>
                <div><dt>Setting</dt><dd>${escapeHtml(experimentSettingLabel(row.setting))}</dd></div>
            </dl>
            <p class="definition-hint">Overall accuracy uses all 1,056 contested cases. Intervention-truth, market-truth, accuracy gap, and B<sub>dir</sub> use the 878 directionally aligned cases.</p>`;
        document.getElementById('model-panel-examples').replaceChildren();
        document.getElementById('model-panel-subfields').replaceChildren();
    }

    function configureDialogTabs(fullPaperDetail) {
        dialog.querySelectorAll('[data-model-tab]').forEach((tab) => {
            tab.hidden = !fullPaperDetail && tab.dataset.modelTab !== 'overview';
        });
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
            <p class="example-intro">Reference evidence appears first, followed by the selected model's prediction and full model-generated rationale.</p>
            <div class="example-list">${cards.join('')}</div>`;
    }

    function renderModelSubfields(model) {
        const panel = document.getElementById('model-panel-subfields');
        const subfields = Array.isArray(model.subfields) ? model.subfields : [];
        if (!subfields.length) {
            panel.innerHTML = '<p class="model-subfield-empty">Subfield results are unavailable for this model.</p>';
            return;
        }
        const rows = [
            ...subfields.map((subfield) => ({ ...subfield, isTotal: false })),
            {
                name: 'Total',
                intervention_accuracy: model.overview.intervention_accuracy,
                market_accuracy: model.overview.market_accuracy,
                accuracy_gap_pp: model.overview.accuracy_gap_pp,
                isTotal: true,
            },
        ];
        panel.innerHTML = `
            <p class="model-subfield-note"><strong>Camera-ready scope.</strong> Total and all seven named rows use the corrected 878 directional cases. Tied JEL-theme assignments split their weight across the tied subfields.</p>
            <div class="model-subfield-columns" aria-hidden="true"><span>Subfield</span><span>Intervention</span><span>Market</span><span>Gap</span></div>
            <ul class="model-subfield-list">
                ${rows.map((subfield) => `
                    <li class="model-subfield-card${subfield.isTotal ? ' is-total' : ''}">
                        <header><h3>${escapeHtml(subfield.name)}</h3></header>
                        <dl>
                            <div class="is-intervention"><dt class="visually-hidden">Intervention-truth accuracy</dt><dd>${formatPercent(subfield.intervention_accuracy)}</dd></div>
                            <div class="is-market"><dt class="visually-hidden">Market-truth accuracy</dt><dd>${formatPercent(subfield.market_accuracy)}</dd></div>
                            <div class="${signedTone(subfield.accuracy_gap_pp)}"><dt class="visually-hidden">Accuracy gap</dt><dd>${escapeHtml(formatSigned(subfield.accuracy_gap_pp, ' pp'))}<span class="visually-hidden">, ${escapeHtml(gapDirection(subfield.accuracy_gap_pp))}</span></dd></div>
                        </dl>
                    </li>`).join('')}
            </ul>`;
    }

    function openModel(modelId, trigger) {
        const model = modelsById.get(modelId);
        if (!model) return;
        configureDialogTabs(true);
        delete dialog.dataset.resultKey;
        delete dialog.dataset.conditionKey;
        dialog.dataset.modelId = modelId;
        lastDialogTrigger = trigger || document.activeElement;
        dialogFamily.textContent = `${model.family} · ${model.access}-source model`;
        dialogTitle.textContent = fullModelName(model);
        dialogRelease.textContent = `Official release: ${formatDate(model.release_date)}`;
        renderOverview(model);
        renderExamples(model);
        renderModelSubfields(model);
        activateTab('overview');
        hideQuickDetail();
        if (!dialog.open) dialog.showModal();
        window.requestAnimationFrame(() => dialog.querySelector('[data-dialog-close]').focus());
    }

    function openUpdatedResult(row, trigger) {
        if (!row?.conditionKey) return;
        configureDialogTabs(false);
        delete dialog.dataset.modelId;
        dialog.dataset.resultKey = row.resultKey;
        dialog.dataset.conditionKey = row.conditionKey;
        lastDialogTrigger = trigger || document.activeElement;
        dialogFamily.textContent = `${row.family} · ${row.provider}`;
        dialogTitle.textContent = `${row.family} ${row.displayName}`;
        dialogRelease.textContent = experimentSettingLabel(row.setting);
        renderUpdatedOverview(row);
        activateTab('overview');
        hideQuickDetail();
        if (!dialog.open) dialog.showModal();
        window.requestAnimationFrame(() => dialog.querySelector('[data-dialog-close]').focus());
    }

    function openBenchmarkRow(row, trigger) {
        if (row.paperModelId) openModel(row.paperModelId, trigger);
        else openUpdatedResult(row, trigger);
    }

    dialog.querySelector('[data-dialog-close]').addEventListener('click', () => dialog.close());
    dialog.addEventListener('close', () => {
        if (!dialog.open) {
            delete dialog.dataset.modelId;
            delete dialog.dataset.resultKey;
            delete dialog.dataset.conditionKey;
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
    tabs.forEach((tab) => {
        tab.addEventListener('click', () => activateTab(tab.dataset.modelTab));
        tab.addEventListener('keydown', (event) => {
            const keys = ['ArrowLeft', 'ArrowRight', 'Home', 'End'];
            if (!keys.includes(event.key)) return;
            event.preventDefault();
            const visibleTabs = tabs.filter((candidate) => !candidate.hidden);
            const index = visibleTabs.indexOf(tab);
            let nextIndex = index;
            if (event.key === 'ArrowLeft') nextIndex = (index - 1 + visibleTabs.length) % visibleTabs.length;
            if (event.key === 'ArrowRight') nextIndex = (index + 1) % visibleTabs.length;
            if (event.key === 'Home') nextIndex = 0;
            if (event.key === 'End') nextIndex = visibleTabs.length - 1;
            activateTab(visibleTabs[nextIndex].dataset.modelTab, true);
        });
    });

    function enhanceMainResults() {
        const rows = [...benchmarkChart.querySelectorAll('.model-score-row[data-result-key]')];
        rows.forEach((row) => {
            const result = mainRowsByResultKey.get(row.dataset.resultKey);
            if (!result) throw new Error(`Unknown benchmark result ${row.dataset.resultKey}.`);
            const model = result.paperModelId ? modelsById.get(result.paperModelId) : null;
            if (result.paperModelId && !model) throw new Error(`Unknown paper model ${result.paperModelId}.`);
            if (model) row.dataset.modelId = model.id;
            if (row.querySelector('.model-open-button')) return;
            const button = document.createElement('button');
            button.type = 'button';
            button.className = 'model-open-button';
            button.dataset.resultKey = result.resultKey;
            if (model) button.dataset.modelId = model.id;
            else button.dataset.conditionKey = result.conditionKey;
            button.setAttribute('aria-label', `Open results for ${result.family} ${result.displayName}`);
            button.setAttribute('aria-describedby', tooltip.id);
            button.addEventListener('mouseenter', () => {
                if (canShowPointerDetail(button)) {
                    if (model) showQuickDetail(button, model);
                    else showBiasDetail(button, result);
                }
            });
            button.addEventListener('mouseleave', () => hideQuickDetailFor(button, true));
            button.addEventListener('focus', () => {
                if (model) showQuickDetail(button, model);
                else showBiasDetail(button, result);
            });
            button.addEventListener('blur', () => hideQuickDetailFor(button));
            button.addEventListener('click', () => openBenchmarkRow(result, button));
            row.prepend(button);
        });
    }

    function initializeUnifiedBenchmark() {
        if (!extensionData) {
            enhanceMainResults();
            return;
        }
        const positiveCount = mainModelRows.filter((row) => row.gap > 0).length;
        benchmarkHeading.textContent = `${positiveCount} of ${mainModelRows.length} models are more accurate on intervention-truth cases.`;
        benchmarkDescription.textContent = 'Each model appears once. Only families with more than ten models are split; within each panel, older generations appear first and lower-capability models precede stronger peers.';
        benchmarkChart.innerHTML = [
            benchmarkGroupMarkup(mainModelRows, [
                'openai-compact', 'openai-flagship', 'claude', 'gemini', 'grok',
            ], 'Closed and hosted models'),
            benchmarkGroupMarkup(mainModelRows, [
                'llama', 'qwen-compact', 'qwen-large',
            ], 'Open-weight models'),
        ].join('');
        benchmarkChart.dataset.modelCount = String(mainModelRows.length);
        benchmarkChart.dataset.positiveGapCount = String(positiveCount);
        benchmarkChart.dataset.order = 'capability-groups';
        enhanceMainResults();
    }

    function renderBiasMap() {
        const ordered = [...mainModelRows].sort((first, second) => (
            first.bias - second.bias
            || `${first.family} ${first.displayName}`.localeCompare(`${second.family} ${second.displayName}`)
        ));
        const biasBound = 20;
        const gapBound = Math.max(10, Math.ceil((Math.max(...ordered.map((row) => Math.abs(row.gap))) + 1) / 5) * 5);
        const lanePositions = [50, 38, 62, 26, 74, 14, 86, 44, 56, 32, 68, 20, 80];
        const laneLastX = lanePositions.map(() => -Infinity);
        const markers = ordered.map((row) => {
            const x = 4 + ((row.bias + biasBound) / (biasBound * 2)) * 92;
            let lane = laneLastX.findIndex((lastX) => x - lastX >= 3.6);
            if (lane < 0) lane = laneLastX.indexOf(Math.min(...laneLastX));
            laneLastX[lane] = x;
            const style = FAMILY_STYLES[row.family];
            const modelName = `${row.family} ${row.displayName}`;
            return `<button type="button" class="bias-data-marker bias-map-marker family-marker-${style.marker} is-family-idle"
                style="--bias-x:${x}%;--bias-y:${lanePositions[lane]}%;--family-color:${style.color}"
                data-result-key="${escapeHtml(row.resultKey)}" data-family="${escapeHtml(row.family)}"
                aria-label="${escapeHtml(`${modelName}, B dir ${formatSigned(row.bias)}, ${biasDirection(row.bias)}.`)}"></button>`;
        }).join('');
        const scatterMarkers = ordered.map((row) => {
            const x = 6 + ((row.gap + gapBound) / (gapBound * 2)) * 88;
            const y = 8 + ((biasBound - row.bias) / (biasBound * 2)) * 84;
            const style = FAMILY_STYLES[row.family];
            const modelName = `${row.family} ${row.displayName}`;
            return `<button type="button" class="bias-data-marker bias-scatter-marker family-marker-${style.marker} is-family-idle"
                style="--scatter-x:${x}%;--scatter-y:${y}%;--family-color:${style.color}"
                data-result-key="${escapeHtml(row.resultKey)}" data-family="${escapeHtml(row.family)}"
                aria-label="${escapeHtml(`${modelName}, accuracy gap ${formatSigned(row.gap)} percentage points, B dir ${formatSigned(row.bias)}.`)}"></button>`;
        }).join('');
        const legend = BENCHMARK_FAMILY_ORDER.map((family) => {
            const style = FAMILY_STYLES[family];
            return `<button type="button" class="bias-family-filter" data-bias-family="${escapeHtml(family)}" aria-pressed="false" style="--family-color:${style.color}">
                <i class="bias-legend-marker family-marker-${style.marker}" aria-hidden="true"></i>${escapeHtml(family)}</button>`;
        }).join('');
        const gapHalf = gapBound / 2;
        biasMap.innerHTML = `
            <div class="bias-map-scroll" tabindex="0" role="region" aria-label="Error-direction bias scores for ${ordered.length} models">
                <div class="bias-map-plot">
                    <div class="bias-map-direction" aria-hidden="true"><span>Market-oriented</span><span>Intervention-oriented</span></div>
                    <div class="bias-map-axis" aria-hidden="true"><span>−20</span><span>−10</span><span>0</span><span>+10</span><span>+20</span></div>
                    <div class="bias-map-line" aria-hidden="true"></div>
                    ${markers}
                </div>
            </div>
            <div class="bias-map-legend" role="group" aria-label="Highlight a model family">${legend}</div>
            <section class="bias-scatter-panel" aria-labelledby="bias-scatter-title">
                <header>
                    <h4 id="bias-scatter-title">Accuracy gap × error-direction bias</h4>
                    <p>Each marker is one model. Use the family controls above to highlight a series.</p>
                </header>
                <div class="bias-scatter-scroll" tabindex="0" role="region" aria-label="Accuracy gap versus error-direction bias for ${ordered.length} models">
                    <div class="bias-scatter-plot">
                        <span class="bias-scatter-axis-label is-y" aria-hidden="true">B<sub>dir</sub></span>
                        <span class="bias-scatter-axis-label is-x" aria-hidden="true">Accuracy gap</span>
                        <div class="bias-scatter-zero is-horizontal" aria-hidden="true"></div>
                        <div class="bias-scatter-zero is-vertical" aria-hidden="true"></div>
                        <div class="bias-scatter-y-ticks" aria-hidden="true"><span>+${biasBound}</span><span>0</span><span>−${biasBound}</span></div>
                        <div class="bias-scatter-x-ticks" aria-hidden="true"><span>−${gapBound}</span><span>−${gapHalf}</span><span>0</span><span>+${gapHalf}</span><span>+${gapBound}</span></div>
                        ${scatterMarkers}
                    </div>
                </div>
            </section>`;
        biasMap.dataset.modelCount = String(ordered.length);
        biasMap.dataset.domain = '-20,20';
        biasMap.dataset.scatterDomain = `${-gapBound},${gapBound};${-biasBound},${biasBound}`;

        function applyFamilyHighlight(family = null) {
            biasMap.dataset.activeFamily = family || '';
            biasMap.querySelectorAll('.bias-family-filter').forEach((button) => {
                button.setAttribute('aria-pressed', String(button.dataset.biasFamily === family));
            });
            biasMap.querySelectorAll('.bias-data-marker').forEach((marker) => {
                const selected = family && marker.dataset.family === family;
                marker.classList.toggle('is-family-highlighted', Boolean(selected));
                marker.classList.toggle('is-family-muted', Boolean(family && !selected));
                marker.classList.toggle('is-family-idle', !family);
            });
        }

        biasMap.querySelectorAll('.bias-family-filter').forEach((button) => {
            button.addEventListener('click', () => {
                const next = biasMap.dataset.activeFamily === button.dataset.biasFamily
                    ? null
                    : button.dataset.biasFamily;
                applyFamilyHighlight(next);
            });
        });

        biasMap.querySelectorAll('.bias-data-marker').forEach((button) => {
            const row = mainRowsByResultKey.get(button.dataset.resultKey);
            button.setAttribute('aria-describedby', tooltip.id);
            button.addEventListener('mouseenter', () => {
                if (canShowPointerDetail(button)) showBiasDetail(button, row);
            });
            button.addEventListener('mouseleave', () => hideQuickDetailFor(button, true));
            button.addEventListener('focus', () => showBiasDetail(button, row));
            button.addEventListener('blur', () => hideQuickDetailFor(button));
            button.addEventListener('click', () => openBenchmarkRow(row, button));
        });
        biasMap.querySelectorAll('.bias-map-scroll, .bias-scatter-scroll').forEach((scroller) => {
            scroller.addEventListener('scroll', () => {
                const context = quickDetailContext;
                if (context?.row && document.activeElement === context.trigger) {
                    window.requestAnimationFrame(() => showBiasDetail(context.trigger, context.row));
                } else {
                    hideQuickDetail();
                }
            }, { passive: true });
        });
        applyFamilyHighlight();
    }

    function renderAggregateSubfieldDetail(row) {
        if (!row) {
            aggregateSubfieldDetail.hidden = true;
            aggregateSubfieldDetail.replaceChildren();
            return;
        }
        const name = row.dataset.subfieldName;
        const sampleSize = Number(row.dataset.sampleSize);
        const interventionAccuracy = Number(row.dataset.interventionAccuracy);
        const marketAccuracy = Number(row.dataset.marketAccuracy);
        const gap = Number(row.dataset.gap);
        aggregateSubfieldDetail.hidden = false;
        aggregateSubfieldDetail.innerHTML = `
            <span class="subfield-detail-kicker">Selected subfield</span>
            <strong>${escapeHtml(name)}</strong>
            <dl>
                <div><dt>Directional cases</dt><dd>n=${escapeHtml(sampleSize)}</dd></div>
                        <div class="is-intervention"><dt>Intervention-truth</dt><dd>${formatPercent(interventionAccuracy)}</dd></div>
                        <div class="is-market"><dt>Market-truth</dt><dd>${formatPercent(marketAccuracy)}</dd></div>
                <div class="${signedTone(gap)}"><dt>Accuracy gap</dt><dd>${escapeHtml(formatSigned(gap, ' pp'))}</dd></div>
            </dl>`;
    }

    function initializeAggregateSubfields() {
        aggregateSubfieldRows.forEach((row) => {
            const name = row.dataset.subfieldName;
            const gap = Number(row.dataset.gap);
            row.setAttribute('aria-label', `${name}: accuracy gap ${formatSigned(gap, ' percentage points')}. Show subfield detail.`);
            row.addEventListener('click', () => {
                const nextPinned = pinnedSubfieldRow === row ? null : row;
                aggregateSubfieldRows.forEach((candidate) => {
                    const selected = candidate === nextPinned;
                    candidate.classList.toggle('is-pinned', selected);
                    candidate.setAttribute('aria-expanded', String(selected));
                });
                pinnedSubfieldRow = nextPinned;
                renderAggregateSubfieldDetail(pinnedSubfieldRow);
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

    initializeUnifiedBenchmark();
    if (extensionData) renderReasoningExplorer(extensionData);
    renderBiasMap();
    initializeAggregateSubfields();

    window.addEventListener('scroll', () => {
        const context = quickDetailContext;
        if (context && document.activeElement === context.trigger && context.model) {
            showQuickDetail(context.trigger, context.model, context.releaseView);
        } else if (context && document.activeElement === context.trigger && context.row) {
            showBiasDetail(context.trigger, context.row);
        } else {
            hideQuickDetail();
        }
    }, { passive: true });
}
