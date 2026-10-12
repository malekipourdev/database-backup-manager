import { describe, expect, it } from "vitest";

import { renderAlert } from "../src/alerts";
import type { NotificationLogItem } from "../src/api/notifications";
import i18n from "../src/i18n";

function item(event: string, params: Record<string, unknown>): NotificationLogItem {
  return {
    id: 1,
    created_at: "2026-10-11T08:00:00Z",
    event,
    severity: "error",
    subject: "s",
    params,
    run_id: null,
    channels: {},
    suppressed: false,
  };
}

const SAMPLES: [string, Record<string, unknown>][] = [
  ["container_down", { name: "web", exit_code: 1, oom: false }],
  ["container_down", { name: "web", exit_code: 137, oom: true }],
  ["container_restarting", { name: "web", restarts: 4, minutes: 10 }],
  ["container_unhealthy", { name: "web" }],
  ["container_resources", { name: "web", cpu: 97.4, memory_percent: 91, memory_usage: 1024 ** 3 }],
  ["host_resources", { kind: "disk", percent: 93.2, used: 9 * 1024 ** 3, total: 10 * 1024 ** 3 }],
  ["host_resources", { kind: "memory", percent: 91, used: 7 * 1024 ** 3, total: 8 * 1024 ** 3 }],
  ["agent_unreachable", { code: "agent_unreachable" }],
  ...[
    "container_down",
    "container_restarting",
    "container_unhealthy",
    "container_resources",
    "host_memory",
    "host_disk",
    "agent",
  ].map((kind): [string, Record<string, unknown>] => [
    "recovered",
    { kind, name: "web", percent: 40 },
  ]),
];

describe("container alerts", () => {
  it.each(["en", "fa"])("render in %s without missing keys", async (lang) => {
    await i18n.changeLanguage(lang);
    for (const [event, params] of SAMPLES) {
      const text = renderAlert(item(event, params), i18n.t, lang);
      expect(text).not.toMatch(/alerts\.|\{\{|undefined|NaN/);
    }
    await i18n.changeLanguage("en");
  });

  it("shows the numbers", async () => {
    await i18n.changeLanguage("en");
    expect(renderAlert(item("container_restarting", SAMPLES[2][1]), i18n.t, "en")).toBe(
      "Container “web” restarted 4 times in 10 minutes.",
    );
    expect(renderAlert(item("container_down", SAMPLES[1][1]), i18n.t, "en")).toMatch(
      /out of memory/,
    );
  });
});
