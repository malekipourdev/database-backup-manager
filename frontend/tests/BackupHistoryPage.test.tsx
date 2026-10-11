import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";

import { BackupHistoryPage, queryFromParams } from "../src/pages/BackupHistoryPage";
import { mockFetch, renderWithProviders } from "./render";

const base = {
  instance_id: 3,
  instance_name: "prod",
  trigger: "all",
  started_at: "2026-10-11T10:00:01Z",
  finished_at: "2026-10-11T10:00:05Z",
  duration_ms: 4000,
  elapsed_ms: null,
  bytes_processed: 2048,
  file_size: 1024,
  compression: "gzip",
  checksum_sha256: "b".repeat(64),
  server_type: "mysql",
  server_version: "8.4.3",
  error_code: null,
  error_message: null,
  status: "success",
  schedule_id: null,
  file_deleted_at: null,
  file_deleted_reason: null,
  remote_status: null,
  remote_uploaded_at: null,
  remote_deleted_at: null,
  remote_error: null,
  remote_available: false,
};
const items = [
  {
    ...base,
    id: 11,
    database_name: "shop",
    requested_at: "2026-10-11T10:00:00Z",
    file_name: "shop.sql.gz",
    file_available: true,
    download_available: true,
  },
  {
    ...base,
    id: 12,
    database_name: "blog",
    requested_at: "2026-10-10T10:00:00Z",
    file_name: "blog.sql.gz",
    file_available: false,
    download_available: false,
  },
];

describe("BackupHistoryPage", () => {
  it("maps URL filters to the API query", () => {
    const query = queryFromParams(
      new URLSearchParams("instance_id=3&status=failed&status=running&sort=file_size&order=asc"),
    );
    expect(query).toMatchObject({
      instanceId: 3,
      statuses: ["failed", "running"],
      sort: "file_size",
      order: "asc",
      page: 1,
      pageSize: 50,
    });
    const days = queryFromParams(new URLSearchParams("from=2026-10-01&to=2026-10-01"));
    expect(new Date(days.to!).getTime() - new Date(days.from!).getTime()).toBe(86_400_000);
  });

  it("lists runs with download links and handles a missing file", async () => {
    const fetchMock = mockFetch((url) =>
      url.startsWith("/api/instances")
        ? { status: 200, body: [] }
        : { status: 200, body: { items, total: 2, page: 1, page_size: 50 } },
    );
    renderWithProviders(<BackupHistoryPage />, {
      path: "/backups",
      route: "/backups?instance_id=3&status=success",
    });

    expect(await screen.findByText("shop")).toBeInTheDocument();
    const listCall = fetchMock.mock.calls.find(([url]) => String(url).startsWith("/api/backups"));
    expect(String(listCall![0])).toContain("instance_id=3");
    expect(String(listCall![0])).toContain("status=success");

    expect(screen.getByRole("link", { name: "Download" })).toHaveAttribute(
      "href",
      "/api/backups/runs/11/download",
    );
    expect(screen.getByRole("button", { name: "File missing" })).toBeDisabled();
  });

  it("asks for confirmation before deleting", async () => {
    const fetchMock = mockFetch((url, init) => {
      if (init.method === "DELETE") return { status: 204 };
      if (url.startsWith("/api/instances")) return { status: 200, body: [] };
      if (url.includes("page_size=1")) {
        return { status: 200, body: { items: [items[0]], total: 1, page: 1, page_size: 1 } };
      }
      return { status: 200, body: { items, total: 2, page: 1, page_size: 50 } };
    });
    renderWithProviders(<BackupHistoryPage />, { path: "/backups", route: "/backups" });

    await screen.findByText("shop");
    await userEvent.click(screen.getAllByRole("button", { name: "Delete" })[0]);
    const dialog = await screen.findByRole("dialog");
    expect(within(dialog).getByText(/latest successful backup of “shop”/)).toBeInTheDocument();
    expect(fetchMock.mock.calls.some(([, init]) => init?.method === "DELETE")).toBe(false);

    await userEvent.click(within(dialog).getByRole("button", { name: "Delete" }));
    await waitFor(() =>
      expect(
        fetchMock.mock.calls.some(
          ([url, init]) => init?.method === "DELETE" && String(url) === "/api/backups/runs/11",
        ),
      ).toBe(true),
    );
  });
});
