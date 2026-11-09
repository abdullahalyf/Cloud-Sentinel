import { test, expect } from '@playwright/test';
import AxeBuilder from '@axe-core/playwright';

const routes = ['/fleet', '/agents/beta', '/approvals', '/incidents', '/cost', '/graph'];

// D11: zero serious or critical accessibility violations on every page
for (const route of routes) {
  test(`axe: no serious violations on ${route}`, async ({ page }) => {
    await page.goto(route, { waitUntil: 'networkidle' });
    await page.waitForTimeout(500);
    const results = await new AxeBuilder({ page }).withTags(['wcag2a', 'wcag2aa']).analyze();
    const bad = results.violations.filter((v) => v.impact === 'serious' || v.impact === 'critical');
    const summary = bad.map((v) => `${v.id} (${v.impact}): ${v.nodes.length} nodes, e.g. ${v.nodes.map((n) => n.target?.join(" ") + " => " + (n.any[0]?.message ?? "")).join(" | ")}`);
    expect(summary, summary.join('\n')).toEqual([]);
  });
}
