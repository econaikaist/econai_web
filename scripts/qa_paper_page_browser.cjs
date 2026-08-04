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
const viewports = [320, 375, 768, 1024, 1440, 1920];

function checkNewTouchTargets(metrics, label) {
    for (const target of metrics) {
        assert.ok(
            target.width >= 43.5 && target.height >= 43.5,
            `${label}: ${target.name} is ${target.width}×${target.height}, below 44px`,
        );
    }
}

async function addToCompare(page, modelId) {
    await page.locator(`.model-open-button[data-model-id="${modelId}"]`).evaluate((button) => button.click());
    await page.locator('#model-detail-dialog[open]').waitFor();
    await page.locator('#model-compare-toggle').click();
    await page.locator('[data-dialog-close]').click();
    await page.waitForFunction(() => !document.querySelector('#model-detail-dialog').open);
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
                centerX: rect.left + rect.width / 2,
                centerY: rect.top + rect.height / 2,
                left: rect.left,
                right: rect.right,
                top: rect.top,
                bottom: rect.bottom,
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
        const leaderIds = [...document.querySelectorAll('.release-leader-line')]
            .map((line) => line.dataset.modelId)
            .sort();
        const anchorIds = [...document.querySelectorAll('.release-data-anchor')]
            .map((anchor) => anchor.dataset.modelId)
            .sort();
        return {
            chart: { left: chart.left, right: chart.right, top: chart.top, bottom: chart.bottom },
            points,
            minimumCenterSpacing,
            minimumActualSpacing,
            displacedIds,
            leaderIds,
            anchorIds,
            declaredSpacing: Number(document.querySelector('#release-chart').dataset.minimumPointSpacing),
        };
    });

    assert.equal(geometry.points.length, 20, `${width}px release geometry point count`);
    assert.equal(new Set(geometry.points.map((point) => point.id)).size, 20, `${width}px release ids`);
    assert.equal(geometry.declaredSpacing, 48, `${width}px declared release spacing`);
    assert.ok(
        geometry.minimumCenterSpacing >= geometry.declaredSpacing - 0.6,
        `${width}px release centers only ${geometry.minimumCenterSpacing.toFixed(2)}px apart`,
    );
    for (const point of geometry.points) {
        assert.ok(point.left >= geometry.chart.left - 0.6, `${width}px ${point.id} clips left`);
        assert.ok(point.right <= geometry.chart.right + 0.6, `${width}px ${point.id} clips right`);
        assert.ok(point.top >= geometry.chart.top - 0.6, `${width}px ${point.id} clips top`);
        assert.ok(point.bottom <= geometry.chart.bottom + 0.6, `${width}px ${point.id} clips bottom`);
    }
    if (geometry.minimumActualSpacing < geometry.declaredSpacing) {
        assert.ok(geometry.displacedIds.length > 0, `${width}px overlapping data points were not offset`);
    }
    assert.deepEqual(geometry.leaderIds, geometry.displacedIds, `${width}px leader lines`);
    assert.deepEqual(geometry.anchorIds, geometry.displacedIds, `${width}px exact-coordinate anchors`);

    const dialog = page.locator('#model-detail-dialog');
    const modelIds = geometry.points.map((point) => point.id);
    for (const modelId of modelIds) {
        const point = page.locator(`.release-point-button[data-model-id="${modelId}"]`);
        await point.scrollIntoViewIfNeeded();
        await point.click({ position: { x: 22, y: 22 } });
        await page.locator('#model-detail-dialog[open]').waitFor();
        assert.equal(await dialog.getAttribute('data-model-id'), modelId, `${width}px clicked ${modelId}`);
        await page.locator('[data-dialog-close]').click();
        await page.waitForFunction(() => !document.querySelector('#model-detail-dialog').open);
    }

    if (width === 375) {
        const touchModelId = 'claude-opus-4-6';
        await page.locator(`.release-point-button[data-model-id="${touchModelId}"]`).tap({
            position: { x: 22, y: 22 },
        });
        await page.locator('#model-detail-dialog[open]').waitFor();
        assert.equal(await dialog.getAttribute('data-model-id'), touchModelId, 'touch tap maps to Opus');
        await page.locator('[data-dialog-close]').tap();
        await page.waitForFunction(() => !document.querySelector('#model-detail-dialog').open);
    }

    if (width === 768) {
        const keyboardModelId = 'claude-opus-4-6';
        const keyboardPoint = page.locator(
            `.release-point-button[data-model-id="${keyboardModelId}"]`,
        );
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
        await page.keyboard.press('Escape');
        await page.waitForFunction(() => !document.querySelector('#model-detail-dialog').open);
        await page.waitForFunction(
            (modelId) => document.activeElement?.dataset?.modelId === modelId,
            keyboardModelId,
        );
        assert.equal(
            await page.evaluate(() => document.activeElement?.dataset?.modelId),
            keyboardModelId,
            'release focus returns after redraw while dialog is open',
        );

        generation = Number(await page.locator('#release-chart').getAttribute('data-layout-generation'));
        await page.setViewportSize({ width: 768, height: 900 });
        await page.waitForFunction((previousGeneration) => (
            document.querySelector('#release-chart')?.dataset.pointLayoutReady === 'true'
            && Number(document.querySelector('#release-chart').dataset.layoutGeneration) > previousGeneration
        ), generation);
        assert.equal(
            await page.evaluate(() => document.activeElement?.dataset?.modelId),
            keyboardModelId,
            'release focus survives a focused-point redraw',
        );
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
        await page.keyboard.press('Escape');
        await page.waitForFunction(() => !document.querySelector('#model-detail-dialog').open);
        await page.waitForFunction(
            (modelId) => document.activeElement?.dataset?.modelId === modelId,
            keyboardModelId,
        );
        assert.equal(
            await page.evaluate(() => document.activeElement?.dataset?.modelId),
            keyboardModelId,
            'release focus returns after Space and Escape',
        );
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
    assert.equal(await page.locator('#release-data-table tbody tr').count(), 20, `${width}px data rows`);

    const layout = await page.evaluate(() => {
        const root = document.documentElement;
        const panel = document.querySelector('.subfield-panel').getBoundingClientRect();
        const rows = [...document.querySelectorAll('.subfield-row')].map((row) => {
            const rect = row.getBoundingClientRect();
            const value = row.querySelector(':scope > strong').getBoundingClientRect();
            return {
                scrollWidth: row.scrollWidth,
                clientWidth: row.clientWidth,
                right: rect.right,
                valueRight: value.right,
            };
        });
        const mainTargets = [...document.querySelectorAll('.model-open-button, .release-point-button')]
            .filter((element) => element.getClientRects().length)
            .map((element) => {
                const rect = element.getBoundingClientRect();
                return { name: element.className, width: rect.width, height: rect.height };
            });
        return {
            pageScrollWidth: root.scrollWidth,
            pageClientWidth: root.clientWidth,
            panelRight: panel.right,
            rows,
            mainTargets,
        };
    });
    assert.ok(layout.pageScrollWidth <= layout.pageClientWidth + 1, `${width}px document overflows`);
    for (const row of layout.rows) {
        assert.ok(row.scrollWidth <= row.clientWidth + 1, `${width}px subfield row internally clips`);
        assert.ok(row.valueRight <= layout.panelRight + 1, `${width}px subfield value clips`);
    }
    checkNewTouchTargets(layout.mainTargets, `${width}px main controls`);
    await validateReleasePointLayoutAndClicks(page, width);

    if (width === 320 || width === 1024) {
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
        assert.deepEqual(violations, [], `${width}px axe violations: ${JSON.stringify(violations)}`);
    }

    const firstTrigger = page.locator('.model-open-button').first();
    await firstTrigger.focus();
    await page.waitForFunction(() => {
        const detail = document.querySelector('#model-quick-detail');
        return !detail.hidden && /Intervention.*Market.*Gap.*Bdir/s.test(detail.innerText);
    });
    assert.match(await page.locator('#model-quick-detail').innerText(), /Intervention.*Market.*Gap.*Bdir/s);
    await firstTrigger.press('Enter');
    const dialog = page.locator('#model-detail-dialog');
    await dialog.waitFor();
    assert.equal(await dialog.getAttribute('open'), '');
    assert.ok(await dialog.evaluate((element) => element.contains(document.activeElement)), `${width}px focus entered dialog`);
    assert.equal(await page.locator('#model-panel-overview .metric-card').count(), 6);
    await page.locator('#model-tab-icl').click();
    assert.equal(await page.locator('#model-panel-icl .icl-target-card').count(), 2);
    await page.locator('#model-tab-examples').click();
    assert.equal(await page.locator('#model-panel-examples .example-card').count(), 2);

    if (width === 768) {
        const reducedMotionDisplays = await page.evaluate(() => ({
            dialog: getComputedStyle(document.querySelector('#model-detail-dialog')).display,
            model: getComputedStyle(document.querySelector('.model-open-button')).display,
            point: getComputedStyle(document.querySelector('.release-point-button')).display,
        }));
        assert.notEqual(reducedMotionDisplays.dialog, 'none', 'reduced-motion dialog hidden');
        assert.notEqual(reducedMotionDisplays.model, 'none', 'reduced-motion model control hidden');
        assert.notEqual(reducedMotionDisplays.point, 'none', 'reduced-motion release point hidden');
        await page.locator('#model-compare-toggle').click();
        assert.ok(await page.locator('#compare-tray').isVisible(), 'reduced-motion compare tray hidden');
        await page.locator('#model-compare-toggle').click();
    }

    const dialogTargets = await page.evaluate(() => [...document.querySelectorAll(
        '#model-detail-dialog[open] [data-dialog-close], #model-detail-dialog[open] [data-model-tab], #model-detail-dialog[open] #model-compare-toggle',
    )].filter((element) => element.getClientRects().length).map((element) => {
        const rect = element.getBoundingClientRect();
        return { name: element.id || element.className, width: rect.width, height: rect.height };
    }));
    checkNewTouchTargets(dialogTargets, `${width}px dialog controls`);
    for (let index = 0; index < 12; index += 1) {
        await page.keyboard.press('Tab');
        assert.ok(await dialog.evaluate((element) => element.contains(document.activeElement)), `${width}px focus escaped modal`);
    }
    await page.keyboard.press('Escape');
    await page.waitForFunction(() => !document.querySelector('#model-detail-dialog').open);
    assert.ok(await firstTrigger.evaluate((element) => element === document.activeElement), `${width}px focus did not return`);

    if (width === 1440) {
        await addToCompare(page, 'gpt-4o');
        await addToCompare(page, 'gpt-5-2');
        await addToCompare(page, 'qwen-3-8b');
        await addToCompare(page, 'grok-3-mini');
        assert.equal(await page.locator('.compare-card').count(), 3, 'desktop compare limit');
        assert.match(page.url(), /compare=gpt-4o%2Cgpt-5-2%2Cqwen-3-8b/);
        await page.locator('#compare-sort').selectOption('b_dir');
        assert.match(await page.locator('.compare-card').first().innerText(), /Qwen 3-8B/);
        await page.reload({ waitUntil: 'networkidle' });
        assert.equal(await page.locator('.compare-card').count(), 3, 'desktop URL restore');
    }

    if (width === 320) {
        await addToCompare(page, 'gpt-4o-mini');
        await addToCompare(page, 'gpt-4o');
        await addToCompare(page, 'gpt-5-nano');
        assert.equal(await page.locator('.compare-card').count(), 2, 'mobile compare limit');
        assert.match(page.url(), /compare=gpt-4o-mini%2Cgpt-4o/);
        const trayMetrics = await page.evaluate(() => {
            const root = document.documentElement;
            const tray = document.querySelector('#compare-tray').getBoundingClientRect();
            return { root: root.scrollWidth - root.clientWidth, left: tray.left, right: tray.right, width: innerWidth };
        });
        assert.ok(trayMetrics.root <= 1 && trayMetrics.left >= 0 && trayMetrics.right <= trayMetrics.width + 1);
    }

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
    assert.equal(await noJsPage.locator('.subfield-row').count(), 7);
    assert.match(await noJsPage.locator('body').innerText(), /10,490.*1,056.*751/s);
    assert.ok(await noJsPage.locator('.release-chart-fallback').isVisible());
    const noJsWidth = await noJsPage.evaluate(() => [document.documentElement.scrollWidth, document.documentElement.clientWidth]);
    assert.ok(noJsWidth[0] <= noJsWidth[1] + 1, 'no-JS page overflows at 320px');
    await noJs.close();

    const failedData = await browser.newContext({ viewport: { width: 375, height: 800 } });
    const failedPage = await failedData.newPage();
    await failedPage.route('**/data/paper-data.v2.json', (route) => route.abort());
    await failedPage.goto(baseUrl, { waitUntil: 'networkidle' });
    assert.equal(await failedPage.locator('.model-score-row').count(), 20);
    assert.ok(await failedPage.locator('.release-chart-fallback').isVisible());
    assert.match(await failedPage.locator('.copy-status').textContent(), /temporarily unavailable/i);
    await failedData.close();
}

(async () => {
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
