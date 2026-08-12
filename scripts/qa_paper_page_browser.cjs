#!/usr/bin/env node
/* Optional browser QA. Install playwright-core and axe-core outside the repo, then set NODE_PATH. */

const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const { chromium } = require('playwright-core');
const axe = require('axe-core');

const baseUrl = process.env.PAPER_PAGE_URL || 'http://127.0.0.1:8765/ideological-bias-in-llms/';
const executablePath = process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE || '/snap/bin/chromium';
const screenshotDir = process.env.PAPER_QA_SCREENSHOT_DIR || '/tmp/econai-paper-page-qa';
const skipScreenshots = process.env.PAPER_QA_SKIP_SCREENSHOTS === '1';
const skipAxe = process.env.PAPER_QA_SKIP_AXE === '1';
const dataPath = path.join(__dirname, '../main_site/ideological-bias-in-llms/data/paper-data.v2.json');
const extensionDataPath = path.join(
    __dirname,
    '../main_site/ideological-bias-in-llms/data/website-experiment-results.v1.json',
);
const paperData = JSON.parse(fs.readFileSync(dataPath, 'utf8'));
const extensionData = JSON.parse(fs.readFileSync(extensionDataPath, 'utf8'));
const modelsById = new Map(paperData.models.map((model) => [model.id, model]));
const viewports = (process.env.PAPER_QA_VIEWPORTS || '320,375,768,1024,1440,1920')
    .split(',')
    .map((value) => Number(value.trim()))
    .filter((value) => Number.isFinite(value) && value > 0);

function one(value) {
    return Number(value).toFixed(1);
}

function signed(value, suffix = '') {
    const number = Number(value);
    const sign = number > 0 ? '+' : number < 0 ? '−' : '';
    return `${sign}${one(Math.abs(number))}${suffix}`;
}

function fullModelName(model) {
    return `${model.family} ${model.display_name}`;
}

function checkTouchTargets(metrics, label) {
    for (const target of metrics) {
        assert.ok(
            target.width >= 43.5 && target.height >= 43.5,
            `${label}: ${target.name} is ${target.width}×${target.height}, below 44px`,
        );
    }
}

async function waitForDialogClosed(page) {
    await page.waitForFunction(() => !document.querySelector('#model-detail-dialog').open);
}

async function closeDialog(page, method = 'button') {
    if (method === 'escape') {
        await page.keyboard.press('Escape');
    } else {
        await page.locator('[data-dialog-close]').click();
    }
    await waitForDialogClosed(page);
}

async function runAxe(page, label) {
    await page.addScriptTag({ content: axe.source });
    const violations = await page.evaluate(async () => {
        const results = await axe.run(document, {
            runOnly: { type: 'tag', values: ['wcag2a', 'wcag2aa', 'wcag21aa'] },
        });
        return results.violations
            .filter((violation) => ['serious', 'critical'].includes(violation.impact))
            .map((violation) => ({
                id: violation.id,
                impact: violation.impact,
                targets: violation.nodes.map((node) => node.target),
            }));
    });
    assert.deepEqual(violations, [], `${label} axe violations: ${JSON.stringify(violations)}`);
}

async function validateAggregateSubfields(page, width) {
    const rows = page.locator('.subfield-row');
    assert.equal(await rows.count(), 7, `${width}px aggregate subfield rows`);
    assert.equal(await page.locator('.subfield-panel').getAttribute('role'), 'region');

    const zeroGeometry = await page.evaluate(() => {
        const marketLabel = document.querySelector('.subfield-axis > span:first-child');
        const axisZero = document.querySelector('.subfield-axis > span:nth-child(2)');
        const interventionLabel = document.querySelector('.subfield-axis > span:last-child');
        const marketRect = marketLabel.getBoundingClientRect();
        const axisRect = axisZero.getBoundingClientRect();
        const interventionRect = interventionLabel.getBoundingClientRect();
        const rowCenters = [...document.querySelectorAll('.subfield-row .zero-line')].map((line) => {
            const rect = line.getBoundingClientRect();
            return rect.left + rect.width / 2;
        });
        return {
            axisVisible: axisZero.getClientRects().length > 0,
            axisCenter: axisRect.left + axisRect.width / 2,
            marketRight: marketRect.right,
            zeroLeft: axisRect.left,
            zeroRight: axisRect.right,
            interventionLeft: interventionRect.left,
            rowCenters,
            declaredZero: getComputedStyle(document.querySelector('.subfield-panel')).getPropertyValue('--zero-x').trim(),
        };
    });
    assert.ok(zeroGeometry.axisVisible, `${width}px zero label is hidden`);
    assert.ok(zeroGeometry.declaredZero, `${width}px shared --zero-x is missing`);
    assert.ok(
        zeroGeometry.marketRight <= zeroGeometry.zeroLeft - 3.5,
        `${width}px Market label overlaps zero by ${(zeroGeometry.marketRight - zeroGeometry.zeroLeft).toFixed(2)}px`,
    );
    assert.ok(
        zeroGeometry.interventionLeft >= zeroGeometry.zeroRight + 3.5,
        `${width}px Intervention label overlaps zero by ${(zeroGeometry.zeroRight - zeroGeometry.interventionLeft).toFixed(2)}px`,
    );
    for (const center of zeroGeometry.rowCenters) {
        assert.ok(
            Math.abs(center - zeroGeometry.axisCenter) < 1,
            `${width}px zero line and label differ by ${Math.abs(center - zeroGeometry.axisCenter).toFixed(3)}px`,
        );
    }

    const targetMetrics = await rows.evaluateAll((buttons) => buttons.map((button) => {
        const rect = button.getBoundingClientRect();
        return { name: button.dataset.subfieldName, width: rect.width, height: rect.height };
    }));
    checkTouchTargets(targetMetrics, `${width}px subfield controls`);

    const first = rows.first();
    const detail = page.locator('#subfield-detail');
    assert.equal(await detail.getAttribute('hidden'), '', `${width}px subfield detail starts visible`);
    assert.equal((await detail.innerText()).trim(), '', `${width}px hidden subfield detail is populated`);
    await first.focus();
    await first.hover();
    assert.equal(await detail.getAttribute('hidden'), '', `${width}px focus or hover opened subfield detail`);
    const expected = {
        name: await first.getAttribute('data-subfield-name'),
        sample: await first.getAttribute('data-sample-size'),
        intervention: one(await first.getAttribute('data-intervention-accuracy')),
        market: one(await first.getAttribute('data-market-accuracy')),
        gap: signed(await first.getAttribute('data-gap'), ' pp'),
    };
    if (width === 375) await first.tap();
    else await first.click();
    assert.equal(await first.getAttribute('aria-expanded'), 'true', `${width}px subfield pin state`);
    assert.equal(await detail.getAttribute('hidden'), null, `${width}px clicked detail remains hidden`);
    const selectedText = await detail.innerText();
    assert.match(selectedText, /Selected subfield/i);
    for (const value of [expected.name, `n=${expected.sample}`, `${expected.intervention}%`, `${expected.market}%`, expected.gap]) {
        assert.ok(selectedText.includes(value), `${width}px subfield detail is missing ${value}`);
    }
    const pinnedLayout = await detail.evaluate((element) => {
        const metrics = [...element.querySelectorAll('dl > div')];
        const tops = metrics.map((metric) => Math.round(metric.getBoundingClientRect().top));
        return {
            count: metrics.length,
            rows: new Set(tops).size,
            height: element.getBoundingClientRect().height,
            interventionColor: getComputedStyle(metrics[1].querySelector('dd')).color,
            marketColor: getComputedStyle(metrics[2].querySelector('dd')).color,
            gapColor: getComputedStyle(metrics[3].querySelector('dd')).color,
        };
    });
    assert.equal(pinnedLayout.count, 4);
    assert.equal(pinnedLayout.rows, width <= 680 ? 2 : 1, `${width}px aggregate metric grid rows`);
    assert.ok(pinnedLayout.height < 240, `${width}px pinned subfield detail is too tall`);
    assert.notEqual(pinnedLayout.interventionColor, pinnedLayout.marketColor);
    assert.notEqual(pinnedLayout.gapColor, pinnedLayout.marketColor);
    await first.focus();
    await page.keyboard.press('Escape');
    assert.equal(await first.getAttribute('aria-expanded'), 'false', `${width}px subfield Escape state`);
    assert.equal(await detail.getAttribute('hidden'), '', `${width}px Escape did not hide detail`);
    assert.equal((await detail.innerText()).trim(), '', `${width}px Escape left detail content`);
}

async function validateModelDialog(page, width) {
    const model = paperData.models[0];
    const trigger = page.locator(`.model-open-button[data-model-id="${model.id}"]`);
    await page.mouse.move(0, 0);
    await trigger.focus();
    await page.waitForFunction((expectedName) => {
        const detail = document.querySelector('#model-quick-detail');
        return !detail.hidden
            && detail.querySelector('header strong')?.textContent.trim() === expectedName
            && detail.querySelectorAll('.quick-detail-grid > div').length === 4;
    }, fullModelName(model));
    const quickDetail = page.locator('#model-quick-detail');
    assert.equal(await quickDetail.locator('.quick-detail-grid > div').count(), 4);
    const tooltipStyle = await quickDetail.evaluate((element) => {
        const style = getComputedStyle(element);
        return {
            top: parseFloat(style.paddingTop),
            right: parseFloat(style.paddingRight),
            bottom: parseFloat(style.paddingBottom),
            left: parseFloat(style.paddingLeft),
        };
    });
    assert.ok(Math.min(...Object.values(tooltipStyle)) >= 14, `${width}px quick tooltip padding is too small`);

    await trigger.press('Enter');
    const dialog = page.locator('#model-detail-dialog');
    await page.locator('#model-detail-dialog[open]').waitFor();
    assert.equal(await dialog.getAttribute('data-model-id'), model.id);
    assert.ok(await dialog.evaluate((element) => element.contains(document.activeElement)), `${width}px focus entered dialog`);
    assert.equal(await page.locator('[data-model-tab]').count(), 3, `${width}px dialog tab count`);
    assert.equal(await page.locator('[data-model-tab]:visible').count(), 3, `${width}px paper dialog did not restore all tabs`);
    assert.equal(await page.locator('#model-tab-icl, #model-panel-icl').count(), 0, `${width}px ICL UI remains`);
    assert.equal(await page.locator('#model-panel-overview .metric-card').count(), 6);
    const overviewText = await page.locator('#model-panel-overview').innerText();
    assert.match(overviewText, /Same-sign accuracy/);
    assert.match(overviewText, /Different-sign accuracy/);
    assert.match(overviewText, /Same predicted sign/);
    assert.match(overviewText, /Different predicted signs/);
    assert.doesNotMatch(overviewText, /views agree|views differ|non-contested|ideology-contested/i);
    assert.match(overviewText, /Accuracy gap/);
    assert.equal(await page.locator('#model-panel-overview .metric-definition-grid > section').count(), 4);
    assert.equal(await page.locator('#model-panel-overview [aria-label="Intervention-oriented sign equals market-oriented sign"]').count(), 1);
    assert.equal(await page.locator('#model-panel-overview [aria-label="Intervention-oriented sign does not equal market-oriented sign"]').count(), 1);
    const neutralMetricColor = await page.locator('#model-panel-overview .metric-card').first().evaluate(
        (card) => getComputedStyle(card.querySelector('dd')).color,
    );
    const overviewBackgrounds = await page.locator('#model-panel-overview .metric-card').evaluateAll(
        (cards) => cards.map((card) => getComputedStyle(card).backgroundColor),
    );
    assert.equal(new Set(overviewBackgrounds).size, 1, `${width}px positive-model metric backgrounds differ`);
    const neutralMetricBackground = overviewBackgrounds[0];
    const signedOverview = await page.locator('#model-panel-overview .metric-card').nth(4).evaluate((card) => ({
        className: card.className,
        color: getComputedStyle(card.querySelector('dd')).color,
        direction: card.querySelector('.metric-direction')?.textContent.trim(),
    }));
    assert.match(signedOverview.className, /is-intervention/);
    assert.equal(signedOverview.direction, 'Intervention-truth advantage');
    assert.notEqual(signedOverview.color, neutralMetricColor);

    await page.locator('#model-tab-examples').click();
    assert.equal(await page.locator('#model-panel-examples .example-card').count(), 2);
    const examplesText = await page.locator('#model-panel-examples').innerText();
    assert.doesNotMatch(examplesText, /t1_(?:9849|515)/);
    assert.doesNotMatch(examplesText, /excerpt|hidden reasoning/i);
    assert.doesNotMatch(examplesText, /side by side/i);
    assert.equal(await page.locator('.example-reference-block').count(), 2);
    assert.equal(await page.locator('.example-model-block').count(), 2);
    assert.equal(await page.locator('.example-sign-chip.sign-positive, .example-sign-chip.sign-negative, .example-sign-chip.sign-none, .example-sign-chip.sign-mixed').count(), 8);
    const chipStyles = await page.locator('.example-sign-chip').evaluateAll((chips) => chips.map((chip) => ({
        className: chip.className,
        background: getComputedStyle(chip).backgroundColor,
        border: getComputedStyle(chip).borderColor,
    })));
    chipStyles.forEach((chip) => {
        assert.match(chip.className, /sign-(?:positive|negative|none|mixed)/);
        assert.notEqual(chip.background, 'rgba(0, 0, 0, 0)');
        assert.notEqual(chip.border, 'rgba(0, 0, 0, 0)');
    });
    const exampleBlockLayouts = await page.locator('.example-card').evaluateAll((cards) => cards.map((card) => {
        const container = card.querySelector('.example-blocks').getBoundingClientRect();
        const reference = card.querySelector('.example-reference-block').getBoundingClientRect();
        const selectedModel = card.querySelector('.example-model-block').getBoundingClientRect();
        return {
            gridTemplateColumns: getComputedStyle(card.querySelector('.example-blocks')).gridTemplateColumns,
            reference: { left: reference.left, right: reference.right, top: reference.top, bottom: reference.bottom, width: reference.width },
            selectedModel: { left: selectedModel.left, right: selectedModel.right, top: selectedModel.top, bottom: selectedModel.bottom, width: selectedModel.width },
            containerWidth: container.width,
        };
    }));
    exampleBlockLayouts.forEach((layout, index) => {
        assert.ok(layout.selectedModel.top >= layout.reference.bottom, `${width}px example ${index + 1} blocks do not stack`);
        assert.ok(Math.abs(layout.reference.left - layout.selectedModel.left) < 1, `${width}px example ${index + 1} left edges`);
        assert.ok(Math.abs(layout.reference.width - layout.selectedModel.width) < 1, `${width}px example ${index + 1} full widths`);
        assert.ok(Math.abs(layout.reference.width - layout.containerWidth) < 1, `${width}px example ${index + 1} reference width`);
        assert.equal(layout.gridTemplateColumns.trim().split(/\s+/).length, 1, `${width}px example ${index + 1} grid columns`);
    });
    const renderedExamples = await page.locator('.example-card').evaluateAll((cards) => cards.map((card) => {
        const context = card.querySelector('.example-context').cloneNode(true);
        context.querySelector('strong')?.remove();
        return {
            heading: card.querySelector('h3').textContent,
            context: context.textContent,
            rationale: card.querySelector('.example-rationale p').textContent,
        };
    }));
    paperData.examples.forEach((example, index) => {
        const output = example.model_outputs.find((row) => row.model_id === model.id);
        assert.equal(renderedExamples[index].heading, `${example.treatment} → ${example.outcome}`);
        assert.equal(renderedExamples[index].context, example.context, `${width}px full example context ${index + 1}`);
        assert.equal(renderedExamples[index].rationale, output.rationale, `${width}px full rationale ${index + 1}`);
    });

    await page.locator('#model-tab-subfields').scrollIntoViewIfNeeded();
    await page.locator('#model-tab-subfields').click();
    assert.equal(await page.locator('#model-panel-subfields .model-subfield-card').count(), 8);
    const subfieldsText = await page.locator('#model-panel-subfields').innerText();
    assert.doesNotMatch(subfieldsText, /Other/);
    assert.doesNotMatch(subfieldsText, /\bn\s*=\s*\d+/i);
    const renderedSubfields = await page.locator('.model-subfield-card').allInnerTexts();
    model.subfields.forEach((subfield, index) => {
        for (const value of [
            subfield.name,
            `${one(subfield.intervention_accuracy)}%`,
            `${one(subfield.market_accuracy)}%`,
            signed(subfield.accuracy_gap_pp, ' pp'),
        ]) {
            assert.ok(renderedSubfields[index].includes(value), `${width}px model subfield is missing ${value}`);
        }
    });
    for (const value of [
        'Total',
        `${one(model.overview.intervention_accuracy)}%`,
        `${one(model.overview.market_accuracy)}%`,
        signed(model.overview.accuracy_gap_pp, ' pp'),
    ]) {
        assert.ok(renderedSubfields[7].includes(value), `${width}px Total row is missing ${value}`);
    }
    assert.match(
        await page.locator('#model-panel-subfields .model-subfield-card').nth(7).getAttribute('class'),
        /is-total/,
    );
    const subfieldLayout = await page.locator('#model-panel-subfields').evaluate((panel) => {
        const rows = [...panel.querySelectorAll('.model-subfield-card')];
        return {
            columnsVisible: panel.querySelector('.model-subfield-columns').getClientRects().length > 0,
            maxRowHeight: Math.max(...rows.map((row) => row.getBoundingClientRect().height)),
            scrollWidth: panel.scrollWidth,
            clientWidth: panel.clientWidth,
        };
    });
    assert.ok(subfieldLayout.maxRowHeight < (width <= 420 ? 170 : 90), `${width}px model subfield rows are too tall`);
    assert.ok(subfieldLayout.scrollWidth <= subfieldLayout.clientWidth + 1, `${width}px model subfield panel overflows`);

    const dialogTargets = await page.locator(
        '#model-detail-dialog[open] [data-dialog-close], #model-detail-dialog[open] [data-model-tab], #model-detail-dialog[open] a[href]',
    ).evaluateAll((elements) => elements.filter((element) => element.getClientRects().length).map((element) => {
        const rect = element.getBoundingClientRect();
        return { name: element.id || element.className, width: rect.width, height: rect.height };
    }));
    checkTouchTargets(dialogTargets, `${width}px dialog controls`);

    if (width === 320) {
        const tabMetrics = await page.locator('.model-tabs').evaluate((tabs) => ({
            documentOverflow: document.documentElement.scrollWidth - document.documentElement.clientWidth,
            stripScrolls: tabs.scrollWidth >= tabs.clientWidth,
            lastVisible: tabs.lastElementChild.getBoundingClientRect().right <= tabs.getBoundingClientRect().right + 1,
        }));
        assert.ok(tabMetrics.documentOverflow <= 1, '320px tabs create document overflow');
        assert.ok(tabMetrics.stripScrolls, '320px tab strip is not horizontally contained');
        assert.ok(tabMetrics.lastVisible, '320px By subfield tab cannot be reached');
    }

    for (let index = 0; index < 12; index += 1) {
        await page.keyboard.press('Tab');
        assert.ok(await dialog.evaluate((element) => element.contains(document.activeElement)), `${width}px focus escaped modal`);
    }

    const outsidePoint = await dialog.evaluate((element) => {
        const rect = element.getBoundingClientRect();
        const candidates = [
            { x: Math.max(1, rect.left - 4), y: Math.max(1, rect.top + 4) },
            { x: Math.max(1, rect.left + 4), y: Math.max(1, rect.top - 4) },
            { x: Math.min(innerWidth - 1, rect.right + 4), y: Math.max(1, rect.top + 4) },
        ];
        return candidates.find((point) => (
            point.x < rect.left || point.x > rect.right || point.y < rect.top || point.y > rect.bottom
        ));
    });
    assert.ok(outsidePoint, `${width}px no backdrop coordinate available`);
    await page.mouse.click(outsidePoint.x, outsidePoint.y);
    await waitForDialogClosed(page);
    assert.ok(await trigger.evaluate((element) => element === document.activeElement), `${width}px backdrop close did not restore focus`);

    await trigger.press('Enter');
    await page.locator('#model-detail-dialog[open]').waitFor();
    await closeDialog(page, 'escape');
    assert.ok(await trigger.evaluate((element) => element === document.activeElement), `${width}px Escape did not restore focus`);

    const negativeTrigger = page.locator('.model-open-button[data-model-id="claude-sonnet-4-6"]');
    await page.mouse.move(1, 1);
    await negativeTrigger.focus();
    await negativeTrigger.dispatchEvent('mouseenter');
    await page.waitForFunction(() => (
        !document.querySelector('#model-quick-detail').hidden
        && document.querySelector('#model-quick-detail .quick-detail-header strong')?.textContent.includes('Claude Sonnet 4.6')
        && document.querySelector('#model-quick-detail .quick-detail-grid > div:nth-child(3)')?.classList.contains('is-market')
        && document.querySelector('#model-quick-detail .quick-detail-grid > div:nth-child(3) dd')?.textContent.includes('0.9')
    ));
    const negativeQuickState = await page.evaluate(() => {
        const metrics = [...document.querySelectorAll('#model-quick-detail .quick-detail-grid > div')];
        return {
            neutralColor: getComputedStyle(metrics[0].querySelector('dd')).color,
            signedMetrics: [2, 3].map((index) => ({
                className: metrics[index].className,
                color: getComputedStyle(metrics[index].querySelector('dd')).color,
                text: metrics[index].querySelector('dd').innerText,
            })),
        };
    });
    const negativeQuickMetrics = negativeQuickState.signedMetrics;
    const quickNeutralColor = negativeQuickState.neutralColor;
    assert.match(negativeQuickMetrics[0].className, /is-market/);
    assert.notEqual(negativeQuickMetrics[0].color, quickNeutralColor);
    assert.match(negativeQuickMetrics[0].text, /[−-]0\.9/);
    assert.match(negativeQuickMetrics[1].className, /is-market/);
    assert.notEqual(negativeQuickMetrics[1].color, quickNeutralColor);
    assert.equal(negativeQuickMetrics[0].color, negativeQuickMetrics[1].color);

    await negativeTrigger.press('Enter');
    await page.locator('#model-detail-dialog[open]').waitFor();
    const negativeMetrics = await page.locator('#model-panel-overview .metric-card').evaluateAll((cards) => [4, 5].map((index) => ({
        className: cards[index].className,
        color: getComputedStyle(cards[index].querySelector('dd')).color,
        background: getComputedStyle(cards[index]).backgroundColor,
        value: cards[index].querySelector('dd').innerText,
        direction: cards[index].querySelector('.metric-direction')?.textContent.trim(),
    })));
    assert.match(negativeMetrics[0].className, /is-market/);
    assert.notEqual(negativeMetrics[0].color, neutralMetricColor);
    assert.match(negativeMetrics[0].value, /[−-]0\.9/);
    assert.match(negativeMetrics[1].className, /is-market/);
    assert.notEqual(negativeMetrics[1].color, neutralMetricColor);
    assert.equal(negativeMetrics[0].color, negativeMetrics[1].color);
    assert.equal(negativeMetrics[0].background, negativeMetrics[1].background);
    assert.equal(negativeMetrics[0].background, neutralMetricBackground);
    assert.equal(negativeMetrics[0].direction, 'Market-truth advantage');
    assert.equal(negativeMetrics[1].direction, 'Market-oriented');
    await closeDialog(page);
}

async function validateUpdatedModelDialog(page, width) {
    const trigger = page.locator('.model-open-button[data-condition-key]').first();
    const conditionKey = await trigger.getAttribute('data-condition-key');
    const resultKey = await trigger.getAttribute('data-result-key');
    assert.ok(conditionKey, `${width}px updated-result trigger has no condition key`);
    assert.match(resultKey, /^new:/, `${width}px updated-result trigger key`);

    await page.mouse.move(1, 1);
    await trigger.focus();
    await page.waitForFunction(() => (
        !document.querySelector('#model-quick-detail').hidden
        && document.querySelectorAll('#model-quick-detail .quick-detail-grid > div').length === 5
    ));
    const quickText = await page.locator('#model-quick-detail').innerText();
    for (const label of ['Overall', 'Intervention-truth', 'Market-truth', 'Accuracy gap']) {
        assert.ok(quickText.includes(label), `${width}px updated-result hover is missing ${label}`);
    }

    await trigger.press('Enter');
    const dialog = page.locator('#model-detail-dialog');
    await page.locator('#model-detail-dialog[open]').waitFor();
    assert.equal(await dialog.getAttribute('data-condition-key'), conditionKey);
    assert.equal(await dialog.getAttribute('data-result-key'), resultKey);
    assert.equal(await dialog.getAttribute('data-model-id'), null, `${width}px updated dialog inherited a paper model id`);
    assert.equal(await page.locator('[data-model-tab]').count(), 3, `${width}px updated dialog changed the tab contract`);
    assert.equal(await page.locator('[data-model-tab]:visible').count(), 3, `${width}px updated dialog does not expose all tabs`);
    assert.equal(await page.locator('#model-panel-overview .metric-card').count(), 5, `${width}px updated overview metric count`);
    assert.equal(await page.locator('#model-panel-overview .updated-result-provenance > div').count(), 4, `${width}px updated provenance count`);
    const overviewText = await page.locator('#model-panel-overview').innerText();
    for (const label of ['Overall accuracy', 'Intervention-truth', 'Market-truth', 'Accuracy gap']) {
        assert.ok(overviewText.includes(label), `${width}px updated dialog is missing ${label}`);
    }
    await page.locator('#model-tab-examples').click();
    assert.equal(await page.locator('#model-panel-examples .example-card').count(), 2, `${width}px updated dialog examples`);
    await page.locator('#model-tab-subfields').click();
    assert.equal(await page.locator('#model-panel-subfields .model-subfield-card').count(), 8, `${width}px updated dialog subfields`);
    await closeDialog(page);
    assert.ok(await trigger.evaluate((element) => element === document.activeElement), `${width}px updated dialog did not restore focus`);
}

async function validateReleaseChart(page, width) {
    const chart = page.locator('#release-chart');
    const points = chart.locator('.release-point-button');
    assert.equal(await page.locator('#bias-map, .bias-map-marker, .bias-scatter-marker').count(), 0, `${width}px removed bias map remains`);
    assert.equal(await points.count(), 51, `${width}px release-chart rows`);
    const releaseKeys = await points.evaluateAll((items) => items.map((item) => item.dataset.resultKey));
    const mainKeys = await page.locator('.model-open-button').evaluateAll((items) => items.map((item) => item.dataset.resultKey));
    assert.equal(new Set(releaseKeys).size, 51, `${width}px duplicate release keys`);
    assert.equal(new Set(mainKeys).size, 51, `${width}px duplicate main keys`);
    assert.deepEqual([...releaseKeys].sort(), [...mainKeys].sort(), `${width}px release/main keys differ`);
    const targetMetrics = await points.evaluateAll((items) => items.map((item) => {
        const rect = item.getBoundingClientRect();
        return { name: item.dataset.resultKey, width: rect.width, height: rect.height };
    }));
    checkTouchTargets(targetMetrics, `${width}px release-chart controls`);
    const geometry = await chart.evaluate((element) => {
        const svg = element.querySelector('.release-chart-svg');
        const svgRect = svg.getBoundingClientRect();
        const markers = [...svg.querySelectorAll('.release-svg-point')];
        const buttons = [...element.querySelectorAll('.release-point-button')];
        const markerByKey = new Map(markers.map((marker) => [marker.dataset.resultKey, marker]));
        const pointAlignment = buttons.map((button) => {
            const marker = markerByKey.get(button.dataset.resultKey);
            const buttonRect = button.getBoundingClientRect();
            const markerAnchor = marker ? svg.createSVGPoint() : null;
            if (markerAnchor) {
                markerAnchor.x = Number(marker.dataset.x);
                markerAnchor.y = Number(marker.dataset.y);
            }
            const markerScreenAnchor = markerAnchor?.matrixTransform(svg.getScreenCTM());
            return {
                key: button.dataset.resultKey,
                missing: !marker,
                dx: markerScreenAnchor ? Math.abs((buttonRect.left + buttonRect.width / 2) - markerScreenAnchor.x) : null,
                dy: markerScreenAnchor ? Math.abs((buttonRect.top + buttonRect.height / 2) - markerScreenAnchor.y) : null,
            };
        });
        const lineOrder = [...svg.querySelectorAll('.release-family-line')].map((line) => {
            const xs = line.getAttribute('points').trim().split(/\s+/).map((pair) => Number(pair.split(',')[0]));
            return {
                family: line.dataset.family,
                nondecreasing: xs.every((value, index) => index === 0 || value >= xs[index - 1] - 0.001),
            };
        });
        return {
            coordinateSystem: element.dataset.coordinateSystem,
            lineOrderContract: element.dataset.familyLineOrder,
            markerCount: markers.length,
            buttonCount: buttons.length,
            svgWidth: svgRect.width,
            chartContentWidth: element.clientWidth,
            pointAlignment,
            lineOrder,
        };
    });
    assert.equal(geometry.coordinateSystem, 'exact-data-coordinates', `${width}px release coordinate contract`);
    assert.equal(geometry.lineOrderContract, 'release-date-ascending', `${width}px release line-order contract`);
    assert.equal(geometry.markerCount, 51, `${width}px release SVG marker count`);
    assert.equal(geometry.buttonCount, 51, `${width}px release hit-target count`);
    assert.ok(Math.abs(geometry.svgWidth - geometry.chartContentWidth) < 1, `${width}px SVG/chart width drift`);
    geometry.pointAlignment.forEach((point) => {
        assert.equal(point.missing, false, `${width}px missing marker for ${point.key}`);
        assert.ok(point.dx < 1 && point.dy < 1, `${width}px ${point.key} marker/hit drift ${point.dx},${point.dy}`);
    });
    geometry.lineOrder.forEach((line) => {
        assert.equal(line.nondecreasing, true, `${width}px ${line.family} line moves backward in time`);
    });
    if (width === 1024) {
        const updatedPoint = chart.locator('.release-point-button[data-result-key^="new:"]').first();
        const resultKey = await updatedPoint.getAttribute('data-result-key');
        await updatedPoint.click();
        await page.locator('#model-detail-dialog[open]').waitFor();
        assert.equal(await page.locator('#model-detail-dialog').getAttribute('data-result-key'), resultKey);
        assert.equal(await page.locator('[data-model-tab]:visible').count(), 3, `${width}px release-chart updated dialog tabs`);
        await closeDialog(page);
    }
}

async function validateEffortCharts(page, width) {
    const grid = page.locator('#reasoning-effort-grid');
    const charts = grid.locator('.effort-line-chart');
    const hits = grid.locator('.effort-setting-hit');
    const seriesPoints = grid.locator('.effort-series-point');
    assert.equal(await grid.getAttribute('data-chart-count'), '4', `${width}px effort chart count`);
    assert.equal(await grid.getAttribute('data-point-count'), '17', `${width}px effort point count`);
    assert.equal(await grid.getAttribute('data-metric'), 'overall,gap', `${width}px simultaneous effort metrics`);
    assert.equal(await charts.count(), 4, `${width}px effort charts`);
    assert.equal(await hits.count(), 17, `${width}px effort setting targets`);
    assert.equal(await seriesPoints.count(), 34, `${width}px effort series point count`);
    assert.deepEqual(
        await charts.evaluateAll((items) => items.map((chart) => chart.querySelectorAll('.effort-setting-hit').length)),
        [5, 5, 4, 3],
        `${width}px effort sweep sizes`,
    );
    assert.deepEqual(
        await charts.evaluateAll((items) => items.map((chart) => chart.querySelectorAll('.effort-series-point').length)),
        [10, 10, 8, 6],
        `${width}px two effort series per setting`,
    );
    assert.equal(await charts.locator('canvas').count(), 4, `${width}px effort canvases`);
    assert.equal(await charts.locator('dl.effort-data-list').count(), 4, `${width}px effort semantic lists`);
    assert.equal(await charts.locator('dl.effort-data-list > div').count(), 17, `${width}px effort semantic rows`);
    assert.equal(await page.locator('[data-effort-metric]').count(), 0, `${width}px obsolete metric controls remain`);
    assert.deepEqual(
        await page.locator('#effort-explorer-controls [data-effort-series]').allInnerTexts(),
        ['Overall accuracy', 'Accuracy gap'],
        `${width}px effort legend series`,
    );
    assert.equal(await grid.locator('.effort-series-point[data-metric="overall"]').count(), 17);
    assert.equal(await grid.locator('.effort-series-point[data-metric="gap"]').count(), 17);
    const geometry = await hits.evaluateAll((items) => items.map((item) => {
        const rect = item.getBoundingClientRect();
        return {
            label: item.getAttribute('aria-label'),
            x: Number(item.dataset.x),
            hitWidth: rect.width,
            hitHeight: rect.height,
        };
    }));
    geometry.forEach((row, index) => {
        assert.match(row.label, /overall \d+\.\d%, gap [+−]?\d+\.\d pp\.$/);
        assert.ok(row.x >= 9 && row.x <= 91, `${width}px effort point ${index + 1} x=${row.x}`);
        assert.ok(row.hitWidth >= 23.5 && row.hitHeight >= 43.5, `${width}px effort point ${index + 1} hit target`);
    });
    const plottedGeometry = await seriesPoints.evaluateAll((items) => items.map((item) => ({
        metric: item.dataset.metric,
        x: Number(item.dataset.x),
        y: Number(item.dataset.y),
    })));
    plottedGeometry.forEach((row, index) => {
        assert.ok(['overall', 'gap'].includes(row.metric), `${width}px effort series point ${index + 1} metric`);
        assert.ok(row.x >= 9 && row.x <= 91, `${width}px effort series point ${index + 1} x=${row.x}`);
        assert.ok(row.y >= 8 && row.y <= 84, `${width}px effort series point ${index + 1} y=${row.y}`);
    });
    const chartColumns = await charts.evaluateAll((items) => new Set(items.map((item) => Math.round(item.getBoundingClientRect().left))).size);
    assert.equal(chartColumns, width <= 680 ? 1 : 2, `${width}px effort chart columns`);

    if (width === 1440) {
        await hits.first().focus();
        assert.equal(await hits.first().locator('.effort-point-tooltip > span').count(), 2);
        const tooltipText = await hits.first().locator('.effort-point-tooltip').innerText();
        assert.match(tooltipText, /Overall \d+\.\d%/);
        assert.match(tooltipText, /Gap [+−]?\d+\.\d pp/);
        assert.doesNotMatch(tooltipText, /Bdir|B\s*dir|bias/i);
    }
}

async function validateViewport(browser, width) {
    const context = await browser.newContext({
        viewport: { width, height: width <= 375 ? 780 : 900 },
        reducedMotion: width === 768 ? 'reduce' : 'no-preference',
        hasTouch: width === 375,
    });
    const page = await context.newPage();
    const errors = [];
    page.on('console', (message) => {
        if (message.type() === 'error') errors.push(`console: ${message.text()}`);
    });
    page.on('pageerror', (error) => errors.push(`pageerror: ${error.message}`));
    page.on('requestfailed', (request) => errors.push(`request: ${request.url()} ${request.failure()?.errorText}`));

    await page.goto(baseUrl, { waitUntil: 'networkidle' });
    await page.locator('#release-chart .release-point-button').first().waitFor();
    assert.equal(await page.locator('.model-open-button').count(), 51, `${width}px model triggers`);
    assert.equal(await page.locator('.model-open-button[data-condition-key]').count(), 31, `${width}px updated-model triggers`);
    assert.equal(await page.locator('.subfield-row').count(), 7, `${width}px subfield rows`);
    assert.equal(await page.locator('#model-benchmark-chart .model-score-row').count(), 51, `${width}px unified benchmark rows`);
    assert.equal(await page.locator('#model-benchmark-chart .model-score-row[data-condition-key]').count(), 31, `${width}px added benchmark models`);
    assert.equal(await page.locator('#model-benchmark-chart .model-score-row[data-condition-key^="local_"]').count(), 9, `${width}px local benchmark rows`);
    assert.equal(await page.locator('#model-benchmark-chart .model-family-group').count(), 8, `${width}px capability groups`);
    assert.equal(await page.locator('#model-benchmark-chart').getAttribute('data-model-count'), '51', `${width}px main model count`);
    assert.equal(await page.locator('#model-benchmark-chart').getAttribute('data-positive-gap-count'), '44', `${width}px positive-gap count`);
    assert.equal(await page.locator('#model-benchmark-chart').getAttribute('data-order'), 'capability-groups', `${width}px grouping contract`);
    assert.equal(await page.locator('#post-paper-extension').count(), 0, `${width}px separate post-paper section remains`);
    assert.equal(await page.locator('#bias-map, .bias-map-marker, .bias-scatter-marker, .bias-ranking-row').count(), 0, `${width}px removed bias UI remains`);
    assert.equal(await page.locator('#release-chart .release-point-button').count(), 51, `${width}px release chart count`);
    assert.equal(await page.locator('#model-benchmark-controls').count(), 0, `${width}px benchmark filter remains`);
    assert.equal(await page.locator('#model-benchmark-chart .result-source-chip').count(), 0, `${width}px source chips remain`);
    assert.equal(await page.locator('#model-benchmark-chart .model-score-name small').count(), 0, `${width}px setting labels remain`);
    assert.equal(await page.locator('#reasoning-effort-grid .interactive-effort-table, #reasoning-effort-grid .effort-model-row, #reasoning-effort-grid .effort-progression-point').count(), 0, `${width}px old effort flow remains`);
    assert.match(await page.locator('#model-benchmark-heading').innerText(), /^44 of 51 models/);
    assert.equal(await page.locator('[id*="compare"], [class*="compare-"]').count(), 0, `${width}px compare UI remains`);
    const bodyText = await page.locator('body').innerText();
    assert.doesNotMatch(bodyText, /�/, `${width}px replacement glyph`);
    assert.doesNotMatch(await page.locator('#reasoning-effort').innerText(), /B\s*dir|Error-direction bias/i, `${width}px reasoning effort exposes removed bias`);

    const capabilityGroups = await page.evaluate(() => Object.fromEntries(
        [...document.querySelectorAll('#model-benchmark-chart [data-model-group]')].map((group) => [
            group.dataset.modelGroup,
            [...group.querySelectorAll('.model-score-row')].map((row) => row.dataset.resultKey),
        ]),
    ));
    assert.deepEqual(Object.keys(capabilityGroups), [
        'openai-compact', 'openai-flagship', 'claude', 'gemini',
        'grok', 'llama', 'qwen-compact', 'qwen-large',
    ]);
    assert.deepEqual(capabilityGroups['openai-compact'], ['paper:gpt-4o-mini', 'paper:gpt-5-nano', 'paper:gpt-5-mini', 'new:oa_gpt54_nano_none', 'new:oa_gpt54_mini_none', 'new:oa_gpt56_luna_none']);
    assert.deepEqual(capabilityGroups['openai-flagship'], ['paper:gpt-4o', 'new:openai_gpt5_minimal', 'new:openai_gpt51_none', 'paper:gpt-5-2', 'new:oa_gpt54_none', 'new:oa_gpt55_none', 'new:oa_gpt56_terra_none', 'new:oa_gpt56_sol_none']);
    assert.deepEqual(capabilityGroups.claude, ['paper:claude-haiku-4-5', 'new:anthropic_sonnet45_disabled', 'new:anthropic_opus45_disabled_low', 'paper:claude-sonnet-4-6', 'paper:claude-opus-4-6', 'new:an_opus47_disabled_low', 'new:an_opus48_disabled_low', 'new:an_sonnet5_disabled_low', 'new:an_opus5_disabled_low', 'new:an_fable5_adaptive_low']);
    assert.deepEqual(capabilityGroups.gemini, ['paper:gemini-2-5-flash', 'paper:gemini-3-flash', 'new:gg_gemini31lite_minimal', 'new:gg_gemini35_minimal', 'new:gg_gemini36_minimal']);
    assert.deepEqual(capabilityGroups.grok, ['paper:grok-3-mini', 'paper:grok-3', 'paper:grok-4-1-fast', 'new:or_grok420_reasoning_disabled', 'new:or_grok43_none', 'new:or_grok45_low']);
    assert.deepEqual(
        await page.locator('#model-benchmark-chart .model-score-row[data-result-key="paper:grok-4-1-fast"] .model-score-name, #model-benchmark-chart .model-score-row[data-result-key="new:or_grok420_reasoning_disabled"] .model-score-name').allInnerTexts(),
        ['4.1', '4.2'],
        `${width}px Grok 4.1/4.2 labels`,
    );
    assert.deepEqual(capabilityGroups.llama, ['paper:llama-3-1-8b', 'paper:llama-3-2-1b', 'paper:llama-3-2-3b', 'paper:llama-3-3-70b', 'new:local_llama4_scout_17b_16e_w4a16']);
    assert.deepEqual(capabilityGroups['qwen-compact'], ['paper:qwen-3-8b', 'paper:qwen-3-14b', 'new:local_qwen35_0_8b_nf4', 'new:local_qwen35_2b_w4_bf16', 'new:local_qwen35_4b_awq', 'new:local_qwen35_9b_awq']);
    assert.deepEqual(capabilityGroups['qwen-large'], ['paper:qwen-3-32b', 'new:local_qwen35_27b_gptq', 'new:local_qwen35_35b_a3b_gptq', 'new:local_qwen36_27b_gptq', 'new:local_qwen36_35b_a3b_awq']);

    const rowBackgrounds = await page.evaluate(() => Object.fromEntries(
        ['gpt-4o-mini', 'claude-sonnet-4-6', 'claude-opus-4-6'].map((modelId) => [
            modelId,
            getComputedStyle(document.querySelector(`.model-score-row[data-model-id="${modelId}"]`)).backgroundColor,
        ]),
    ));
    assert.equal(rowBackgrounds['claude-sonnet-4-6'], rowBackgrounds['gpt-4o-mini'], `${width}px Sonnet row background`);
    assert.equal(rowBackgrounds['claude-opus-4-6'], rowBackgrounds['gpt-4o-mini'], `${width}px Opus row background`);

    const mainGapColors = await page.evaluate(() => {
        const firstScoreBars = getComputedStyle(document.querySelector('.model-score-bars'));
        return {
            scoreBarsBackgroundImage: firstScoreBars.backgroundImage,
            positive: {
                color: getComputedStyle(document.querySelector('.model-open-button[data-model-id="gpt-4o-mini"]')
                    .closest('.model-score-row').querySelector('.model-gap')).color,
                text: document.querySelector('.model-open-button[data-model-id="gpt-4o-mini"]')
                    .closest('.model-score-row').querySelector('.model-gap').innerText,
            },
            sonnet: {
                color: getComputedStyle(document.querySelector('.model-open-button[data-model-id="claude-sonnet-4-6"]')
                    .closest('.model-score-row').querySelector('.model-gap')).color,
                text: document.querySelector('.model-open-button[data-model-id="claude-sonnet-4-6"]')
                    .closest('.model-score-row').querySelector('.model-gap').innerText,
            },
            opus: {
                color: getComputedStyle(document.querySelector('.model-open-button[data-model-id="claude-opus-4-6"]')
                    .closest('.model-score-row').querySelector('.model-gap')).color,
                text: document.querySelector('.model-open-button[data-model-id="claude-opus-4-6"]')
                    .closest('.model-score-row').querySelector('.model-gap').innerText,
            },
        };
    });
    assert.equal(mainGapColors.scoreBarsBackgroundImage, 'none', `${width}px main score grid background remains`);
    assert.match(mainGapColors.positive.text, /\+/);
    for (const [name, metric] of Object.entries({ Sonnet: mainGapColors.sonnet, Opus: mainGapColors.opus })) {
        assert.notEqual(metric.color, mainGapColors.positive.color, `${width}px ${name} negative gap has positive color`);
        assert.match(metric.text, /[−-]/, `${width}px ${name} gap lost its minus sign`);
    }
    assert.equal(mainGapColors.sonnet.color, mainGapColors.opus.color, `${width}px negative gaps use inconsistent colors`);

    const layout = await page.evaluate(() => {
        const root = document.documentElement;
        const mainTargets = [...document.querySelectorAll('.model-open-button')]
            .filter((element) => element.getClientRects().length)
            .map((element) => {
                const rect = element.getBoundingClientRect();
                return { name: element.dataset.modelId, width: rect.width, height: rect.height };
            });
        const motivation = document.querySelector('#motivation .section-heading');
        const motivationParagraph = motivation.querySelector('p');
        const headingRect = motivation.getBoundingClientRect();
        const paragraphRect = motivationParagraph.getBoundingClientRect();
        return {
            pageScrollWidth: root.scrollWidth,
            pageClientWidth: root.clientWidth,
            mainTargets,
            motivationCenterError: Math.abs(
                (headingRect.left + headingRect.width / 2)
                - (paragraphRect.left + paragraphRect.width / 2)
            ),
        };
    });
    assert.ok(layout.pageScrollWidth <= layout.pageClientWidth + 1, `${width}px document overflows`);
    assert.ok(layout.motivationCenterError < 1, `${width}px motivation copy is not centered`);
    checkTouchTargets(layout.mainTargets, `${width}px main controls`);

    await validateAggregateSubfields(page, width);
    await validateReleaseChart(page, width);
    await validateEffortCharts(page, width);
    await validateUpdatedModelDialog(page, width);
    await validateModelDialog(page, width);

    const internshipOrder = await page.evaluate(() => {
        const internship = document.querySelector('[aria-labelledby="internship-heading"]');
        const citation = document.querySelector('#citation');
        return {
            precedesCitation: Boolean(internship && citation && (internship.compareDocumentPosition(citation) & Node.DOCUMENT_POSITION_FOLLOWING)),
            heading: internship?.querySelector('#internship-heading')?.textContent.trim(),
            copy: internship?.querySelector('.internship-copy p')?.textContent.trim(),
            links: [...(internship?.querySelectorAll('a') || [])].map((link) => link.getAttribute('href')),
        };
    });
    assert.equal(internshipOrder.precedesCitation, true);
    assert.equal(internshipOrder.heading, 'I am looking for research internship opportunities.');
    assert.match(internshipOrder.copy, /^I(?:['’]m| am) /);
    assert.doesNotMatch(internshipOrder.copy, /our lab|we are hiring|we are looking/i);
    assert.deepEqual(internshipOrder.links, [
        'mailto:donggyu.lee@kaist.ac.kr',
        'https://donggyu-lee1.github.io',
        'https://www.linkedin.com/in/donggyu-lee-65784b21b',
    ]);

    if (width === 768) {
        const reducedMotionDisplays = await page.evaluate(() => Object.fromEntries(
            ['.model-open-button', '.release-point-button', '.effort-setting-hit', '.subfield-row']
                .map((selector) => [selector, getComputedStyle(document.querySelector(selector)).display]),
        ));
        for (const [selector, display] of Object.entries(reducedMotionDisplays)) {
            assert.notEqual(display, 'none', `reduced-motion ${selector} hidden`);
        }
        await page.locator('.model-open-button').first().evaluate((button) => button.click());
        await page.locator('#model-detail-dialog[open]').waitFor();
        assert.notEqual(
            await page.locator('#model-detail-dialog').evaluate((dialog) => getComputedStyle(dialog).display),
            'none',
            'reduced-motion open dialog hidden',
        );
        await closeDialog(page);
    }

    if (!skipAxe && (width === 320 || width === 1024)) await runAxe(page, `${width}px`);

    if (!skipScreenshots && (width === 1440 || width === 320)) {
        fs.mkdirSync(screenshotDir, { recursive: true });
        await page.screenshot({
            path: path.join(screenshotDir, `paper-page-${width}.png`),
            fullPage: true,
        });
    }

    assert.deepEqual(errors, [], `${width}px browser errors:\n${errors.join('\n')}`);
    await context.close();
}

async function validateFallbacks(browser) {
    const noJs = await browser.newContext({ viewport: { width: 320, height: 780 }, javaScriptEnabled: false });
    const noJsPage = await noJs.newPage();
    await noJsPage.goto(baseUrl, { waitUntil: 'load' });
    assert.equal(await noJsPage.locator('.model-score-row').count(), 20);
    assert.equal(await noJsPage.locator('.bias-ranking-row, #bias-map').count(), 0);
    assert.equal(await noJsPage.locator('.subfield-row').count(), 7);
    assert.equal(await noJsPage.locator('#post-paper-extension').count(), 0);
    assert.equal(await noJsPage.locator('#release-chart .release-point-button').count(), 0);
    assert.equal(await noJsPage.locator('#reasoning-effort-grid .effort-card').count(), 0);
    assert.equal(await noJsPage.locator('#reasoning-effort-grid .effort-model-row').count(), 4);
    assert.equal(await noJsPage.locator('#reasoning-effort-grid .effort-progression-point').count(), 17);
    assert.match(await noJsPage.locator('body').innerText(), /10,490.*1,056.*878.*507.*371/s);
    assert.doesNotMatch(await noJsPage.locator('body').innerText(), /�/);
    const noJsWidth = await noJsPage.evaluate(() => {
        const root = document.documentElement;
        const offenders = [...document.querySelectorAll('body *')]
            .map((element) => ({ element, rect: element.getBoundingClientRect() }))
            .filter(({ rect }) => rect.right > root.clientWidth + 1 || rect.left < -1)
            .slice(0, 10)
            .map(({ element, rect }) => ({
                selector: `${element.tagName.toLowerCase()}${element.id ? `#${element.id}` : ''}${element.className ? `.${String(element.className).trim().replaceAll(/\s+/g, '.')}` : ''}`,
                left: Math.round(rect.left),
                right: Math.round(rect.right),
                width: Math.round(rect.width),
            }));
        const inspect = (selector) => {
            const element = document.querySelector(selector);
            const rect = element?.getBoundingClientRect();
            return element && rect ? {
                selector,
                left: Math.round(rect.left),
                right: Math.round(rect.right),
                width: Math.round(rect.width),
                clientWidth: element.clientWidth,
                scrollWidth: element.scrollWidth,
                minWidth: getComputedStyle(element).minWidth,
                maxWidth: getComputedStyle(element).maxWidth,
                overflowX: getComputedStyle(element).overflowX,
            } : null;
        };
        return {
            scrollWidth: root.scrollWidth,
            clientWidth: root.clientWidth,
            offenders,
            chain: [
                inspect('#findings'),
                inspect('.model-benchmark'),
                inspect('.model-benchmark-chart'),
                inspect('.model-family-group'),
            ],
        };
    });
    assert.ok(
        noJsWidth.scrollWidth <= noJsWidth.clientWidth + 1,
        `no-JS page overflows at 320px: ${JSON.stringify(noJsWidth)}`,
    );
    await noJs.close();

    const failedData = await browser.newContext({ viewport: { width: 375, height: 800 } });
    const failedPage = await failedData.newPage();
    await failedPage.route('**/data/paper-data.v2.json*', (route) => route.abort());
    await failedPage.goto(baseUrl, { waitUntil: 'networkidle' });
    assert.equal(await failedPage.locator('.model-score-row').count(), 20);
    assert.equal(await failedPage.locator('.bias-ranking-row, #bias-map').count(), 0);
    assert.equal(await failedPage.locator('.subfield-row').count(), 7);
    assert.equal(await failedPage.locator('#release-chart .release-point-button').count(), 0);
    await failedPage.waitForFunction(() => document.querySelector('.copy-status')?.textContent.trim());
    assert.match(await failedPage.locator('.copy-status').textContent(), /temporarily unavailable/i);
    const failedWidth = await failedPage.evaluate(() => [document.documentElement.scrollWidth, document.documentElement.clientWidth]);
    assert.ok(failedWidth[0] <= failedWidth[1] + 1, 'data-failure page overflows at 375px');
    await failedData.close();
}

(async () => {
    assert.equal(paperData.models.length, 20, 'paper baseline model count');
    assert.deepEqual(paperData.denominators, {
        benchmark_total: 10490,
        contested_pool: 1056,
        directional_total: 878,
        intervention_truth: 507,
        market_truth: 371,
        sensitive_neither: 178,
        non_contested: 9434,
    });
    assert.equal(
        paperData.models.filter((model) => model.overview.accuracy_gap_pp > 0).length,
        17,
        'paper intervention-truth accuracy-gap count',
    );
    assert.ok(paperData.models.every((model) => model.subfields?.length === 7), '20×7 subfield data');
    assert.equal(paperData.examples.length, 2, 'representative examples');
    assert.equal(extensionData.schema_version, 'website-experiment-results.v1');
    assert.deepEqual(extensionData.evaluation.denominators, {
        contested: 1056,
        directional: 878,
        intervention_truth: 507,
        market_truth: 371,
        neither_truth: 178,
    });
    assert.equal(extensionData.main_benchmark.condition_count, 36, 'new main rows');
    assert.equal(extensionData.main_benchmark.results.length, 36, 'new main result count');
    assert.equal(extensionData.main_benchmark.results.filter((row) => row.provider === 'Local GPU').length, 9, 'local result count');
    assert.equal(extensionData.reasoning_effort_sweeps.sweep_count, 4, 'reasoning sweep count');
    assert.equal(extensionData.reasoning_effort_sweeps.condition_count, 17, 'reasoning condition count');
    assert.deepEqual(
        extensionData.reasoning_effort_sweeps.sweeps.map((sweep) => sweep.results.length),
        [5, 5, 4, 3],
        'reasoning sweep sizes',
    );
    const browser = await chromium.launch({ executablePath, headless: true, args: ['--no-sandbox'] });
    try {
        for (const width of viewports) {
            console.log(`QA viewport: ${width}px`);
            await validateViewport(browser, width);
        }
        await validateFallbacks(browser);
        console.log(`PASS: browser QA at ${viewports.join(', ')}px; screenshots in ${screenshotDir}`);
    } finally {
        await browser.close();
    }
})().catch((error) => {
    console.error(error.stack || error);
    process.exitCode = 1;
});
