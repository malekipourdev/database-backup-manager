import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";

import { ContainersPage } from "../src/pages/ContainersPage";
import { mockFetch, renderWithProviders } from "./render";

const base = {
  health: null,
  created_at: null,
  finished_at: null,
  exit_code: 0,
  oom_killed: false,
  restart_count: 0,
  restart_policy: "unless-stopped",
  panel: null,
  ports: [],
  locked: false,
  monitored: true,
  problem: null,
};
const CONTAINERS = [
  {
    ...base,
    id: "a1",
    name: "shop-web-1",
    image: "nginx:1.27",
    state: "running",
    started_at: new Date(Date.now() - 3_600_000).toISOString(),
    project: "shop",
    service: "web",
  },
  {
    ...base,
    id: "b2",
    name: "shop-worker-1",
    image: "shop:latest",
    state: "exited",
    started_at: null,
    exit_code: 1,
    project: "shop",
    service: "worker",
    problem: "crashed",
  },
  {
    ...base,
    id: "c3",
    name: "mbp-backend-1",
    image: "mbp-backend",
    state: "running",
    started_at: new Date().toISOString(),
    project: "mysql-backup-panel",
    service: "backend",
    panel: "panel",
    locked: true,
  },
];
const INFO = {
  docker: { version: "27.3.1", cpus: 4, running: 2, stopped: 1, images: 5, name: "srv" },
  host: {
    cpu_percent: 12.5,
    load: [0.5, 0.4, 0.3],
    memory_total: 8 * 1024 ** 3,
    memory_available: 2 * 1024 ** 3,
    disk_total: 100 * 1024 ** 3,
    disk_free: 40 * 1024 ** 3,
  },
};
const STATS = {
  stats: {
    "shop-web-1": {
      cpu_percent: 3.2,
      memory_usage: 64 * 1024 ** 2,
      memory_limit: 512 * 1024 ** 2,
      memory_percent: 12.5,
      net_rx: 0,
      net_tx: 0,
      block_read: 0,
      block_write: 0,
      pids: 3,
    },
    "mbp-backend-1": null,
  },
};

function api(overrides: Record<string, () => { status: number; body?: unknown }> = {}) {
  return mockFetch((url, init) => {
    const path = url.replace(/^\/api/, "");
    const key = `${init.method ?? "GET"} ${path}`;
    if (overrides[key]) return overrides[key]();
    if (path === "/containers")
      return { status: 200, body: { containers: CONTAINERS, read_only: false } };
    if (path === "/containers/-/info") return { status: 200, body: INFO };
    if (path === "/containers/-/stats") return { status: 200, body: STATS };
    if (path === "/containers/shop-web-1")
      return {
        status: 200,
        body: {
          ...CONTAINERS[0],
          image_id: "abc",
          hostname: "h",
          env_names: ["DB_PASSWORD", "PATH"],
          mounts: [{ type: "volume", source: "data", destination: "/data", read_only: false }],
          networks: [{ name: "web", ip: "172.18.0.5" }],
          health_failing_streak: null,
          health_last_output: null,
          tty: false,
        },
      };
    if (path.startsWith("/containers/shop-web-1/logs"))
      return {
        status: 200,
        body: {
          lines: [
            { stream: "stdout", time: "2026-10-11T08:00:00Z", text: "GET / 200" },
            { stream: "stderr", time: null, text: "warning: slow" },
          ],
          truncated: false,
        },
      };
    if (init.method === "POST")
      return { status: 200, body: { container: { ...CONTAINERS[0], state: "running" } } };
    return { status: 404, body: { code: "not_found" } };
  });
}

describe("ContainersPage", () => {
  it("explains how to set up the agent when it is missing", async () => {
    mockFetch(() => ({ status: 503, body: { code: "agent_unreachable" } }));
    renderWithProviders(<ContainersPage />);
    expect(await screen.findByText("Container management is not set up")).toBeInTheDocument();
    expect(screen.getByText(/COMPOSE_PROFILES=containers/)).toBeInTheDocument();
  });

  it("shows the containers grouped by project, problems first, with usage", async () => {
    api();
    renderWithProviders(<ContainersPage />);
    expect(await screen.findByText("shop")).toBeInTheDocument();
    expect(screen.getByText("mysql-backup-panel")).toBeInTheDocument();
    const rows = screen.getAllByTestId(/^container-shop-/);
    expect(rows.map((r) => r.dataset.testid)).toEqual([
      "container-shop-worker-1",
      "container-shop-web-1",
    ]);
    expect(within(rows[0]).getByText("Crashed")).toBeInTheDocument();
    expect(within(rows[0]).getByText("exit code 1")).toBeInTheDocument();
    expect(await within(rows[1]).findByText("3.2%")).toBeInTheDocument();
    expect(screen.getByText("2 / 3")).toBeInTheDocument();
    expect(await screen.findByText("12.5%")).toBeInTheDocument();
    // The panel's own container has no controls.
    const panel = screen.getByTestId("container-mbp-backend-1");
    expect(within(panel).queryByRole("button")).toBeNull();
    expect(within(panel).getByLabelText("Locked")).toBeInTheDocument();
  });

  it("asks before a restart and starts without asking", async () => {
    const fetchMock = api();
    renderWithProviders(<ContainersPage />);
    await userEvent.click(await screen.findByRole("button", { name: "Restart shop-web-1" }));
    const dialog = await screen.findByRole("dialog");
    expect(within(dialog).getByText(/Restart “shop-web-1”/)).toBeInTheDocument();
    await userEvent.click(within(dialog).getByRole("button", { name: "Restart" }));
    await waitFor(() =>
      expect(
        fetchMock.mock.calls.some(
          ([url, init]) =>
            String(url).endsWith("/containers/shop-web-1/restart") && init?.method === "POST",
        ),
      ).toBe(true),
    );
    expect(await screen.findByText("“shop-web-1” restarted.")).toBeInTheDocument();

    await userEvent.click(screen.getByRole("button", { name: "Start shop-worker-1" }));
    await waitFor(() =>
      expect(
        fetchMock.mock.calls.some(([url]) =>
          String(url).endsWith("/containers/shop-worker-1/start"),
        ),
      ).toBe(true),
    );
  });

  it("filters problems and searches", async () => {
    api();
    renderWithProviders(<ContainersPage />);
    await screen.findByTestId("container-shop-web-1");
    await userEvent.click(screen.getByText("Problems"));
    expect(screen.queryByTestId("container-shop-web-1")).toBeNull();
    expect(screen.getByTestId("container-shop-worker-1")).toBeInTheDocument();
    await userEvent.click(screen.getByText("All"));
    await userEvent.type(screen.getByLabelText(/Search by name/), "mbp");
    expect(screen.queryByTestId("container-shop-worker-1")).toBeNull();
    expect(screen.getByTestId("container-mbp-backend-1")).toBeInTheDocument();
  });

  it("opens the details with env names and logs", async () => {
    api();
    renderWithProviders(<ContainersPage />);
    await userEvent.click(await screen.findByTestId("container-shop-web-1"));
    expect(await screen.findByText("DB_PASSWORD")).toBeInTheDocument();
    expect(screen.getByText(/never leave the server/)).toBeInTheDocument();
    expect(screen.getByText("web (172.18.0.5)")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("tab", { name: "Logs" }));
    const box = await screen.findByTestId("log-box");
    expect(within(box).getByText("GET / 200")).toBeInTheDocument();
    expect(within(box).getByText("warning: slow")).toBeInTheDocument();
    await userEvent.type(screen.getByLabelText("Filter lines"), "slow");
    expect(within(box).queryByText("GET / 200")).toBeNull();
  });

  it("saves the settings", async () => {
    const settings = {
      read_only: false,
      hidden: [],
      locked: [],
      monitor_all: true,
      monitored: [],
      cpu_percent: 90,
      memory_percent: 90,
      restart_count: 3,
      restart_window_minutes: 10,
      host_memory_percent: 90,
      host_disk_percent: 90,
      bot_logs: false,
    };
    let saved: unknown = null;
    const fetchMock = api({
      "GET /containers/-/settings": () => ({ status: 200, body: settings }),
      "PUT /containers/-/settings": () => ({ status: 200, body: saved ?? settings }),
    });
    renderWithProviders(<ContainersPage />);
    await userEvent.click(await screen.findByRole("tab", { name: "Settings" }));
    await userEvent.click(await screen.findByRole("switch", { name: /Read-only mode/ }));
    await userEvent.click(screen.getByRole("switch", { name: /Show logs in the bots/ }));
    await userEvent.click(screen.getByRole("button", { name: "Save" }));
    await waitFor(() => {
      const put = fetchMock.mock.calls.find(([, init]) => init?.method === "PUT");
      expect(put).toBeTruthy();
      saved = JSON.parse(String(put![1]!.body));
    });
    expect(saved).toMatchObject({ read_only: true, bot_logs: true, cpu_percent: 90 });
  });

  it("switches between servers", async () => {
    const fetchMock = api({
      "GET /servers": () => ({
        status: 200,
        body: [
          { id: 1, name: "main", kind: "local", paired: true },
          { id: 4, name: "edge", kind: "remote", paired: true },
          { id: 5, name: "new", kind: "remote", paired: false },
        ],
      }),
      "GET /containers?server=4": () => ({
        status: 200,
        body: {
          containers: [{ ...CONTAINERS[0], id: "e1", name: "edge-api-1" }],
          read_only: false,
        },
      }),
      "GET /containers/-/info?server=4": () => ({ status: 200, body: INFO }),
      "GET /containers/-/stats?server=4": () => ({ status: 200, body: { stats: {} } }),
    });
    renderWithProviders(<ContainersPage />);
    expect(await screen.findByText("shop-web-1")).toBeInTheDocument();
    const picker = await screen.findByRole("textbox", { name: "Server" });
    await userEvent.click(picker);
    // Only servers whose agent can be used are offered.
    expect(screen.queryByRole("option", { name: "new" })).toBeNull();
    await userEvent.click(await screen.findByRole("option", { name: "edge" }));
    expect(await screen.findByText("edge-api-1")).toBeInTheDocument();
    expect(fetchMock.mock.calls.some(([url]) => String(url) === "/api/containers?server=4")).toBe(
      true,
    );
  });
});
