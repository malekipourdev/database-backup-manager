import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";

import { BackupActions } from "../src/components/BackupActions";
import { mockFetch, renderWithProviders } from "./render";

function databases(selected: string[]) {
  return {
    reachable: true,
    error_code: null,
    error_detail: null,
    databases: ["blog", "information_schema", "shop"].map((name) => ({
      name,
      is_system: name === "information_schema",
      selectable: name !== "information_schema",
      selected: selected.includes(name),
      missing: false,
    })),
  };
}

describe("BackupActions", () => {
  it("disables 'back up all' when nothing is marked", async () => {
    mockFetch(() => ({ status: 200, body: databases([]) }));
    renderWithProviders(<BackupActions instanceId={7} activeDatabases={new Set()} />);
    expect(
      await screen.findByText("Mark databases for backup in the list below to enable this."),
    ).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Back up all marked databases" })).toBeDisabled();
  });

  it("starts a single-database backup and reports skipped databases", async () => {
    const fetchMock = mockFetch((_url, init) => {
      if (init.method === "POST") {
        return {
          status: 202,
          body: { created: [], skipped: [{ database: "shop", reason: "already_in_progress" }] },
        };
      }
      return { status: 200, body: databases(["shop"]) };
    });
    renderWithProviders(<BackupActions instanceId={7} activeDatabases={new Set()} />);

    const allButton = await screen.findByRole("button", { name: "Back up all marked databases" });
    await waitFor(() => expect(allButton).toBeEnabled());

    await userEvent.click(screen.getByRole("textbox", { name: "Back up a single database" }));
    await userEvent.click(await screen.findByRole("option", { name: "shop" }));
    expect(screen.queryByRole("option", { name: "information_schema" })).not.toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Back up" }));

    await waitFor(() =>
      expect(fetchMock.mock.calls.some(([, init]) => init?.method === "POST")).toBe(true),
    );
    const post = fetchMock.mock.calls.find(([, init]) => init?.method === "POST")!;
    expect(String(post[0])).toBe("/api/instances/7/backups");
    expect(JSON.parse(String(post[1]!.body))).toEqual({ scope: "single", database: "shop" });
    expect(
      await screen.findByText("“shop” skipped: a backup of it is already in progress."),
    ).toBeInTheDocument();
  });

  it("disables single backup for a database that is already running", async () => {
    mockFetch(() => ({ status: 200, body: databases(["shop"]) }));
    renderWithProviders(<BackupActions instanceId={7} activeDatabases={new Set(["shop"])} />);
    await userEvent.click(
      await screen.findByRole("textbox", { name: "Back up a single database" }),
    );
    await userEvent.click(await screen.findByRole("option", { name: "shop" }));
    expect(screen.getByRole("button", { name: "Back up" })).toBeDisabled();
  });
});
