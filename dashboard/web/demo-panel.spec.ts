import { test, expect } from '@playwright/test';

test.describe('3 AM demo panel', () => {
  test.beforeEach(async ({ page }) => {
    await page.setViewportSize({ width: 1440, height: 900 });
    await page.goto('/fleet');
    await page.getByRole('button', { name: 'Run 3 AM Demo Incident' }).click();
    await expect(page.getByRole('dialog', { name: /3 AM incident/i })).toBeVisible();
  });

  test('can be dragged away so the page underneath is reachable', async ({ page }) => {
    const dialog = page.getByRole('dialog', { name: /3 AM incident/i });
    const before = (await dialog.boundingBox())!;
    // the page content under the panel is covered at first
    const coveredBefore = await page.evaluate(([x, y]) => !!document.elementFromPoint(x, y)?.closest('[role=dialog]'), [before.x + 100, before.y + 300]);
    expect(coveredBefore).toBe(true);

    const handle = page.getByTestId('demo-drag-handle');
    const h = (await handle.boundingBox())!;
    await page.mouse.move(h.x + 60, h.y + 12);
    await page.mouse.down();
    await page.mouse.move(h.x + 560, h.y + 140, { steps: 8 });
    await page.mouse.up();

    const after = (await dialog.boundingBox())!;
    expect(after.x).toBeGreaterThan(before.x + 400);
    expect(after.y).toBeGreaterThan(before.y + 100);
    // what was covered is now the page again, so it can be hovered
    const coveredAfter = await page.evaluate(([x, y]) => !!document.elementFromPoint(x, y)?.closest('[role=dialog]'), [before.x + 100, before.y + 300]);
    expect(coveredAfter).toBe(false);
  });

  test('stays on screen and moves with the arrow keys', async ({ page }) => {
    const dialog = page.getByRole('dialog', { name: /3 AM incident/i });
    const start = (await dialog.boundingBox())!;
    await page.getByTestId('demo-drag-handle').focus();
    await page.keyboard.press('ArrowRight');
    expect((await dialog.boundingBox())!.x).toBe(start.x + 24);
    for (let i = 0; i < 40; i++) await page.keyboard.press('Shift+ArrowRight');
    const b = (await dialog.boundingBox())!;
    expect(b.x + b.width).toBeLessThanOrEqual(1440);
  });

  test('minimizes to a small bar and expands again, keeping Start/Reset reachable', async ({ page }) => {
    const dialog = page.getByRole('dialog', { name: /3 AM incident/i });
    const full = (await dialog.boundingBox())!;
    await page.getByRole('button', { name: 'Minimize demo panel' }).click();
    await expect(page.getByRole('button', { name: 'Start demo' })).toHaveCount(0);
    const small = (await dialog.boundingBox())!;
    expect(small.height).toBeLessThan(full.height / 3);
    await page.getByRole('button', { name: 'Expand demo panel' }).click();
    await expect(page.getByRole('button', { name: 'Start demo' })).toBeVisible();
    await expect(page.getByTestId('demo-step-beta-ready').or(page.locator('[data-testid^=demo-step-]').first())).toBeVisible();
  });

  test('Escape still closes it', async ({ page }) => {
    await page.keyboard.press('Escape');
    await expect(page.getByRole('dialog', { name: /3 AM incident/i })).toHaveCount(0);
  });
});
