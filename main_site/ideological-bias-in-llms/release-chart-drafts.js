const PAPER_URL = new URL('./data/paper-data.v2.json?v=20260812b', import.meta.url);
const RESULTS_URL = new URL('./data/website-experiment-results.v1.json?v=20260812b', import.meta.url);
const SVG_NS = 'http://www.w3.org/2000/svg';
const EXCLUDED_CONDITIONS = new Set([
    'oa_gpt5_nano_minimal',
    'oa_gpt5_mini_minimal',
    'an_sonnet46_disabled_low',
    'an_opus46_disabled_low',
    'gg_gemini3_minimal',
]);
const FAMILIES = ['OpenAI', 'Claude', 'Gemini', 'Grok', 'Llama', 'Qwen'];
const COLORS = {
    OpenAI: '#005eb8',
    Claude: '#7857b8',
    Gemini: '#00877c',
    Grok: '#d36a20',
    Llama: '#aa3f63',
    Qwen: '#4d70ae',
};
const POSITIVE = '#0b887c';
const NEGATIVE = '#d56816';
const tooltip = document.getElementById('draft-tooltip');

function svgElement(tag, attributes = {}, text = '') {
    const element = document.createElementNS(SVG_NS, tag);
    Object.entries(attributes).forEach(([name, value]) => element.setAttribute(name, String(value)));
    if (text) element.textContent = text;
    return element;
}

function shortName(family, name) {
    const prefixes = { Claude: /^Claude\s+/, Gemini: /^Gemini\s+/, Grok: /^Grok\s+/, Llama: /^Llama\s+/, Qwen: /^Qwen\s+/ };
    return prefixes[family] ? name.replace(prefixes[family], '') : name;
}

function normalizeRows(paper, experiments) {
    const paperRows = paper.models.map((model) => ({
        key: `paper:${model.id}`,
        family: model.family,
        name: shortName(model.family, model.display_name),
        releaseDate: model.release_date,
        date: Date.parse(`${model.release_date}T00:00:00Z`),
        gap: Number(model.overview.accuracy_gap_pp),
        source: 'camera-ready',
    }));
    const experimentRows = experiments.main_benchmark.results
        .filter((result) => !EXCLUDED_CONDITIONS.has(result.condition_key))
        .map((result) => {
            const family = result.family === 'GPT' ? 'OpenAI' : result.family;
            return {
                key: `new:${result.condition_key}`,
                family,
                name: shortName(family, result.display_name),
                releaseDate: result.release_date,
                date: Date.parse(`${result.release_date}T00:00:00Z`),
                gap: Number(result.metrics.accuracy_gap_pp),
                source: 'updated evaluation',
            };
        });
    const rows = [...paperRows, ...experimentRows]
        .sort((first, second) => first.date - second.date || first.family.localeCompare(second.family) || first.name.localeCompare(second.name));
    if (rows.length !== 47 || new Set(rows.map((row) => row.key)).size !== 47) {
        throw new Error(`Unexpected Figure 1 draft data: ${rows.length} rows.`);
    }
    const familyCounts = Object.fromEntries(FAMILIES.map((family) => [family, rows.filter((row) => row.family === family).length]));
    const expectedCounts = { OpenAI: 12, Claude: 8, Gemini: 5, Grok: 6, Llama: 5, Qwen: 11 };
    if (JSON.stringify(familyCounts) !== JSON.stringify(expectedCounts)) {
        throw new Error(`Unexpected family counts: ${JSON.stringify(familyCounts)}.`);
    }
    return rows;
}

function signed(value) {
    const number = Number(value);
    return `${number > 0 ? '+' : number < 0 ? '−' : ''}${Math.abs(number).toFixed(1)} pp`;
}

function displayDate(value) {
    return new Intl.DateTimeFormat('en', { year: 'numeric', month: 'short', day: 'numeric', timeZone: 'UTC' })
        .format(new Date(`${value}T00:00:00Z`));
}

function showTooltip(row, anchor) {
    tooltip.innerHTML = `<strong>${row.family} ${row.name}</strong><span>${displayDate(row.releaseDate)}</span><span>Accuracy gap: <b>${signed(row.gap)}</b></span>`;
    tooltip.hidden = false;
    const rect = anchor.getBoundingClientRect();
    const box = tooltip.getBoundingClientRect();
    let left = rect.left + rect.width / 2 + 13;
    let top = rect.top + rect.height / 2 - box.height - 12;
    if (left + box.width > window.innerWidth - 8) left = rect.left - box.width - 10;
    if (top < 8) top = rect.bottom + 10;
    tooltip.style.left = `${Math.max(8, left)}px`;
    tooltip.style.top = `${Math.max(8, top)}px`;
}

function hideTooltip() {
    tooltip.hidden = true;
}

function bindTooltip(target, row) {
    target.setAttribute('tabindex', '0');
    target.setAttribute('role', 'img');
    target.setAttribute('aria-label', `${row.family} ${row.name}, released ${displayDate(row.releaseDate)}, accuracy gap ${signed(row.gap)}.`);
    target.addEventListener('pointerenter', () => showTooltip(row, target));
    target.addEventListener('pointerleave', hideTooltip);
    target.addEventListener('focus', () => showTooltip(row, target));
    target.addEventListener('blur', hideTooltip);
}

function addSvgPoint(parent, row, x, y, options = {}) {
    const group = svgElement('g', {
        class: `chart-point ${options.className || ''}`.trim(),
        'data-result-key': row.key,
        'data-family': row.family,
    });
    const radius = options.radius || 5.5;
    group.appendChild(svgElement('circle', {
        class: 'point-shape', cx: x, cy: y, r: radius,
        fill: options.fill || COLORS[row.family],
        stroke: options.stroke || '#fff',
    }));
    bindTooltip(group, row);
    parent.appendChild(group);
    return group;
}

function extent(rows) {
    const day = 86400000;
    return {
        xMin: Math.min(...rows.map((row) => row.date)) - 32 * day,
        xMax: Math.max(...rows.map((row) => row.date)) + 32 * day,
        yMin: -5,
        yMax: 25,
    };
}

function scaleLinear(domainMin, domainMax, rangeMin, rangeMax) {
    return (value) => rangeMin + ((value - domainMin) / (domainMax - domainMin)) * (rangeMax - rangeMin);
}

function addYearTicks(svg, xScale, y, xMin, xMax, options = {}) {
    [2024, 2025, 2026].forEach((year) => {
        const timestamp = Date.parse(`${year}-07-01T00:00:00Z`);
        if (timestamp < xMin || timestamp > xMax) return;
        const x = xScale(timestamp);
        if (options.lines) svg.appendChild(svgElement('line', { x1: x, x2: x, y1: options.top, y2: options.bottom, class: 'chart-grid' }));
        svg.appendChild(svgElement('text', { x, y, 'text-anchor': 'middle', class: 'chart-axis-label' }, String(year)));
    });
}

function createSvg(target, width, height, label) {
    const svg = svgElement('svg', { viewBox: `0 0 ${width} ${height}`, width, height, 'aria-label': label, role: 'img' });
    svg.appendChild(svgElement('rect', { width, height, class: 'chart-bg' }));
    target.replaceChildren(svg);
    return svg;
}

function renderSmallMultiples(rows) {
    const width = 1050;
    const height = 650;
    const svg = createSvg(document.getElementById('chart-small-multiples'), width, height, 'Accuracy gap over release date, split into six model-family panels.');
    const bounds = extent(rows);
    const columns = 3;
    const outer = { left: 44, right: 24, top: 24, bottom: 26 };
    const gapX = 18;
    const gapY = 18;
    const panelWidth = (width - outer.left - outer.right - gapX * 2) / 3;
    const panelHeight = (height - outer.top - outer.bottom - gapY) / 2;
    FAMILIES.forEach((family, index) => {
        const column = index % columns;
        const rowIndex = Math.floor(index / columns);
        const left = outer.left + column * (panelWidth + gapX);
        const top = outer.top + rowIndex * (panelHeight + gapY);
        const plot = { left: left + 38, right: left + panelWidth - 14, top: top + 42, bottom: top + panelHeight - 30 };
        const xScale = scaleLinear(bounds.xMin, bounds.xMax, plot.left, plot.right);
        const yScale = scaleLinear(bounds.yMin, bounds.yMax, plot.bottom, plot.top);
        svg.appendChild(svgElement('rect', { x: left, y: top, width: panelWidth, height: panelHeight, rx: 13, class: 'chart-panel' }));
        svg.appendChild(svgElement('text', { x: left + 16, y: top + 23, class: 'chart-family-title' }, family));
        const familyRows = rows.filter((item) => item.family === family);
        svg.appendChild(svgElement('text', { x: left + panelWidth - 16, y: top + 23, 'text-anchor': 'end', class: 'chart-family-count' }, `${familyRows.length} models`));
        [0, 10, 20].forEach((tick) => {
            const y = yScale(tick);
            svg.appendChild(svgElement('line', { x1: plot.left, x2: plot.right, y1: y, y2: y, class: tick === 0 ? 'chart-zero' : 'chart-grid' }));
            if (column === 0) svg.appendChild(svgElement('text', { x: plot.left - 7, y: y + 4, 'text-anchor': 'end', class: 'chart-axis-label' }, tick === 0 ? '0' : `+${tick}`));
        });
        addYearTicks(svg, xScale, plot.bottom + 19, bounds.xMin, bounds.xMax);
        const points = familyRows.map((item) => [xScale(item.date), yScale(item.gap)]);
        svg.appendChild(svgElement('polyline', { points: points.map((point) => point.join(',')).join(' '), class: 'chart-family-line', stroke: COLORS[family] }));
        familyRows.forEach((item, itemIndex) => {
            const point = addSvgPoint(svg, item, points[itemIndex][0], points[itemIndex][1], { radius: 5 });
            if (itemIndex === familyRows.length - 1) {
                point.querySelector('.point-shape').setAttribute('stroke', '#17243a');
                point.querySelector('.point-shape').setAttribute('stroke-width', '2.5');
            }
        });
    });
}

function dateClusterOffsets(familyRows) {
    const byDate = new Map();
    familyRows.forEach((row) => {
        if (!byDate.has(row.releaseDate)) byDate.set(row.releaseDate, []);
        byDate.get(row.releaseDate).push(row);
    });
    const offsets = new Map();
    byDate.forEach((cluster) => {
        cluster.forEach((row, index) => offsets.set(row.key, (index - (cluster.length - 1) / 2) * 5));
    });
    return offsets;
}

function renderSignalLanes(rows) {
    const width = 1050;
    const height = 570;
    const svg = createSvg(document.getElementById('chart-signal-lanes'), width, height, 'Six family release lanes with accuracy-gap stems above and below each lane.');
    const bounds = extent(rows);
    const xScale = scaleLinear(bounds.xMin, bounds.xMax, 158, 1018);
    const maxMagnitude = 25;
    svg.appendChild(svgElement('text', { x: 158, y: 27, class: 'chart-axis-label' }, 'Market-truth advantage ↓'));
    svg.appendChild(svgElement('text', { x: 1018, y: 27, 'text-anchor': 'end', class: 'chart-axis-label' }, '↑ Intervention-truth advantage'));
    addYearTicks(svg, xScale, height - 14, bounds.xMin, bounds.xMax, { lines: true, top: 36, bottom: height - 38 });
    FAMILIES.forEach((family, index) => {
        const center = 72 + index * 78;
        const familyRows = rows.filter((row) => row.family === family);
        const offsets = dateClusterOffsets(familyRows);
        svg.appendChild(svgElement('rect', { x: 148, y: center - 35, width: 880, height: 35, class: 'chart-lane-bg-positive' }));
        svg.appendChild(svgElement('rect', { x: 148, y: center, width: 880, height: 35, class: 'chart-lane-bg-negative' }));
        svg.appendChild(svgElement('line', { x1: 148, x2: 1028, y1: center, y2: center, class: 'chart-zero' }));
        svg.appendChild(svgElement('text', { x: 20, y: center - 3, class: 'chart-family-title' }, family));
        svg.appendChild(svgElement('text', { x: 20, y: center + 13, class: 'chart-family-count' }, `${familyRows.length} releases`));
        familyRows.forEach((row) => {
            const x = xScale(row.date) + offsets.get(row.key);
            const y = center - (row.gap / maxMagnitude) * 34;
            svg.appendChild(svgElement('line', { x1: x, x2: x, y1: center, y2: y, class: 'chart-stem', stroke: row.gap >= 0 ? POSITIVE : NEGATIVE }));
            addSvgPoint(svg, row, x, y, { radius: 5.5, fill: row.gap >= 0 ? POSITIVE : NEGATIVE, stroke: COLORS[family] });
        });
    });
}

function renderConstellation(rows) {
    const width = 1050;
    const height = 510;
    const svg = createSvg(document.getElementById('chart-constellation'), width, height, 'Release constellation: model family by release date, with dot area encoding the absolute gap.');
    const bounds = extent(rows);
    const xScale = scaleLinear(bounds.xMin, bounds.xMax, 155, 1018);
    [2024, 2025, 2026].forEach((year, index) => {
        const start = Math.max(bounds.xMin, Date.parse(`${year}-01-01T00:00:00Z`));
        const end = Math.min(bounds.xMax, Date.parse(`${year + 1}-01-01T00:00:00Z`));
        svg.appendChild(svgElement('rect', { x: xScale(start), y: 45, width: Math.max(0, xScale(end) - xScale(start)), height: 405, class: `chart-year-band${index % 2 ? ' is-alt' : ''}` }));
        svg.appendChild(svgElement('text', { x: (xScale(start) + xScale(end)) / 2, y: 29, 'text-anchor': 'middle', class: 'chart-year-title' }, String(year)));
    });
    FAMILIES.forEach((family, index) => {
        const center = 82 + index * 66;
        const familyRows = rows.filter((row) => row.family === family);
        const byDate = new Map();
        familyRows.forEach((row) => {
            if (!byDate.has(row.releaseDate)) byDate.set(row.releaseDate, []);
            byDate.get(row.releaseDate).push(row);
        });
        svg.appendChild(svgElement('line', { x1: 145, x2: 1028, y1: center, y2: center, class: 'chart-grid' }));
        svg.appendChild(svgElement('text', { x: 18, y: center + 5, class: 'chart-family-title' }, family));
        byDate.forEach((cluster) => {
            cluster.forEach((row, clusterIndex) => {
                const y = center + (clusterIndex - (cluster.length - 1) / 2) * 12;
                const radius = 4.5 + Math.sqrt(Math.abs(row.gap)) * 1.25;
                addSvgPoint(svg, row, xScale(row.date), y, { radius, fill: row.gap >= 0 ? POSITIVE : NEGATIVE, stroke: COLORS[family] });
            });
        });
    });
    svg.appendChild(svgElement('circle', { cx: 805, cy: 480, r: 5, fill: POSITIVE }));
    svg.appendChild(svgElement('text', { x: 816, y: 484, class: 'chart-axis-label' }, 'Intervention advantage'));
    svg.appendChild(svgElement('circle', { cx: 928, cy: 480, r: 5, fill: NEGATIVE }));
    svg.appendChild(svgElement('text', { x: 939, y: 484, class: 'chart-axis-label' }, 'Market advantage'));
}

function eraFor(row) {
    if (row.releaseDate < '2025-01-01') return '2024 H2';
    if (row.releaseDate < '2025-07-01') return '2025 H1';
    if (row.releaseDate < '2026-01-01') return '2025 H2';
    if (row.releaseDate < '2026-04-01') return '2026 Q1';
    if (row.releaseDate < '2026-07-01') return '2026 Q2';
    return '2026 Q3';
}

function renderEraCards(rows) {
    const target = document.getElementById('chart-era-cards');
    const eras = ['2024 H2', '2025 H1', '2025 H2', '2026 Q1', '2026 Q2', '2026 Q3'];
    const board = document.createElement('div');
    board.className = 'era-board';
    eras.forEach((era) => {
        const eraRows = rows.filter((row) => eraFor(row) === era);
        const column = document.createElement('section');
        column.className = 'era-column';
        column.innerHTML = `<header><h3>${era}</h3><span>${eraRows.length} models</span></header><div class="era-models"></div>`;
        const modelList = column.querySelector('.era-models');
        eraRows.forEach((row) => {
            const width = Math.min(50, (Math.abs(row.gap) / 25) * 50);
            const model = document.createElement('div');
            model.className = 'era-model';
            model.tabIndex = 0;
            model.style.setProperty('--family-color', COLORS[row.family]);
            model.style.setProperty('--gap-color', row.gap >= 0 ? POSITIVE : NEGATIVE);
            model.innerHTML = `<div><span class="era-model-name">${row.name}</span><span class="era-model-meta">${row.family} · ${row.releaseDate.slice(5)}</span></div><div class="era-gap"><strong>${signed(row.gap)}</strong><div class="era-track"><span class="era-fill" style="left:${row.gap >= 0 ? 50 : 50 - width}%;width:${width}%"></span></div></div>`;
            bindTooltip(model, row);
            modelList.appendChild(model);
        });
        board.appendChild(column);
    });
    target.replaceChildren(board);
}

function renderFocusChart(rows) {
    const width = 1050;
    const height = 520;
    const svg = createSvg(document.getElementById('chart-focus'), width, height, 'Release-date and accuracy-gap plot with selectable family focus.');
    const bounds = extent(rows);
    const plot = { left: 72, right: 1022, top: 32, bottom: 466 };
    const xScale = scaleLinear(bounds.xMin, bounds.xMax, plot.left, plot.right);
    const yScale = scaleLinear(bounds.yMin, bounds.yMax, plot.bottom, plot.top);
    [0, 5, 10, 15, 20, 25].forEach((tick) => {
        const y = yScale(tick);
        svg.appendChild(svgElement('line', { x1: plot.left, x2: plot.right, y1: y, y2: y, class: tick === 0 ? 'chart-zero' : 'chart-grid' }));
        svg.appendChild(svgElement('text', { x: plot.left - 9, y: y + 4, 'text-anchor': 'end', class: 'chart-axis-label' }, tick > 0 ? `+${tick}` : '0'));
    });
    addYearTicks(svg, xScale, 496, bounds.xMin, bounds.xMax, { lines: true, top: plot.top, bottom: plot.bottom });
    FAMILIES.forEach((family) => {
        const familyRows = rows.filter((row) => row.family === family);
        const line = svgElement('polyline', {
            points: familyRows.map((row) => `${xScale(row.date)},${yScale(row.gap)}`).join(' '),
            class: 'chart-family-line focus-line',
            stroke: COLORS[family],
            'data-family': family,
        });
        svg.appendChild(line);
        familyRows.forEach((row) => {
            const x = xScale(row.date);
            const y = yScale(row.gap);
            addSvgPoint(svg, row, x, y, { className: 'focus-point', radius: 5.5, fill: COLORS[family] });
            const label = svgElement('text', { x: x + 7, y: y - 7, class: 'chart-model-label focus-label', 'data-family': family }, row.name);
            svg.appendChild(label);
        });
    });
    const toolbar = document.getElementById('focus-toolbar');
    const controls = ['All', ...FAMILIES].map((family) => {
        const button = document.createElement('button');
        button.type = 'button';
        button.className = 'focus-chip';
        button.textContent = family === 'All' ? 'All models' : family;
        button.dataset.family = family;
        button.style.setProperty('--chip-color', family === 'All' ? '#526077' : COLORS[family]);
        button.setAttribute('aria-pressed', String(family === 'All'));
        return button;
    });
    const setFamily = (selected) => {
        controls.forEach((button) => button.setAttribute('aria-pressed', String(button.dataset.family === selected)));
        svg.querySelectorAll('.focus-point').forEach((point) => point.classList.toggle('is-active', selected === 'All' || point.dataset.family === selected));
        svg.querySelectorAll('.focus-line').forEach((line) => line.classList.toggle('is-active', selected !== 'All' && line.dataset.family === selected));
        svg.querySelectorAll('.focus-label').forEach((label) => label.classList.toggle('is-active', selected !== 'All' && label.dataset.family === selected));
    };
    controls.forEach((button) => {
        button.addEventListener('click', () => setFamily(button.dataset.family));
        toolbar.appendChild(button);
    });
    setFamily('All');
}

async function initialize() {
    const [paperResponse, resultResponse] = await Promise.all([fetch(PAPER_URL), fetch(RESULTS_URL)]);
    if (!paperResponse.ok || !resultResponse.ok) throw new Error('Could not load frozen paper-page data.');
    const rows = normalizeRows(await paperResponse.json(), await resultResponse.json());
    document.getElementById('model-count').textContent = String(rows.length);
    renderSmallMultiples(rows);
    renderSignalLanes(rows);
    renderConstellation(rows);
    renderEraCards(rows);
    renderFocusChart(rows);
    document.body.dataset.draftsReady = 'true';
    document.body.dataset.modelCount = String(rows.length);
    document.body.dataset.draftCount = '5';
}

initialize().catch((error) => {
    console.error(error);
    document.body.dataset.draftsReady = 'error';
    document.querySelector('main').innerHTML = '<p role="alert">The frozen Figure 1 data could not be loaded.</p>';
});
