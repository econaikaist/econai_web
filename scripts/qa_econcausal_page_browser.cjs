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
            const page = await browser.newPage({ viewport: { width, height: 1000 } });
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
            await page.waitForFunction(() => document.querySelectorAll('[data-model-id]').length === 18);

            assert.equal(consoleErrors.length, 0, `${width}px console errors: ${consoleErrors.join('\n')}`);
            assert.equal(failedRequests.length, 0, `${width}px request failures: ${failedRequests.join('\n')}`);
            assert.equal(await page.locator('#case-select option[data-case-id]').count(), 8, `${width}px curated case count`);
            assert.equal(await page.locator('[data-model-id]').count(), 18, `${width}px model count`);

            const geometry = await page.evaluate(() => ({
                documentWidth: document.documentElement.scrollWidth,
                viewportWidth: window.innerWidth,
                elements: [...document.querySelectorAll('main section, [data-model-id], #case-select')]
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

            const resultsMode = page.locator('[data-view-mode="results"]');
            const exploreMode = page.locator('[data-view-mode="explore"]');
            await resultsMode.click();
            assert.equal(await resultsMode.getAttribute('aria-pressed'), 'true', `${width}px results mode pressed`);
            assert.equal(await page.locator('#context-lab').isVisible(), false, `${width}px lab remains visible`);
            await exploreMode.click();
            assert.equal(await exploreMode.getAttribute('aria-pressed'), 'true', `${width}px explore mode pressed`);
            assert.equal(await page.locator('#context-lab').isVisible(), true, `${width}px lab is hidden`);

            const firstChoice = page.locator('[data-sign-choice]').first();
            await firstChoice.click();
            const reveal = page.locator('[data-case-reveal]');
            if (await reveal.count()) await reveal.click();
            assert.equal(await page.locator('[data-case-result]').isVisible(), true, `${width}px reveal feedback hidden`);

            const firstModel = page.locator('[data-model-id]').first();
            await firstModel.focus();
            await firstModel.press('Enter');
            const dialog = page.locator('#model-detail-dialog');
            await dialog.waitFor({ state: 'visible' });
            assert.equal(await dialog.getAttribute('open'), '', `${width}px model dialog did not open`);
            await page.keyboard.press('Escape');
            await page.waitForFunction(() => !document.querySelector('#model-detail-dialog').open);
            assert.equal(await firstModel.evaluate((element) => element === document.activeElement), true, `${width}px focus not restored`);

            await checkTouchTargets(page.locator('[data-view-mode], [data-case-id], [data-sign-choice]'), `${width}px control`);
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
