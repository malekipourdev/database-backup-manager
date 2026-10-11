import { screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { type BackupRun, POLL_MS, pollInterval, useInstanceRuns } from "../src/api/backups";
import { RunTable } from "../src/components/RunTable";
import { mockFetch, renderWithProviders } from "./render";

function makeRun(status: BackupRun["status"], extra: Partial<BackupRun> = {}): BackupRun {
  return {
    id: 1,
    instance_id: 7,
    instance_name: "prod",
    database_name: "shop",
    trigger: "single",
    status,
    requested_at: "2026-10-11T10:00:00Z",
    started_at: "2026-10-11T10:00:01Z",
    finished_at: status === "success" ? "2026-10-11T10:00:05Z" : null,
    duration_ms: status === "success" ? 4000 : null,
    elapsed_ms: status === "running" ? 3000 : null,
    bytes_processed: 5 * 1024 * 1024,
    file_size: status === "success" ? 1024 : null,
    compression: "gzip",
    checksum_sha256: status === "success" ? "a".repeat(64) : null,
    file_name: status === "success" ? "shop.sql.gz" : null,
    file_available: status === "success",
    server_type: "mysql",
    server_version: "8.4.3",
    error_code: null,
    error_message: null,
    ...extra,
  };
}

function Runs() {
  const runs = useInstanceRuns(7);
  return runs.data ? <RunTable runs={runs.data.items} /> : null;
}

describe("run polling", () => {
  it("polls only while a run is queued or running", () => {
    expect(pollInterval([makeRun("running")])).toBe(POLL_MS);
    expect(pollInterval([makeRun("queued"), makeRun("success")])).toBe(POLL_MS);
    expect(pollInterval([makeRun("success"), makeRun("failed")])).toBe(false);
    expect(pollInterval(undefined)).toBe(false);
  });

  it("refreshes a running run until it succeeds, then stops", async () => {
    let calls = 0;
    mockFetch(() => {
      calls += 1;
      const run = calls === 1 ? makeRun("running") : makeRun("success");
      return { status: 200, body: { items: [run], total: 1, page: 1, page_size: 10 } };
    });
    renderWithProviders(<Runs />);

    expect(await screen.findByText("Running")).toBeInTheDocument();
    expect(screen.getByText(/5 MB dumped/)).toBeInTheDocument();
    expect(await screen.findByText("Success", {}, { timeout: POLL_MS + 2000 })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Download" })).toHaveAttribute(
      "href",
      "/api/backups/runs/1/download",
    );

    const callsAfterSuccess = calls;
    await new Promise((resolve) => setTimeout(resolve, POLL_MS + 500));
    expect(calls).toBe(callsAfterSuccess);
  }, 10_000);

  it("shows the translated error for a failed run", async () => {
    mockFetch(() => ({
      status: 200,
      body: {
        items: [makeRun("failed", { error_code: "disk_full", error_message: "ENOSPC" })],
        total: 1,
        page: 1,
        page_size: 10,
      },
    }));
    renderWithProviders(<Runs />);
    expect(await screen.findByText("Not enough disk space for the backup.")).toBeInTheDocument();
  });
});
