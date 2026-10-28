import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it } from "vitest";

import { levelOf, withLevel } from "../src/api/apiAccess";
import i18n from "../src/i18n";
import { ApiAccessPage } from "../src/pages/ApiAccessPage";
import { mockFetch, renderWithProviders } from "./render";

const CATALOG = {
  base_path: "/api/v1",
  areas: [
    { area: "projects", read: 6, write: 7 },
    { area: "backups", read: 3, write: 3 },
  ],
  scopes: [
    "*",
    "projects:read",
    "projects:write",
    "backups:read",
    "backups:write",
    "backups:download",
  ],
  events: ["*", "backup_failed", "deploy_failed", "ping"],
};
const KEY = {
  id: 1,
  name: "Shop site",
  prefix: "mbp_abcd1234",
  scopes: ["projects:read"],
  server_ids: [7],
  allowed_ips: ["203.0.113.0/24"],
  rate_limit: 600,
  enabled: true,
  expires_at: null,
  expired: false,
  created_at: "2026-10-01T10:00:00Z",
  rotated_at: null,
  last_used_at: "2026-10-28T10:00:00Z",
  last_used_ip: "203.0.113.9",
  request_count: 12,
  requests_24h: 5,
  errors_24h: 1,
};
const bodyOf = (init?: RequestInit) => JSON.parse(String(init?.body));

function api(keys = [KEY]) {
  return mockFetch((url, init) => {
    if (url === "/api/api-access/settings")
      return { status: 200, body: { enabled: true, cors_origins: [], log_retention_days: 30 } };
    if (url === "/api/api-access/catalog") return { status: 200, body: CATALOG };
    if (url === "/api/api-access/keys" && init.method === "POST")
      return {
        status: 201,
        body: { key: { ...KEY, id: 2, name: "CI" }, secret: "mbp_SECRET-123" },
      };
    if (url === "/api/api-access/keys") return { status: 200, body: keys };
    if (url === "/api/webhooks") return { status: 200, body: [] };
    if (url === "/api/servers")
      return {
        status: 200,
        body: [
          { id: 1, name: "main", kind: "local", paired: true },
          { id: 7, name: "edge", kind: "remote", paired: true },
        ],
      };
    if (url.startsWith("/api/api-access/requests"))
      return {
        status: 200,
        body: {
          items: [
            {
              id: 9,
              key_id: 1,
              key_name: "Shop site",
              created_at: "2026-10-28T10:00:00Z",
              method: "GET",
              path: "/instances",
              status: 403,
              ip: "203.0.113.9",
              duration_ms: 4,
              error: "insufficient_scope",
              on_behalf_of: "Sara",
            },
          ],
          next_before: null,
        },
      };
    return { status: 404, body: { code: "not_found" } };
  });
}

describe("scope helpers", () => {
  it("reads and sets an area's level", () => {
    expect(levelOf(["*"], "projects")).toBe("write");
    expect(levelOf(["projects:read"], "projects")).toBe("read");
    expect(levelOf([], "projects")).toBe("none");
    expect(withLevel(["projects:read", "backups:download"], "projects", "write")).toEqual([
      "backups:download",
      "projects:write",
    ]);
    expect(withLevel(["projects:write"], "projects", "none")).toEqual([]);
  });
});

describe("ApiAccessPage", () => {
  beforeEach(() => i18n.changeLanguage("en"));

  it("lists keys with their access and use", async () => {
    api();
    renderWithProviders(<ApiAccessPage />);
    const card = await screen.findByTestId("api-key-1");
    expect(card).toHaveTextContent("Shop site");
    expect(card).toHaveTextContent("mbp_abcd1234…");
    expect(card).toHaveTextContent("Projects");
    expect(card).toHaveTextContent("203.0.113.0/24");
    expect(card).toHaveTextContent("1 errors");
    expect(await within(card).findByText("edge")).toBeInTheDocument();
    expect(screen.getByDisplayValue(/\/api\/v1$/)).toBeInTheDocument();
  });

  it("creates a key with custom scopes and shows the secret once", async () => {
    const fetchMock = api([]);
    renderWithProviders(<ApiAccessPage />);
    expect(await screen.findByTestId("no-keys")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "New key" }));
    const dialog = await screen.findByRole("dialog");
    await userEvent.type(within(dialog).getByLabelText(/^Name/), "CI");
    await userEvent.click(within(dialog).getByText("Custom"));
    const row = within(dialog).getByTestId("scope-projects");
    await userEvent.click(within(row).getByText("Read & write"));
    await userEvent.click(within(dialog).getByLabelText("Download backup files"));
    await userEvent.type(within(dialog).getByLabelText(/^Your password/), "pw");
    await userEvent.click(within(dialog).getByRole("button", { name: "Create key" }));

    await waitFor(() =>
      expect(
        fetchMock.mock.calls.some(
          ([url, init]) => url === "/api/api-access/keys" && init?.method === "POST",
        ),
      ).toBe(true),
    );
    const [, init] = fetchMock.mock.calls.find(
      ([url, i]) => url === "/api/api-access/keys" && i?.method === "POST",
    )!;
    expect(bodyOf(init)).toMatchObject({
      name: "CI",
      scopes: ["backups:read", "projects:write", "backups:download"],
      password: "pw",
      expires_at: null,
      server_ids: null,
    });
    expect(await screen.findByDisplayValue("mbp_SECRET-123")).toBeInTheDocument();
  });

  it("limits a new key to some servers", async () => {
    const fetchMock = api([]);
    renderWithProviders(<ApiAccessPage />);
    expect(await screen.findByTestId("no-keys")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "New key" }));
    const dialog = await screen.findByRole("dialog");
    await userEvent.type(within(dialog).getByLabelText(/^Name/), "tskm");
    await userEvent.type(within(dialog).getByLabelText(/^Your password/), "pw");
    const create = within(dialog).getByRole("button", { name: "Create key" });
    await userEvent.click(within(dialog).getByText("Only some servers"));
    // A key for no server at all is not offered.
    expect(create).toBeDisabled();
    await userEvent.click(within(dialog).getByRole("textbox", { name: "Servers" }));
    await userEvent.click(await screen.findByRole("option", { name: "edge" }));
    expect(create).toBeEnabled();
    await userEvent.click(create);
    await waitFor(() =>
      expect(
        fetchMock.mock.calls.some(
          ([url, init]) => url === "/api/api-access/keys" && init?.method === "POST",
        ),
      ).toBe(true),
    );
    const [, init] = fetchMock.mock.calls.find(
      ([url, i]) => url === "/api/api-access/keys" && i?.method === "POST",
    )!;
    expect(bodyOf(init)).toMatchObject({ name: "tskm", server_ids: [7] });
  });

  it("shows the request log", async () => {
    api();
    renderWithProviders(<ApiAccessPage />, { route: "/?tab=log" });
    const log = await screen.findByTestId("api-log");
    await waitFor(() => expect(log).toHaveTextContent("/instances"));
    expect(log).toHaveTextContent("403");
    expect(log).toHaveTextContent("insufficient_scope");
    expect(log).toHaveTextContent("for Sara");
  });
});
