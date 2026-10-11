import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";

import { NotificationsPage } from "../src/pages/NotificationsPage";
import { mockFetch, renderWithProviders } from "./render";

const EVENTS = [
  { name: "backup_failed", severity: "error" },
  { name: "backup_succeeded", severity: "info" },
];
const SETTINGS = {
  rules: {
    backup_failed: { enabled: true, channels: ["bale", "telegram", "webhook"] },
    backup_succeeded: { enabled: true, channels: ["bale", "telegram", "webhook"] },
  },
  cooldown_minutes: 60,
  stale_hours: 26,
  disk_free_percent: 10,
  daily_summary_time: "08:00",
  timezone: "Asia/Tehran",
  webhook_enabled: true,
  webhook_url: "https://hooks.example.com/x",
  has_webhook_secret: true,
  events: EVENTS,
};
const LOG = {
  items: [
    {
      id: 1,
      created_at: "2026-10-11T10:00:00Z",
      event: "backup_failed",
      severity: "error",
      subject: "backup_failed:1:shop",
      params: { instance: "prod", db: "shop", reason: "missing_privileges" },
      run_id: 5,
      channels: { bale: "sent: 1", webhook: "failed: HTTP 500" },
      suppressed: false,
    },
    {
      id: 2,
      created_at: "2026-10-11T10:05:00Z",
      event: "backup_failed",
      severity: "error",
      subject: "backup_failed:1:shop",
      params: { instance: "prod", db: "shop", reason: "again" },
      run_id: 6,
      channels: {},
      suppressed: true,
    },
  ],
  total: 2,
  page: 1,
  page_size: 25,
};
const bodyOf = (init?: RequestInit) => JSON.parse(String(init?.body));

function api() {
  return mockFetch((url, init) => {
    if (url === "/api/notifications/settings" && init.method === "PUT")
      return { status: 200, body: { ...SETTINGS, ...bodyOf(init) } };
    if (url === "/api/notifications/settings") return { status: 200, body: SETTINGS };
    if (url.startsWith("/api/notifications/log")) return { status: 200, body: LOG };
    if (url === "/api/notifications/test")
      return { status: 200, body: { results: { bale: "sent: 1", webhook: "failed: HTTP 500" } } };
    return { status: 200, body: {} };
  });
}

describe("NotificationsPage", () => {
  it("turns off a rule and a channel, keeping the stored webhook secret", async () => {
    const fetchMock = api();
    renderWithProviders(<NotificationsPage />);
    const row = await screen.findByTestId("rule-backup_succeeded");
    await userEvent.click(within(row).getByRole("switch"));
    const failed = screen.getByTestId("rule-backup_failed");
    await userEvent.click(within(failed).getByRole("checkbox", { name: "Webhook" }));
    await userEvent.click(screen.getByRole("button", { name: "Save" }));
    await waitFor(() =>
      expect(fetchMock.mock.calls.some(([, i]) => i?.method === "PUT")).toBe(true),
    );
    const body = bodyOf(fetchMock.mock.calls.find(([, i]) => i?.method === "PUT")![1]);
    expect(body.rules.backup_succeeded.enabled).toBe(false);
    expect(body.rules.backup_failed.channels).toEqual(["bale", "telegram"]);
    expect(body.webhook_secret).toBe("");
    expect(body.clear_webhook_secret).toBe(false);
  });

  it("shows test results per channel", async () => {
    api();
    renderWithProviders(<NotificationsPage />);
    await userEvent.click(
      await screen.findByRole("button", { name: "Send a test alert to all channels" }),
    );
    const results = await screen.findByTestId("test-results");
    expect(results).toHaveTextContent("Bale: sent");
    expect(results).toHaveTextContent("Webhook: failed");
  });

  it("renders the alert history with suppressed repeats", async () => {
    api();
    renderWithProviders(<NotificationsPage />);
    const history = await screen.findByTestId("alert-history");
    expect(
      within(history).getByText("Backup of “shop” on “prod” failed: missing_privileges"),
    ).toBeInTheDocument();
    expect(within(history).getByText("Repeat (not sent)")).toBeInTheDocument();
  });
});
