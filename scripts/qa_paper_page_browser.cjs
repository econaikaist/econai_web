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
const dataPath = path.join(__dirname, '../main_site/ideological-bias-in-llms/data/paper-data.v2.json');
const paperData = JSON.parse(fs.readFileSync(dataPath, 'utf8'));
const modelsById = new Map(paperData.models.map((model) => [model.id, model]));
const viewports = [320, 375, 768, 1024, 1440, 1920];

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

async function validateReleasePointLayoutAndClicks(page, width) {
    await page.waitForFunction(() => (
        document.querySelector('#release-chart')?.dataset.pointLayoutReady === 'true'
    ));
    await page.waitForTimeout(180);

    const geometry = await page.evaluate(() => {
        const chart = document.querySelector('#release-chart').getBoundingClientRect();
        const points = [...document.querySelectorAll('.release-point-button')].map((button) => {
            const rect = button.getBoundingClientRect();
            return {
                id: button.dataset.modelId,
                family: button.dataset.family,
                centerX: rect.left + rect.width / 2,
                centerY: rect.top + rect.height / 2,
                left: rect.left,
                right: rect.right,
                top: rect.top,
                bottom: rect.bottom,
                width: rect.width,
                height: rect.height,
                actualX: Number(button.dataset.actualX),
                actualY: Number(button.dataset.actualY),
                displayX: Number(button.dataset.displayX),
                displayY: Number(button.dataset.displayY),
            };
        });
        let minimumCenterSpacing = Infinity;
        let minimumActualSpacing = Infinity;
        for (let first = 0; first < points.length; first += 1) {
            for (let second = first + 1; second < points.length; second += 1) {
                minimumCenterSpacing = Math.min(
                    minimumCenterSpacing,
                    Math.hypot(
                        points[first].centerX - points[second].centerX,
                        points[first].centerY - points[second].centerY,
                    ),
                );
                minimumActualSpacing = Math.min(
                    minimumActualSpacing,
                    Math.hypot(
                        points[first].actualX - points[second].actualX,
                        points[first].actualY - points[second].actualY,
                    ),
                );
            }
        }
        const displacedIds = points
            .filter((point) => Math.hypot(
                point.displayX - point.actualX,
                point.displayY - point.actualY,
            ) >= 1)
            .map((point) => point.id)
            .sort();
        return {
            chart: { left: chart.left, right: chart.right, top: chart.top, bottom: chart.bottom },
            points,
            minimumCenterSpacing,
            minimumActualSpacing,
            displacedIds,
            familyConnectors: [...document.querySelectorAll('.release-family-line')].map((line) => {
                const style = getComputedStyle(line);
                const matrix = line.getScreenCTM();
                const vertices = Array.from(line.points).map((point) => ({
                    x: point.x,
                    y: point.y,
                    screenX: point.x * matrix.a + point.y * matrix.c + matrix.e,
                    screenY: point.x * matrix.b + point.y * matrix.d + matrix.f,
                }));
                return {
                    family: line.dataset.family,
                    stroke: style.stroke,
                    strokeWidth: parseFloat(style.strokeWidth),
                    opacity: parseFloat(style.opacity),
                    vertices,
                };
            }),
            obsoleteConnectorArtifacts: document.querySelectorAll(
                '.release-leader-layer, .release-leader-line, .release-anchor-dot',
            ).length,
            declaredSpacing: Number(document.querySelector('#release-chart').dataset.minimumPointSpacing),
        };
    });

    assert.equal(geometry.points.length, 20, `${width}px release geometry point count`);
    assert.equal(new Set(geometry.points.map((point) => point.id)).size, 20, `${width}px release ids`);
    assert.equal(geometry.familyConnectors.length, 6, `${width}px family connectors`);
    assert.equal(new Set(geometry.familyConnectors.map((connector) => connector.family)).size, 6);
    assert.equal(geometry.obsoleteConnectorArtifacts, 0, `${width}px obsolete leader/anchor artifacts`);
    const pointsById = new Map(geometry.points.map((point) => [point.id, point]));
    geometry.familyConnectors.forEach((connector, index) => {
        assert.notEqual(connector.stroke, 'none', `${width}px family connector ${index + 1} stroke`);
        assert.ok(connector.strokeWidth >= 1, `${width}px family connector ${index + 1} width`);
        assert.ok(connector.opacity >= 0.4, `${width}px family connector ${index + 1} opacity`);
        const expectedModels = paperData.models
            .map((model, originalIndex) => ({ model, originalIndex }))
            .filter(({ model }) => model.family === connector.family)
            .sort((first, second) => (
                first.model.release_date.localeCompare(second.model.release_date)
                || first.originalIndex - second.originalIndex
            ));
        assert.equal(connector.vertices.length, expectedModels.length, `${width}px ${connector.family} vertex count`);
        connector.vertices.forEach((vertex, vertexIndex) => {
            const expectedModel = expectedModels[vertexIndex].model;
            const point = pointsById.get(expectedModel.id);
            assert.equal(point.family, connector.family, `${width}px ${expectedModel.id} family mapping`);
            assert.ok(Math.abs(vertex.x - point.displayX) <= 0.001, `${width}px ${expectedModel.id} local connector x`);
            assert.ok(Math.abs(vertex.y - point.displayY) <= 0.001, `${width}px ${expectedModel.id} local connector y`);
            assert.ok(Math.abs(vertex.screenX - point.centerX) < 1, `${width}px ${expectedModel.id} connector center x`);
            assert.ok(Math.abs(vertex.screenY - point.centerY) < 1, `${width}px ${expectedModel.id} connector center y`);
            if (vertexIndex > 0) {
                assert.ok(
                    vertex.x >= connector.vertices[vertexIndex - 1].x - 0.001,
                    `${width}px ${connector.family} connector doubles back`,
                );
            }
        });
        if (connector.family === 'Grok') {
            const grokIndex = expectedModels.findIndex(({ model }) => model.id === 'grok-4-1-fast');
            assert.ok(grokIndex >= 0, `${width}px Grok 4-1 missing from expected family`);
            const grokPoint = pointsById.get('grok-4-1-fast');
            assert.ok(
                Math.abs(connector.vertices[grokIndex].screenX - grokPoint.centerX) < 1
                && Math.abs(connector.vertices[grokIndex].screenY - grokPoint.centerY) < 1,
                `${width}px Grok 4-1 is detached from the Grok connector`,
            );
        }
    });
    assert.equal(geometry.declaredSpacing, 48, `${width}px declared release spacing`);
    assert.ok(
        geometry.minimumCenterSpacing >= geometry.declaredSpacing - 0.6,
        `${width}px release centers only ${geometry.minimumCenterSpacing.toFixed(2)}px apart`,
    );
    checkTouchTargets(geometry.points, `${width}px release controls`);
    for (const point of geometry.points) {
        assert.ok(point.left >= geometry.chart.left - 0.6, `${width}px ${point.id} clips left`);
        assert.ok(point.right <= geometry.chart.right + 0.6, `${width}px ${point.id} clips right`);
        assert.ok(point.top >= geometry.chart.top - 0.6, `${width}px ${point.id} clips top`);
        assert.ok(point.bottom <= geometry.chart.bottom + 0.6, `${width}px ${point.id} clips bottom`);
    }
    if (geometry.minimumActualSpacing < geometry.declaredSpacing) {
        assert.ok(geometry.displacedIds.length > 0, `${width}px overlapping data points were not offset`);
    }

    const dialog = page.locator('#model-detail-dialog');
    for (const modelId of geometry.points.map((point) => point.id)) {
        const point = page.locator(`.release-point-button[data-model-id="${modelId}"]`);
        await point.scrollIntoViewIfNeeded();
        await point.click({ position: { x: 22, y: 22 } });
        await page.locator('#model-detail-dialog[open]').waitFor();
        assert.equal(await dialog.getAttribute('data-model-id'), modelId, `${width}px clicked ${modelId}`);
        await closeDialog(page);
    }

    if (width === 375) {
        const touchModelId = 'claude-opus-4-6';
        await page.locator(`.release-point-button[data-model-id="${touchModelId}"]`).tap({
            position: { x: 22, y: 22 },
        });
        await page.locator('#model-detail-dialog[open]').waitFor();
        assert.equal(await dialog.getAttribute('data-model-id'), touchModelId, 'touch tap maps to Opus');
        await page.locator('[data-dialog-close]').tap();
        await waitForDialogClosed(page);
    }

    if (width === 768) {
        const keyboardModelId = 'claude-opus-4-6';
        const keyboardPoint = page.locator(`.release-point-button[data-model-id="${keyboardModelId}"]`);
        const baselineCoordinates = await page.locator('.release-point-button').evaluateAll(
            (buttons) => buttons.map((button) => [
                button.dataset.modelId,
                button.dataset.actualX,
                button.dataset.actualY,
                button.dataset.displayX,
                button.dataset.displayY,
            ]),
        );
        let generation = Number(await page.locator('#release-chart').getAttribute('data-layout-generation'));

        await keyboardPoint.focus();
        await keyboardPoint.press('Enter');
        await page.locator('#model-detail-dialog[open]').waitFor();
        await page.setViewportSize({ width: 770, height: 900 });
        await page.waitForFunction((previousGeneration) => (
            document.querySelector('#release-chart')?.dataset.pointLayoutReady === 'true'
            && Number(document.querySelector('#release-chart').dataset.layoutGeneration) > previousGeneration
        ), generation);
        await closeDialog(page, 'escape');
        await page.waitForFunction((modelId) => document.activeElement?.dataset?.modelId === modelId, keyboardModelId);

        generation = Number(await page.locator('#release-chart').getAttribute('data-layout-generation'));
        await page.setViewportSize({ width: 768, height: 900 });
        await page.waitForFunction((previousGeneration) => (
            document.querySelector('#release-chart')?.dataset.pointLayoutReady === 'true'
            && Number(document.querySelector('#release-chart').dataset.layoutGeneration) > previousGeneration
        ), generation);
        const restoredCoordinates = await page.locator('.release-point-button').evaluateAll(
            (buttons) => buttons.map((button) => [
                button.dataset.modelId,
                button.dataset.actualX,
                button.dataset.actualY,
                button.dataset.displayX,
                button.dataset.displayY,
            ]),
        );
        assert.deepEqual(restoredCoordinates, baselineCoordinates, 'release layout redraw is deterministic');

        await page.keyboard.press('Space');
        await page.locator('#model-detail-dialog[open]').waitFor();
        assert.equal(await dialog.getAttribute('data-model-id'), keyboardModelId, 'Space opens release point');
        await closeDialog(page, 'escape');
        assert.equal(
            await page.evaluate(() => document.activeElement?.dataset?.modelId),
            keyboardModelId,
            'release focus returns after Space and Escape',
        );
    }
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

    const defaultDetail = await page.locator('#subfield-detail').evaluate((detail) => {
        const kicker = detail.querySelector('.subfield-detail-kicker').getBoundingClientRect();
        const title = detail.querySelector(':scope > strong').getBoundingClientRect();
        return {
            overlap: Math.max(0, Math.min(kicker.bottom, title.bottom) - Math.max(kicker.top, title.top)),
            height: detail.getBoundingClientRect().height,
        };
    });
    assert.equal(defaultDetail.overlap, 0, `${width}px default subfield labels collide`);
    assert.ok(defaultDetail.height < 180, `${width}px default subfield detail is too tall`);

    const first = rows.first();
    await first.focus();
    const expected = {
        name: await first.getAttribute('data-subfield-name'),
        sample: await first.getAttribute('data-sample-size'),
        intervention: one(await first.getAttribute('data-intervention-accuracy')),
        market: one(await first.getAttribute('data-market-accuracy')),
        gap: signed(await first.getAttribute('data-gap'), ' pp'),
    };
    await page.waitForFunction(() => /preview/i.test(document.querySelector('#subfield-detail').innerText));
    const preview = await page.locator('#subfield-detail').innerText();
    for (const value of [expected.name, `n=${expected.sample}`, `${expected.intervention}%`, `${expected.market}%`, expected.gap]) {
        assert.ok(preview.includes(value), `${width}px subfield preview is missing ${value}`);
    }
    if (width === 375) await first.tap();
    else await first.click();
    assert.equal(await first.getAttribute('aria-expanded'), 'true', `${width}px subfield pin state`);
    assert.match(await page.locator('#subfield-detail').innerText(), /Pinned selection/i);
    const pinnedLayout = await page.locator('#subfield-detail').evaluate((detail) => {
        const metrics = [...detail.querySelectorAll('dl > div')];
        const tops = metrics.map((metric) => Math.round(metric.getBoundingClientRect().top));
        return {
            count: metrics.length,
            rows: new Set(tops).size,
            height: detail.getBoundingClientRect().height,
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
    await page.mouse.move(1, 1);
    assert.match(await page.locator('#subfield-detail').innerText(), /Pinned selection/i);
    await first.focus();
    await page.keyboard.press('Escape');
    assert.equal(await first.getAttribute('aria-expanded'), 'false', `${width}px subfield Escape state`);
    assert.match(await page.locator('#subfield-detail').innerText(), /Select a subfield/);
}

async function validateModelDialog(page, width) {
    const model = paperData.models[0];
    const trigger = page.locator(`.model-open-button[data-model-id="${model.id}"]`);
    await trigger.focus();
    await page.waitForFunction(() => !document.querySelector('#model-quick-detail').hidden);
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
    assert.equal(await page.locator('#model-tab-icl, #model-panel-icl').count(), 0, `${width}px ICL UI remains`);
    assert.equal(await page.locator('#model-panel-overview .metric-card').count(), 6);
    const overviewText = await page.locator('#model-panel-overview').innerText();
    assert.match(overviewText, /Same-sign accuracy/);
    assert.match(overviewText, /Different-sign accuracy/);
    assert.match(overviewText, /Same predicted sign/);
    assert.match(overviewText, /Different predicted signs/);
    assert.doesNotMatch(overviewText, /views agree|views differ|non-contested|ideology-contested/i);
    assert.match(overviewText, /Accuracy gap/);
    assert.match(overviewText, /Error-direction bias/);
    assert.equal(await page.locator('#model-panel-overview .metric-definition-grid > section').count(), 4);
    assert.equal(await page.locator('#model-panel-overview [aria-label="Intervention-oriented sign equals market-oriented sign"]').count(), 1);
    assert.equal(await page.locator('#model-panel-overview [aria-label="Intervention-oriented sign does not equal market-oriented sign"]').count(), 1);
    assert.equal(await page.locator('#model-panel-overview [aria-label*="divided by all prediction errors"]').count(), 1);
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
    assert.equal(signedOverview.direction, 'Intervention-aligned advantage');
    assert.notEqual(signedOverview.color, neutralMetricColor);
    const signedBias = await page.locator('#model-panel-overview .metric-card').nth(5).evaluate((card) => ({
        className: card.className,
        color: getComputedStyle(card.querySelector('dd')).color,
        direction: card.querySelector('.metric-direction')?.textContent.trim(),
    }));
    assert.match(signedBias.className, /is-intervention/);
    assert.equal(signedBias.direction, 'Intervention-oriented');
    assert.notEqual(signedBias.color, neutralMetricColor);

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
        && document.querySelector('#model-quick-detail .quick-detail-grid > div:nth-child(3) dd')?.textContent.includes('1.9')
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
    assert.match(negativeQuickMetrics[0].text, /[−-]1\.9/);
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
    assert.match(negativeMetrics[0].value, /[−-]1\.9/);
    assert.match(negativeMetrics[1].className, /is-market/);
    assert.notEqual(negativeMetrics[1].color, neutralMetricColor);
    assert.equal(negativeMetrics[0].color, negativeMetrics[1].color);
    assert.equal(negativeMetrics[0].background, negativeMetrics[1].background);
    assert.equal(negativeMetrics[0].background, neutralMetricBackground);
    assert.equal(negativeMetrics[0].direction, 'Market-aligned advantage');
    assert.equal(negativeMetrics[1].direction, 'Market-oriented');
    await closeDialog(page);
}

async function validateDirectionalRanking(page, width) {
    const list = page.locator('#bias-ranking-list');
    assert.equal(await list.evaluate((element) => element.tagName), 'OL');
    const rows = list.locator('.bias-ranking-row');
    assert.equal(await rows.count(), 20, `${width}px directional rows`);
    const visibleRows = await rows.evaluateAll((buttons) => buttons.map((button, index) => ({
        index,
        label: button.getAttribute('aria-label'),
        name: button.querySelector('.bias-model-name')?.textContent.trim(),
        score: button.querySelector('strong, .bias-static-score')?.textContent.trim(),
        direction: button.querySelector('.bias-direction')?.textContent.trim(),
        width: button.getBoundingClientRect().width,
        height: button.getBoundingClientRect().height,
    })));
    checkTouchTargets(visibleRows, `${width}px directional controls`);
    visibleRows.forEach((row) => {
        assert.ok(row.name && /^[+−]?\d+\.\d$/.test(row.score), `${width}px ranked row ${row.index + 1} lacks visible name/score`);
        assert.ok(['Intervention-oriented', 'Market-oriented', 'Balanced'].includes(row.direction));
        assert.match(row.label, new RegExp(`^Rank ${row.index + 1} of 20,`));
        assert.ok(row.label.includes(row.name));
        assert.ok(row.label.includes(row.score));
        assert.ok(row.label.includes(row.direction));
    });

    await rows.first().focus();
    await page.waitForFunction(() => !document.querySelector('#model-quick-detail').hidden);
    assert.match(await page.locator('#model-quick-detail').innerText(), /Bdir|B\s*dir/i);
    await page.keyboard.press('Tab');

    if (width === 1024) {
        await rows.last().scrollIntoViewIfNeeded();
        await rows.last().hover();
        await page.waitForFunction(() => !document.querySelector('#model-quick-detail').hidden);
        assert.match(await page.locator('#model-quick-detail').innerText(), /Bdir|B\s*dir/i);
        await page.mouse.move(1, 1);
    }

    if (width === 1024) {
        for (let index = 0; index < 20; index += 1) {
            const row = rows.nth(index);
            const modelId = await row.getAttribute('data-model-id');
            await row.scrollIntoViewIfNeeded();
            await row.click();
            await page.locator('#model-detail-dialog[open]').waitFor();
            assert.equal(await page.locator('#model-detail-dialog').getAttribute('data-model-id'), modelId);
            await closeDialog(page);
        }
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
    await page.locator('.release-point-button').first().waitFor();
    assert.equal(await page.locator('.model-open-button').count(), 20, `${width}px model triggers`);
    assert.equal(await page.locator('.release-point-button').count(), 20, `${width}px chart points`);
    assert.equal(await page.locator('.bias-ranking-row').count(), 20, `${width}px directional rows`);
    assert.equal(await page.locator('.subfield-row').count(), 7, `${width}px subfield rows`);
    assert.equal(await page.locator('[id*="compare"], [class*="compare-"]').count(), 0, `${width}px compare UI remains`);
    assert.doesNotMatch(await page.locator('body').innerText(), /�/, `${width}px replacement glyph`);

    const rowBackgrounds = await page.evaluate(() => Object.fromEntries(
        ['gpt-4o-mini', 'claude-sonnet-4-6', 'claude-opus-4-6'].map((modelId) => [
            modelId,
            getComputedStyle(document.querySelector(`.model-score-row[data-model-id="${modelId}"]`)).backgroundColor,
        ]),
    ));
    assert.equal(rowBackgrounds['claude-sonnet-4-6'], rowBackgrounds['gpt-4o-mini'], `${width}px Sonnet row background`);
    assert.equal(rowBackgrounds['claude-opus-4-6'], rowBackgrounds['gpt-4o-mini'], `${width}px Opus row background`);

    const mainGapColors = await page.evaluate(() => {
        const interventionAccent = getComputedStyle(document.querySelector('.bias-ranking-row.is-intervention > strong, .bias-ranking-row.is-intervention .bias-static-score')).color;
        const marketAccent = getComputedStyle(document.querySelector('.bias-ranking-row.is-market > strong, .bias-ranking-row.is-market .bias-static-score')).color;
        const firstScoreBars = getComputedStyle(document.querySelector('.model-score-bars'));
        return {
            interventionAccent,
            marketAccent,
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
    assert.equal(mainGapColors.positive.color, mainGapColors.interventionAccent, `${width}px positive gap is not intervention green`);
    assert.match(mainGapColors.positive.text, /\+/);
    for (const [name, metric] of Object.entries({ Sonnet: mainGapColors.sonnet, Opus: mainGapColors.opus })) {
        assert.equal(metric.color, mainGapColors.marketAccent, `${width}px ${name} gap is not market orange`);
        assert.match(metric.text, /[−-]/, `${width}px ${name} gap lost its minus sign`);
    }

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
    await validateDirectionalRanking(page, width);
    await validateReleasePointLayoutAndClicks(page, width);
    await validateModelDialog(page, width);

    if (width === 768) {
        const reducedMotionDisplays = await page.evaluate(() => Object.fromEntries(
            ['.model-open-button', '.release-point-button', '.bias-ranking-row', '.subfield-row']
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

    if (width === 320 || width === 1024) await runAxe(page, `${width}px`);

    if (width === 1440 || width === 320) {
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
    assert.equal(await noJsPage.locator('.bias-ranking-row').count(), 20);
    assert.equal(await noJsPage.locator('.subfield-row').count(), 7);
    assert.match(await noJsPage.locator('body').innerText(), /10,490.*1,056.*751/s);
    assert.doesNotMatch(await noJsPage.locator('body').innerText(), /�/);
    const noJsWidth = await noJsPage.evaluate(() => [document.documentElement.scrollWidth, document.documentElement.clientWidth]);
    assert.ok(noJsWidth[0] <= noJsWidth[1] + 1, 'no-JS page overflows at 320px');
    await noJs.close();

    const failedData = await browser.newContext({ viewport: { width: 375, height: 800 } });
    const failedPage = await failedData.newPage();
    await failedPage.route('**/data/paper-data.v2.json', (route) => route.abort());
    await failedPage.goto(baseUrl, { waitUntil: 'networkidle' });
    assert.equal(await failedPage.locator('.model-score-row').count(), 20);
    assert.equal(await failedPage.locator('.bias-ranking-row').count(), 20);
    assert.equal(await failedPage.locator('.subfield-row').count(), 7);
    assert.match(await failedPage.locator('.copy-status').textContent(), /temporarily unavailable/i);
    const failedWidth = await failedPage.evaluate(() => [document.documentElement.scrollWidth, document.documentElement.clientWidth]);
    assert.ok(failedWidth[0] <= failedWidth[1] + 1, 'data-failure page overflows at 375px');
    await failedData.close();
}

(async () => {
    assert.equal(paperData.models.length, 20, 'paper baseline model count');
    assert.ok(paperData.models.every((model) => model.subfields?.length === 7), '20×7 subfield data');
    assert.equal(paperData.examples.length, 2, 'representative examples');
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
