import { screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { OverviewPage } from "../src/pages/OverviewPage";
import { CurrentServerContext } from "../src/server/CurrentServer";
import { mockFetch, renderWithProviders } from "./render";
import { LOCAL, currentOn } from "./servers";

const RUN = {
  id: 1,
  instance_id: 2,
  instance_name: "prod-mysql",
  database_name: "shop",
  trigger: "schedule",
  schedule_id: null,
  status: "success",
  requested_at: new Date().toISOString(),
  started_at: null,
  finished_at: null,
  duration_ms: 1000,
  elapsed_ms: null,
  bytes_processed: 0,
  file_size: 2048,
  compression: "gzip",
  checksum_sha256: null,
  file_name: null,
  file_available: true,
  server_type: "mysql",
  server_version: "8.0",
  error_code: null,
  error_message: null,
  file_deleted_at: null,
  file_deleted_reason: null,
  remote_status: null,
  remote_uploaded_at: null,
  remote_deleted_at: null,
  remote_error: null,
  remote_available: false,
  remote_deletable_at: null,
  remote_deletable: false,
  download_available: true,
};
const CONTAINER = {
  id: "a1",
  name: "shop-web-1",
  image: "nginx",
  state: "running",
  health: null,
  created_at: null,
  started_at: null,
  finished_at: null,
  exit_code: 0,
  oom_killed: false,
  restart_count: 0,
  restart_policy: "always",
  project: null,
  service: null,
  panel: null,
  ports: [],
  locked: false,
  monitored: true,
  problem: null,
};
const PROJECT = {
  id: 3,
  name: "shop",
  server_id: 1,
  server_name: "main",
  last_deployment: {
    id: 9,
    project_id: 3,
    project_name: "shop",
    status: "failed",
    step: "build",
    ref: "main",
    commit_sha: "abcdef1234567890",
    commit_message: null,
    trigger: "panel",
    actor: "admin",
    error_code: "build_failed",
    error_detail: null,
    backup_run_ids: [],
    requested_at: "2026-10-12T08:00:00Z",
    started_at: null,
    finished_at: null,
  },
  last_success: null,
};

function serve({ healthy }: { healthy: boolean }) {
  const runs = healthy ? [RUN] : [RUN, { ...RUN, id: 2, status: "failed" }];
  const containers = healthy
    ? [CONTAINER]
    : [
        CONTAINER,
        { ...CONTAINER, id: "b2", name: "shop-worker-1", state: "exited", problem: "crashed" },
      ];
  const projects = healthy ? [] : [PROJECT];
  return mockFetch((url) => {
    if (url.includes("/backups/runs")) {
      return { status: 200, body: { items: runs, total: runs.length, page: 1, page_size: 200 } };
    }
    if (url.includes("/containers/-/info")) {
      return {
        status: 200,
        body: {
          docker: { name: "main" },
          host: {
            cpu_percent: 12,
            load: [0.1],
            memory_total: 1000,
            memory_available: 500,
            disk_total: 100,
            disk_free: 75,
          },
        },
      };
    }
    if (url.includes("/containers")) return { status: 200, body: { containers, read_only: false } };
    if (url.includes("/projects")) return { status: 200, body: projects };
    if (url.includes("/instances")) return { status: 200, body: [] };
    return { status: 404, body: { code: "not_found" } };
  });
}

function renderOverview() {
  renderWithProviders(
    <CurrentServerContext.Provider value={currentOn(LOCAL)}>
      <OverviewPage />
    </CurrentServerContext.Provider>,
  );
}

describe("OverviewPage", () => {
  it("lists what needs attention, each linking to its page", async () => {
    serve({ healthy: false });
    renderOverview();
    const section = await screen.findByRole("region", { name: "Needs attention" });
    const backups = await within(section).findByRole("link", {
      name: "1 backup failed in the last 24 hours",
    });
    expect(backups).toHaveAttribute("href", "/backups");
    expect(
      await within(section).findByRole("link", { name: "Container “shop-worker-1”: Crashed" }),
    ).toHaveAttribute("href", "/containers");
    expect(
      within(section).getByRole("link", { name: "The last deploy of “shop” failed" }),
    ).toHaveAttribute("href", "/projects/3");
    expect(screen.getByTestId("tile-containers")).toHaveTextContent("1 of 2 running");
    expect(screen.getByTestId("tile-server")).toHaveTextContent("RAM 50%");
  });

  it("says so when everything is fine", async () => {
    serve({ healthy: true });
    renderOverview();
    expect(await screen.findByText("Everything looks fine on this server.")).toBeInTheDocument();
    expect(screen.getByRole("heading", { level: 1, name: "Overview" })).toBeInTheDocument();
    expect(await screen.findByText("No deploys yet.")).toBeInTheDocument();
  });
});
