import { test, expect } from '@playwright/test';

test.describe('Dashboard Smoke E2E Tests', () => {
  test('renders topbar, left navigation, and redirects to /fleet', async ({ page }) => {
    await page.goto('/');
    await expect(page).toHaveURL(/.*\/fleet/);

    // Verify TopBar
    await expect(page.getByText('CloudSentinel')).toBeVisible();
    await expect(page.getByText('v2')).toBeVisible();

    // Verify Navigation Links
    await expect(page.getByRole('link', { name: /Fleet Overview/i })).toBeVisible();
    await expect(page.getByRole('link', { name: /Approvals Inbox/i })).toBeVisible();
    await expect(page.getByRole('link', { name: /Incidents Replay/i })).toBeVisible();
    await expect(page.getByRole('link', { name: /Cost & ROI/i })).toBeVisible();
  });

  test('navigates to approvals inbox and displays panels', async ({ page }) => {
    await page.goto('/approvals');
    await expect(page.getByText('Human-in-the-Loop Approvals Inbox')).toBeVisible();
    await expect(page.getByText(/Pending Tool Overrides/i)).toBeVisible();
  });

  test('navigates to cost & roi and displays metrics', async ({ page }) => {
    await page.goto('/cost');
    await expect(page.getByText('Cost Burn-Down & ROI Attribution')).toBeVisible();
    await expect(page.getByText('Economic Return Summary')).toBeVisible();
  });
});

test.describe('Keyboard-only run', () => {
  test('Tab reaches an agent card and Enter opens its page; J/K and shortcuts hint show in approvals', async ({ page }) => {
    await page.goto('/fleet');
    await expect(page.getByTestId('fleet-agent-grid')).toBeVisible();
    // Tab through the page until an agent card has focus, then open it with Enter
    for (let i = 0; i < 40; i++) {
      await page.keyboard.press('Tab');
      const id = await page.evaluate(() => document.activeElement?.getAttribute('data-testid') ?? '');
      if (id.startsWith('agent-card-')) break;
    }
    const focused = await page.evaluate(() => document.activeElement?.getAttribute('data-testid') ?? '');
    expect(focused).toMatch(/^agent-card-/);
    await page.keyboard.press('Enter');
    await expect(page).toHaveURL(/\/agents\//);

    await page.goto('/approvals');
    await expect(page.getByLabel('Keyboard shortcuts')).toBeVisible();
    await page.keyboard.press('j');
    await page.keyboard.press('k');
  });
});
