import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";

import type { Server } from "../src/api/servers";
import { ServersPage } from "../src/pages/ServersPage";
import { mockFetch, renderWithProviders } from "./render";

const base: Server = {
  id: 1,
  name: "main",
  kind: "local",
  host: null,
  port: null,
  notes: "",
  paired: true,
  cert_fingerprint: null,
  paired_at: null,
  last_seen_at: "2026-10-12T08:00:00Z",
  last_error: null,
  agent_hostname: "panel-host",
  docker_version: "27.3.1",
  projects: 2,
  instances: 1,
  created_at: "2026-10-12T08:00:00Z",
};
const EDGE: Server = {
  ...base,
  id: 4,
  name: "edge",
  kind: "remote",
  host: "203.0.113.7",
  port: 8443,
  paired: true,
  cert_fingerprint: "ab".repeat(32),
  last_error: "agent_unreachable",
  projects: 0,
  instances: 0,
};
const TOKEN = "tok_Secret-Agent-Token-1234567890";

describe("ServersPage", () => {
  it("lists the panel's server and others, with their state", async () => {
    mockFetch(() => ({ status: 200, body: [base, EDGE] }));
    renderWithProviders(<ServersPage />);
    const local = await screen.findByTestId("server-main");
    expect(within(local).getByText("this server")).toBeInTheDocument();
    expect(within(local).getByText("Connected")).toBeInTheDocument();
    const edge = screen.getByTestId("server-edge");
    expect(within(edge).getByText("203.0.113.7:8443")).toBeInTheDocument();
    expect(within(edge).getByText("Unreachable")).toBeInTheDocument();
    expect(within(edge).getByText("ab:ab:ab:ab:ab:ab:ab:ab")).toBeInTheDocument();
    // The local server cannot be deleted or given a new token.
    expect(within(local).queryByLabelText("Delete")).toBeNull();
    expect(within(edge).getByLabelText("Delete")).toBeInTheDocument();
  });

  it("adds a server, shows its install commands once, then connects it", async () => {
    let servers: Server[] = [base];
    const fetchMock = mockFetch((url, init) => {
      if (url.endsWith("/api/servers") && init.method === "POST") {
        const created = { ...EDGE, paired: false, cert_fingerprint: null, last_error: null };
        servers = [base, created];
        return {
          status: 201,
          body: {
            server: created,
            token: TOKEN,
            install_command: `git clone x mbp-agent\nMBP_AGENT_TOKEN=${TOKEN}`,
          },
        };
      }
      if (url.endsWith("/connect")) {
        servers = [base, { ...EDGE, last_error: null }];
        return { status: 200, body: servers[1] };
      }
      return { status: 200, body: servers };
    });
    renderWithProviders(<ServersPage />);
    await userEvent.click(await screen.findByRole("button", { name: "Add server" }));
    const dialog = await screen.findByRole("dialog");
    await userEvent.type(within(dialog).getByLabelText(/^Name/), "edge");
    await userEvent.type(within(dialog).getByLabelText(/^Server address/), "203.0.113.7");
    await userEvent.click(within(dialog).getByRole("button", { name: "Save" }));

    const setup = await screen.findByText(/Set up the agent on/);
    const modal = setup.closest("[role=dialog]") as HTMLElement;
    expect(within(modal).getByText(/MBP_AGENT_TOKEN=tok_Secret/)).toBeInTheDocument();
    expect(within(modal).getByText(/shown only this once/)).toBeInTheDocument();
    const post = fetchMock.mock.calls.find(([, init]) => init?.method === "POST")!;
    expect(JSON.parse(String(post[1]!.body))).toEqual({
      name: "edge",
      host: "203.0.113.7",
      port: 8443,
      notes: "",
    });

    await userEvent.click(within(modal).getByRole("button", { name: "Connect" }));
    await waitFor(() =>
      expect(fetchMock.mock.calls.some(([url]) => String(url).endsWith("/servers/4/connect"))).toBe(
        true,
      ),
    );
    await waitFor(() => expect(screen.queryByText(/Set up the agent on/)).toBeNull());
    // The token is not kept on the page once the dialog is closed.
    expect(screen.queryByText(new RegExp(TOKEN))).toBeNull();
  });

  it("explains a refused delete", async () => {
    mockFetch((_url, init) =>
      init.method === "DELETE"
        ? { status: 409, body: { code: "server_in_use", detail: "1:0" } }
        : { status: 200, body: [base, EDGE] },
    );
    renderWithProviders(<ServersPage />);
    const edge = await screen.findByTestId("server-edge");
    await userEvent.click(within(edge).getByLabelText("Delete"));
    const dialog = await screen.findByRole("dialog");
    await userEvent.click(within(dialog).getByRole("button", { name: "Delete" }));
    expect(await within(dialog).findByText(/still has projects or databases/)).toBeInTheDocument();
  });
});
