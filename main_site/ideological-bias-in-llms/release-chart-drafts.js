const PAPER_URL = new URL('./data/paper-data.v2.json?v=20260813a', import.meta.url);
const RESULTS_URL = new URL('./data/website-experiment-results.v1.json?v=20260813a', import.meta.url);
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
            };
        });
    const rows = [...paperRows, ...experimentRows]
        .sort((first, second) => first.date - second.date || first.family.localeCompare(second.family) || first.name.localeCompare(second.name));
    if (!rows.length || new Set(rows.map((row) => row.key)).size !== rows.length) {
        throw new Error('The selected Figure 1 data are empty or contain duplicate models.');
    }
    if (rows.some((row) => !FAMILIES.includes(row.family) || !Number.isFinite(row.date) || !Number.isFinite(row.gap))) {
        throw new Error('The selected Figure 1 data contain an invalid family, release date, or metric.');
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
    tooltip.innerHTML = `<strong>${row.family} ${row.name}</strong><span>${displayDate(row.releaseDate)}</span><span>Left-Advantage Score: <b>${signed(row.gap)}</b></span>`;
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

function bindTooltip(target, row) {
    target.setAttribute('tabindex', '0');
    target.setAttribute('role', 'img');
    target.setAttribute('aria-label', `${row.family} ${row.name}, released ${displayDate(row.releaseDate)}, Left-Advantage Score ${signed(row.gap)}.`);
    target.addEventListener('pointerenter', () => showTooltip(row, target));
    target.addEventListener('pointerleave', () => { tooltip.hidden = true; });
    target.addEventListener('focus', () => showTooltip(row, target));
    target.addEventListener('blur', () => { tooltip.hidden = true; });
}

function scaleLinear(domainMin, domainMax, rangeMin, rangeMax) {
    return (value) => rangeMin + ((value - domainMin) / (domainMax - domainMin)) * (rangeMax - rangeMin);
}

function renderFocusChart(rows) {
    const width = 1050;
    const height = 520;
    const target = document.getElementById('chart-focus');
    const svg = svgElement('svg', { viewBox: `0 0 ${width} ${height}`, width, height, role: 'img', 'aria-label': 'Release-date and Left-Advantage Score plot with selectable family focus.' });
    svg.appendChild(svgElement('rect', { width, height, class: 'chart-bg' }));
    target.replaceChildren(svg);
    const day = 86400000;
    const xMin = Math.min(...rows.map((row) => row.date)) - 32 * day;
    const xMax = Math.max(...rows.map((row) => row.date)) + 32 * day;
    const gapValues = rows.map((row) => row.gap);
    const yMin = Math.floor(Math.min(-5, ...gapValues) / 5) * 5;
    const yMax = Math.ceil(Math.max(5, ...gapValues) / 5) * 5;
    const plot = { left: 72, right: 1022, top: 32, bottom: 466 };
    const xScale = scaleLinear(xMin, xMax, plot.left, plot.right);
    const yScale = scaleLinear(yMin, yMax, plot.bottom, plot.top);

    for (let tick = yMin; tick <= yMax; tick += 5) {
        const y = yScale(tick);
        svg.appendChild(svgElement('line', { x1: plot.left, x2: plot.right, y1: y, y2: y, class: tick === 0 ? 'chart-zero' : 'chart-grid' }));
        svg.appendChild(svgElement('text', { x: plot.left - 9, y: y + 4, 'text-anchor': 'end', class: 'chart-axis-label' }, tick > 0 ? `+${tick}` : String(tick)));
    }
    [2024, 2025, 2026].forEach((year) => {
        const timestamp = Date.parse(`${year}-07-01T00:00:00Z`);
        if (timestamp < xMin || timestamp > xMax) return;
        const x = xScale(timestamp);
        svg.appendChild(svgElement('line', { x1: x, x2: x, y1: plot.top, y2: plot.bottom, class: 'chart-grid' }));
        svg.appendChild(svgElement('text', { x, y: 496, 'text-anchor': 'middle', class: 'chart-axis-label' }, String(year)));
    });

    FAMILIES.forEach((family) => {
        const familyRows = rows.filter((row) => row.family === family);
        svg.appendChild(svgElement('polyline', {
            points: familyRows.map((row) => `${xScale(row.date)},${yScale(row.gap)}`).join(' '),
            class: 'chart-family-line focus-line',
            stroke: COLORS[family],
            'data-family': family,
        }));
        familyRows.forEach((row) => {
            const x = xScale(row.date);
            const y = yScale(row.gap);
            const point = svgElement('g', { class: 'chart-point focus-point', 'data-family': family });
            point.appendChild(svgElement('circle', { class: 'point-shape', cx: x, cy: y, r: 5.5, fill: COLORS[family], stroke: '#fff' }));
            bindTooltip(point, row);
            svg.appendChild(point);
            svg.appendChild(svgElement('text', { x: x + 7, y: y - 7, class: 'chart-model-label focus-label', 'data-family': family }, row.name));
        });
    });

    const toolbar = document.getElementById('focus-toolbar');
    toolbar.replaceChildren();
    const controls = ['All', ...FAMILIES].map((family) => {
        const button = document.createElement('button');
        button.type = 'button';
        button.className = 'focus-chip';
        button.textContent = family === 'All' ? 'All models' : family;
        button.dataset.family = family;
        button.style.setProperty('--chip-color', family === 'All' ? '#526077' : COLORS[family]);
        button.setAttribute('aria-pressed', String(family === 'All'));
        toolbar.appendChild(button);
        return button;
    });
    const setFamily = (selected) => {
        const overview = selected === 'All';
        controls.forEach((button) => button.setAttribute('aria-pressed', String(button.dataset.family === selected)));
        svg.querySelectorAll('.focus-point').forEach((point) => point.classList.toggle('is-active', overview || point.dataset.family === selected));
        svg.querySelectorAll('.focus-line').forEach((line) => {
            line.classList.toggle('is-overview', overview);
            line.classList.toggle('is-active', !overview && line.dataset.family === selected);
        });
        svg.querySelectorAll('.focus-label').forEach((label) => label.classList.toggle('is-active', !overview && label.dataset.family === selected));
    };
    controls.forEach((button) => button.addEventListener('click', () => setFamily(button.dataset.family)));
    setFamily('OpenAI');
}

async function initialize() {
    const [paperResponse, resultResponse] = await Promise.all([fetch(PAPER_URL), fetch(RESULTS_URL)]);
    if (!paperResponse.ok || !resultResponse.ok) throw new Error('Could not load frozen paper-page data.');
    const rows = normalizeRows(await paperResponse.json(), await resultResponse.json());
    document.getElementById('model-count').textContent = String(rows.length);
    renderFocusChart(rows);
    document.body.dataset.draftsReady = 'true';
    document.body.dataset.modelCount = String(rows.length);
    document.body.dataset.draftCount = '1';
}

initialize().catch((error) => {
    console.error(error);
    document.body.dataset.draftsReady = 'error';
    document.querySelector('main').innerHTML = '<p role="alert">The frozen Figure 1 data could not be loaded.</p>';
});
