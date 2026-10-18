import { MantineProvider } from "@mantine/core";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it } from "vitest";
import { MemoryRouter, Route, Routes } from "react-router-dom";

import { Layout } from "../src/components/Layout";
import { locate } from "../src/navigation";
import { mockFetch } from "./render";
import { EDGE, LOCAL } from "./servers";

function renderLayout(route: string) {
  mockFetch((url) => {
    if (url.endsWith("/auth/me")) {
      return { status: 200, body: { username: "admin", two_factor_enabled: true } };
    }
    if (url.endsWith("/servers")) return { status: 200, body: [LOCAL, EDGE] };
    return { status: 404, body: { code: "not_found" } };
  });
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <MantineProvider>
      <QueryClientProvider client={queryClient}>
        <MemoryRouter initialEntries={[route]}>
          <Routes>
            <Route element={<Layout />}>
              <Route path="*" element={<h1>page</h1>} />
            </Route>
          </Routes>
        </MemoryRouter>
      </QueryClientProvider>
    </MantineProvider>,
  );
}

describe("where a page is in the menu", () => {
  it("finds the group, item and sub-page of a path", () => {
    const edit = locate("/instances/3/edit");
    expect(edit.group?.id).toBe("data");
    expect(edit.item?.to).toBe("/instances");
    expect(edit.sub).toBe("nav.sub.edit");
    expect(locate("/projects/new").sub).toBe("nav.sub.new");
    expect(locate("/projects/7").sub).toBe("nav.sub.details");
    expect(locate("/help/install").sub).toBe("nav.sub.article");
    expect(locate("/settings/backups").item?.label).toBe("nav.settings");
    expect(locate("/backups").sub).toBeNull();
    // "/servers" is not mistaken for a sub-page of anything else.
    expect(locate("/servers").item?.to).toBe("/servers");
    expect(locate("/nowhere").item).toBeNull();
  });
});

describe("the panel's frame", () => {
  afterEach(() => localStorage.removeItem("mbp.nav.open"));

  it("groups the menu, marks the current page and names it in the title", async () => {
    renderLayout("/backups");
    const menu = await screen.findByRole("navigation", { name: "Main menu" });
    const group = within(menu).getByRole("group", { name: "Databases & backups" });
    const current = within(group).getByRole("link", { name: "Backup history" });
    expect(current).toHaveAttribute("aria-current", "page");
    // Groups run from the widest scope down.
    expect(
      within(menu)
        .getAllByRole("group")
        .map((g) => g.getAttribute("aria-labelledby")),
    ).toEqual(["side-infra", "side-apps", "side-data", "side-alerts", "side-system"]);
    // Only the current page's group is open; the others fold.
    const apps = within(menu).getByRole("button", { name: "Applications" });
    expect(apps).toHaveAttribute("aria-expanded", "false");
    expect(within(menu).queryByRole("link", { name: "Projects" })).toBeNull();
    await userEvent.click(apps);
    expect(apps).toHaveAttribute("aria-expanded", "true");
    expect(within(menu).getByRole("link", { name: "Projects" })).toHaveAttribute(
      "href",
      "/projects",
    );
    const data = within(menu).getByRole("button", { name: "Databases & backups" });
    await userEvent.click(data);
    expect(within(menu).queryByRole("link", { name: "Backup history" })).toBeNull();
    // The choice is remembered.
    expect(JSON.parse(localStorage.getItem("mbp.nav.open")!)).toEqual(["apps"]);

    const crumbs = screen.getByRole("navigation", { name: "You are here" });
    expect(crumbs).toHaveTextContent("Databases & backups");
    expect(crumbs).toHaveTextContent("Backup history");
    await waitFor(() => expect(document.title).toBe("Backup history · DevOps Manager"));

    expect(screen.getByRole("link", { name: "Skip to content" })).toHaveAttribute("href", "#main");
    expect(screen.getByRole("main")).toHaveAttribute("id", "main");
  });

  it("links back to the list from a sub-page", async () => {
    renderLayout("/projects/3/edit");
    const crumbs = await screen.findByRole("navigation", { name: "You are here" });
    expect(within(crumbs).getByRole("link", { name: "Projects" })).toHaveAttribute(
      "href",
      "/projects",
    );
    expect(within(crumbs).getByText("Edit")).toHaveAttribute("aria-current", "page");
    await waitFor(() => expect(document.title).toBe("Edit · Projects · DevOps Manager"));
  });

  it("opens the whole menu from the phone's Menu tab", async () => {
    renderLayout("/servers");
    const tabs = await screen.findByRole("navigation", { name: "Quick navigation" });
    expect(within(tabs).getByRole("link", { name: "Overview" })).toBeInTheDocument();
    const open = within(tabs).getByRole("button", { name: "Menu" });
    expect(open).toHaveAttribute("aria-expanded", "false");
    await userEvent.click(open);
    const drawer = await screen.findByRole("dialog", { name: "Menu" });
    await userEvent.click(within(drawer).getByRole("button", { name: "Alerts & chat access" }));
    expect(within(drawer).getByRole("link", { name: "Alerts" })).toBeInTheDocument();
    expect(within(drawer).getByRole("link", { name: "Servers" })).toHaveAttribute(
      "aria-current",
      "page",
    );
    expect(within(drawer).getByRole("button", { name: "Sign out" })).toBeInTheDocument();
  });
});
