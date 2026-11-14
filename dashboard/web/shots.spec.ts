import { test } from '@playwright/test';
import fs from 'fs';
import path from 'path';

const routes = [
  { name: 'fleet', path: '/fleet' },
  { name: 'agent_detail', path: '/agents/beta' },
  { name: 'approvals', path: '/approvals' },
  { name: 'incidents', path: '/incidents' },
  { name: 'cost', path: '/cost' },
  { name: 'graph', path: '/graph' },
];

const resolutions = [
  { width: 1440, height: 900, label: '1440x900_laptop' },
  { width: 1920, height: 1080, label: '1920x1080_projector' },
];

test('capture daily screenshot review (10 PNGs)', async ({ page }) => {
  const dateStr = new Date().toISOString().split('T')[0];
  const shotsDir = path.resolve(process.cwd(), 'shots', dateStr);
  if (!fs.existsSync(shotsDir)) {
    fs.mkdirSync(shotsDir, { recursive: true });
  }

  for (const res of resolutions) {
    await page.setViewportSize({ width: res.width, height: res.height });
    for (const route of routes) {
      await page.goto(route.path, { waitUntil: 'networkidle' });
      // Short delay for rendering settle
      await page.waitForTimeout(500);
      const filename = `${route.name}_${res.label}.png`;
      await page.screenshot({ path: path.join(shotsDir, filename), fullPage: true });
    }
  }
});
