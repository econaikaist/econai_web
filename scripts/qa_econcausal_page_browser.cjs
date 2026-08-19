#!/usr/bin/env node
/* Browser QA for the interactive EconCausal paper page. */

const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const { chromium } = require('playwright-core');

const baseUrl = process.env.ECONCAUSAL_PAGE_URL || 'http://127.0.0.1:8765/econcausal/';
const executablePath = process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE || '/snap/bin/chromium';
const screenshotDir = process.env.ECONCAUSAL_QA_SCREENSHOT_DIR || '/tmp/econcausal-page-qa';
const skipScreenshots = process.env.ECONCAUSAL_QA_SKIP_SCREENSHOTS === '1';
const viewports = (process.env.ECONCAUSAL_QA_VIEWPORTS || '320,375,768,1024,1440,1920')
    .split(',')
    .map((value) => Number(value.trim()))
    .filter((value) => Number.isFinite(value) && value > 0);
const expectedTaskOrder = ['task1_econ', 'task1_finance', 'task2_overall', 'task3'];

function visibleOverflow(metrics, width) {
    return metrics.filter((item) => item.visible && (item.left < -1 || item.right > width + 1));
}

async function checkTouchTargets(locator, label) {
    const metrics = await locator.evaluateAll((elements) => elements
        .filter((element) => element.getClientRects().length > 0)
        .map((element) => {
            const rect = element.getBoundingClientRect();
            return { label: element.textContent.trim(), width: rect.width, height: rect.height };
        }));
    for (const metric of metrics) {
        assert.ok(
            metric.width >= 43.5 && metric.height >= 43.5,
            `${label} ${metric.label}: ${metric.width}x${metric.height} is below 44px`,
        );
    }
}

async function main() {
    if (!skipScreenshots) fs.mkdirSync(screenshotDir, { recursive: true });
    const browser = await chromium.launch({ executablePath, headless: true });
    try {
        for (const width of viewports) {
            const height = width <= 320 ? 700 : width <= 375 ? 812 : width <= 768 ? 720 : width <= 1024 ? 768 : width <= 1440 ? 900 : 1080;
            const page = await browser.newPage({ viewport: { width, height } });
            const consoleErrors = [];
            const failedRequests = [];
            page.on('console', (message) => {
                if (message.type() === 'error') consoleErrors.push(message.text());
            });
            page.on('requestfailed', (request) => {
                failedRequests.push(`${request.url()}: ${request.failure()?.errorText || 'failed'}`);
            });
            await page.emulateMedia({ reducedMotion: 'reduce' });
            await page.goto(baseUrl, { waitUntil: 'networkidle' });
            await page.waitForFunction(() => (
                document.querySelectorAll('[data-family-panel]').length === 5
                && document.querySelectorAll('[data-model-id]').length === 18
                && document.querySelectorAll('[data-accuracy-bar]').length === 72
            ));

            assert.equal(consoleErrors.length, 0, `${width}px console errors: ${consoleErrors.join('\n')}`);
            assert.equal(failedRequests.length, 0, `${width}px request failures: ${failedRequests.join('\n')}`);
            assert.equal(await page.locator('#context-lab').count(), 0, `${width}px Context Lab must be absent`);
            assert.equal(await page.locator('#calibration-chart').count(), 0, `${width}px calibration must be absent`);
            assert.equal(await page.locator('[data-family-panel]').count(), 5, `${width}px family panel count`);
            assert.equal(await page.locator('[data-model-id]').count(), 18, `${width}px model count`);
            assert.equal(await page.locator('[data-accuracy-bar][data-task]').count(), 72, `${width}px accuracy bar count`);

            const sceneContract = await page.evaluate(() => {
                const headerHeight = document.querySelector('.paper-nav').getBoundingClientRect().height;
                const scenes = [...document.querySelectorAll('main > .scene')].map((scene) => ({
                    id: scene.id || 'closing',
                    height: scene.getBoundingClientRect().height,
                    clientHeight: scene.clientHeight,
                    scrollHeight: scene.scrollHeight,
                    snapAlign: getComputedStyle(scene).scrollSnapAlign,
                    snapStop: getComputedStyle(scene).scrollSnapStop,
                }));
                const title = document.querySelector('#paper-title').getBoundingClientRect();
                const concept = document.querySelector('.hero-concept').getBoundingClientRect();
                return {
                    headerHeight,
                    viewportHeight: window.innerHeight,
                    scrollSnapType: getComputedStyle(document.documentElement).scrollSnapType,
                    scenes,
                    titleBottom: title.bottom,
                    conceptTop: concept.top,
                };
            });
            assert.equal(sceneContract.scrollSnapType, 'y mandatory', `${width}px document snap type`);
            assert.deepEqual(sceneContract.scenes.slice(0, 3).map((scene) => scene.id), ['overview', 'benchmark', 'construction'], `${width}px scene order`);
            for (const scene of sceneContract.scenes) {
                assert.equal(scene.snapAlign, 'start', `${width}px ${scene.id} snap alignment`);
                assert.equal(scene.snapStop, 'always', `${width}px ${scene.id} snap stop`);
                assert.ok(
                    Math.abs(scene.height - (sceneContract.viewportHeight - sceneContract.headerHeight)) <= 1,
                    `${width}px ${scene.id} is not one viewport tall`,
                );
                assert.ok(scene.scrollHeight <= scene.clientHeight + 1, `${width}px ${scene.id} content is clipped`);
            }
            assert.ok(sceneContract.titleBottom <= sceneContract.conceptTop + 1, `${width}px title overlaps concept figure`);

            await page.locator('.hero-actions a[href="#benchmark"]').click();
            await page.waitForTimeout(500);
            const linkedBenchmarkTop = await page.locator('#benchmark').evaluate((element) => element.getBoundingClientRect().top);
            assert.ok(
                Math.abs(linkedBenchmarkTop - sceneContract.headerHeight) <= 3,
                `${width}px results link did not align the benchmark scene: ${linkedBenchmarkTop}`,
            );

            await page.evaluate(() => window.scrollTo(0, 0));
            await page.mouse.wheel(0, 900);
            await page.waitForTimeout(500);
            const snappedBenchmarkTop = await page.locator('#benchmark').evaluate((element) => element.getBoundingClientRect().top);
            assert.ok(
                Math.abs(snappedBenchmarkTop - sceneContract.headerHeight) <= 3,
                `${width}px wheel did not stop on the benchmark scene: ${snappedBenchmarkTop}`,
            );

            const benchmarkLayout = await page.locator('[data-model-id]').evaluateAll((models) => models.map((model) => ({
                id: model.dataset.modelId,
                family: model.closest('[data-family-panel]')?.dataset.familyPanel || '',
                tasks: [...model.querySelectorAll('[data-accuracy-bar]')].map((bar) => bar.dataset.task),
                values: [...model.querySelectorAll('[data-accuracy-bar]')]
                    .map((bar) => Number.parseFloat(bar.style.getPropertyValue('--score'))),
            })));
            assert.equal(new Set(benchmarkLayout.map((model) => model.id)).size, 18, `${width}px unique model IDs`);
            assert.equal(new Set(benchmarkLayout.map((model) => model.family)).size, 5, `${width}px represented families`);
            for (const model of benchmarkLayout) {
                assert.deepEqual(model.tasks, expectedTaskOrder, `${width}px ${model.id} task order`);
                assert.ok(
                    model.values.every((value) => Number.isFinite(value) && value >= 0 && value <= 100),
                    `${width}px ${model.id} accuracy bar values`,
                );
            }

            const geometry = await page.evaluate(() => ({
                documentWidth: document.documentElement.scrollWidth,
                viewportWidth: window.innerWidth,
                familyOverflow: [...document.querySelectorAll('[data-family-panel]')]
                    .filter((element) => element.getClientRects().length > 0)
                    .map((element) => ({
                        family: element.dataset.familyPanel,
                        clientWidth: element.clientWidth,
                        scrollWidth: element.scrollWidth,
                    })),
                elements: [...document.querySelectorAll('main > section, #family-chart')]
                    .map((element) => {
                        const rect = element.getBoundingClientRect();
                        return {
                            name: element.id || element.dataset.modelId || element.dataset.caseId || element.tagName,
                            visible: element.getClientRects().length > 0,
                            left: rect.left,
                            right: rect.right,
                        };
                    }),
            }));
            assert.ok(
                geometry.documentWidth <= geometry.viewportWidth + 1,
                `${width}px document overflows by ${geometry.documentWidth - geometry.viewportWidth}px`,
            );
            assert.deepEqual(visibleOverflow(geometry.elements, width), [], `${width}px visible elements overflow`);
            for (const panel of geometry.familyOverflow) {
                assert.ok(
                    panel.scrollWidth <= panel.clientWidth + 1,
                    `${width}px ${panel.family} panel has internal horizontal overflow`,
                );
            }

            const familyStatus = page.locator('#family-status');
            assert.match(await familyStatus.textContent(), /Gemini/, `${width}px initial family status`);
            await page.locator('#family-next').click();
            await page.waitForFunction(() => document.querySelector('#family-status')?.textContent.includes('OpenAI'));
            assert.ok(await page.locator('#family-chart').evaluate((element) => element.scrollLeft > 0), `${width}px family chart did not move`);
            await page.locator('#family-prev').click();
            await page.waitForFunction(() => document.querySelector('#family-status')?.textContent.includes('Gemini'));

            const firstModel = page.locator('[data-model-id]').first();
            await firstModel.focus();
            await firstModel.press('Enter');
            const dialog = page.locator('#model-detail-dialog');
            await dialog.waitFor({ state: 'visible' });
            assert.equal(await dialog.getAttribute('open'), '', `${width}px model dialog did not open`);
            await page.keyboard.press('Escape');
            await page.waitForFunction(() => !document.querySelector('#model-detail-dialog').open);
            await page.waitForFunction(() => document.querySelector('[data-model-id]') === document.activeElement);
            assert.equal(await firstModel.evaluate((element) => element === document.activeElement), true, `${width}px focus not restored`);

            await checkTouchTargets(
                page.locator('#family-prev, #family-next, [data-model-id], [data-dialog-close]'),
                `${width}px control`,
            );
            if (!skipScreenshots) {
                await page.screenshot({
                    path: path.join(screenshotDir, `econcausal-${width}.png`),
                    fullPage: true,
                });
            }
            await page.close();
        }
    } finally {
        await browser.close();
    }
    process.stdout.write(`EconCausal browser QA passed at ${viewports.join(', ')}px.\n`);
}

main().catch((error) => {
    console.error(error.stack || error);
    process.exitCode = 1;
});
