import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it } from "vitest";

import { ServerSwitcher } from "../src/components/ServerSwitcher";
import { CurrentServerProvider, pickServer, useCurrentServer } from "../src/server/CurrentServer";
import { mockFetch, renderWithProviders } from "./render";
import { EDGE, LOCAL, NEW } from "./servers";

function Probe() {
  const { server } = useCurrentServer();
  return <div data-testid="current">{server?.name}</div>;
}

describe("the current server", () => {
  afterEach(() => localStorage.removeItem("mbp.server"));

  it("falls back to the panel's own server", () => {
    const servers = [LOCAL, EDGE, NEW];
    expect(pickServer(servers, null)?.name).toBe("main");
    expect(pickServer(servers, 4)?.name).toBe("edge");
    expect(pickServer(servers, 5)?.name).toBe("main"); // not connected
    expect(pickServer(servers, 99)?.name).toBe("main"); // deleted
  });

  it("is switched from the server card and remembered", async () => {
    mockFetch(() => ({ status: 200, body: [LOCAL, EDGE, NEW] }));
    renderWithProviders(
      <CurrentServerProvider>
        <ServerSwitcher />
        <Probe />
      </CurrentServerProvider>,
    );
    await waitFor(() => expect(screen.getByTestId("current")).toHaveTextContent("main"));
    await userEvent.click(
      screen.getByRole("button", { name: "Current server: main. Switch server" }),
    );
    // A server that is not connected cannot be picked.
    const unconnected = await screen.findByRole("menuitem", { name: /new/ });
    expect(unconnected).toHaveAttribute("data-disabled");
    expect(screen.getByRole("menuitem", { name: /Manage all servers/ })).toBeInTheDocument();
    await userEvent.click(screen.getByRole("menuitem", { name: /edge/ }));
    expect(screen.getByTestId("current")).toHaveTextContent("edge");
    expect(localStorage.getItem("mbp.server")).toBe("4");
  });

  it("starts on the remembered server", async () => {
    localStorage.setItem("mbp.server", "4");
    mockFetch(() => ({ status: 200, body: [LOCAL, EDGE] }));
    renderWithProviders(
      <CurrentServerProvider>
        <Probe />
      </CurrentServerProvider>,
    );
    await waitFor(() => expect(screen.getByTestId("current")).toHaveTextContent("edge"));
  });
});
