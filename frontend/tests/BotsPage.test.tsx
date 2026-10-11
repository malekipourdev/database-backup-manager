import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";

import { BotsPage } from "../src/pages/BotsPage";
import { mockFetch, renderWithProviders } from "./render";

const bot = (platform: "bale" | "telegram", extra = {}) => ({
  platform,
  enabled: false,
  has_token: false,
  api_base_url: "",
  proxy_url: "",
  allow_file_download: false,
  max_file_mb: 20,
  bot_username: null,
  running: false,
  last_ok_at: null,
  last_error: null,
  ...extra,
});

const ADMIN = {
  id: 1,
  platform: "bale",
  user_id: 111,
  display_name: "Ops",
  enabled: true,
  notify_level: "warning",
  language: "fa",
  last_seen_at: null,
  created_at: "2026-10-11T10:00:00Z",
};

const bodyOf = (init?: RequestInit) => JSON.parse(String(init?.body));

function api(overrides: (url: string, init: RequestInit) => unknown = () => undefined) {
  return mockFetch((url, init) => {
    const custom = overrides(url, init);
    if (custom) return custom as { status: number; body?: unknown };
    if (url === "/api/bots")
      return {
        status: 200,
        body: [
          bot("bale", { enabled: true, has_token: true, running: true, bot_username: "mbp_bot" }),
          bot("telegram"),
        ],
      };
    if (url === "/api/bot-admins" && (init.method ?? "GET") === "GET")
      return { status: 200, body: [ADMIN] };
    return { status: 200, body: {} };
  });
}

describe("BotsPage", () => {
  it("shows connection state and never pre-fills the token", async () => {
    api();
    renderWithProviders(<BotsPage />);
    expect(await screen.findByText("Connected as @mbp_bot")).toBeInTheDocument();
    expect(screen.getByText("A token is stored. Leave empty to keep it.")).toBeInTheDocument();
    for (const input of screen.getAllByLabelText("Bot token")) expect(input).toHaveValue("");
    expect(await screen.findByText("Ops")).toBeInTheDocument();
  });

  it("saves with an empty token to keep the stored one", async () => {
    const fetchMock = api((url, init) =>
      url === "/api/bots/bale" && init.method === "PUT"
        ? { status: 200, body: bot("bale") }
        : undefined,
    );
    renderWithProviders(<BotsPage />);
    await screen.findByText("Connected as @mbp_bot");
    await userEvent.click(screen.getAllByRole("button", { name: "Save" })[0]);
    await waitFor(() =>
      expect(
        fetchMock.mock.calls.some(([u, i]) => u === "/api/bots/bale" && i?.method === "PUT"),
      ).toBe(true),
    );
    const put = fetchMock.mock.calls.find(
      ([u, i]) => u === "/api/bots/bale" && i?.method === "PUT",
    )!;
    expect(bodyOf(put[1])).toMatchObject({ enabled: true, token: "", allow_file_download: false });
  });

  it("adds an admin by numeric ID", async () => {
    const fetchMock = api((url, init) =>
      url === "/api/bot-admins" && init.method === "POST"
        ? { status: 201, body: ADMIN }
        : undefined,
    );
    renderWithProviders(<BotsPage />);
    await screen.findByText("Ops");
    await userEvent.type(screen.getByLabelText(/Numeric user ID/), "4242");
    const nameInputs = screen.getAllByLabelText("Name");
    await userEvent.type(nameInputs[nameInputs.length - 1], "Sara");
    await userEvent.click(screen.getByRole("button", { name: "Add admin" }));
    await waitFor(() =>
      expect(
        fetchMock.mock.calls.some(([u, i]) => u === "/api/bot-admins" && i?.method === "POST"),
      ).toBe(true),
    );
    const post = fetchMock.mock.calls.find(
      ([u, i]) => u === "/api/bot-admins" && i?.method === "POST",
    )!;
    expect(bodyOf(post[1])).toEqual({ platform: "bale", user_id: 4242, display_name: "Sara" });
  });

  it("creates a one-time link code", async () => {
    api((url) =>
      url === "/api/bots/bale/link-codes"
        ? {
            status: 201,
            body: {
              code: "ABCD2345",
              expires_at: "2026-10-11T10:15:00Z",
              bot_username: "mbp_bot",
              deep_link: null,
            },
          }
        : undefined,
    );
    renderWithProviders(<BotsPage />);
    await userEvent.click(await screen.findByRole("button", { name: "Create link code" }));
    const dialog = await screen.findByRole("dialog");
    await userEvent.type(within(dialog).getByLabelText("Name"), "Reza");
    await userEvent.click(within(dialog).getByRole("button", { name: "Create code" }));
    expect(await within(dialog).findByTestId("link-code")).toHaveTextContent("ABCD2345");
    expect(within(dialog).getByText("Open @mbp_bot in the messenger.")).toBeInTheDocument();
  });
});
