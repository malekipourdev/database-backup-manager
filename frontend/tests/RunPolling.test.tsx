import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
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
    schedule_id: null,
    file_deleted_at: null,
    file_deleted_reason: null,
    remote_status: null,
    remote_uploaded_at: null,
    remote_deleted_at: null,
    remote_error: null,
    remote_available: false,
    download_available: status === "success",
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
    // An upload to remote storage also keeps the table refreshing.
    expect(pollInterval([makeRun("success", { remote_status: "uploading" })])).toBe(POLL_MS);
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

describe("remote copies and retention", () => {
  const page = (run: BackupRun) => ({
    status: 200,
    body: { items: [run], total: 1, page: 1, page_size: 10 },
  });

  it("offers a retry for a failed upload", async () => {
    const run = makeRun("success", { remote_status: "failed", remote_error: "bucket_not_found" });
    const fetchMock = mockFetch((url) =>
      url.endsWith("/upload") ? { status: 202, body: run } : page(run),
    );
    renderWithProviders(<Runs />);
    expect(await screen.findByText("Upload failed")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Retry upload" }));
    await waitFor(() =>
      expect(
        fetchMock.mock.calls.some(
          ([u, init]) => String(u) === "/api/backups/runs/1/upload" && init?.method === "POST",
        ),
      ).toBe(true),
    );
  });

  it("still downloads from the remote copy after retention removed the local file", async () => {
    const run = makeRun("success", {
      file_available: false,
      file_deleted_at: "2026-10-12T10:00:00Z",
      file_deleted_reason: "retention",
      remote_status: "success",
      remote_available: true,
      download_available: true,
    });
    mockFetch(() => page(run));
    renderWithProviders(<Runs />);
    expect(await screen.findByText("Stored remotely")).toBeInTheDocument();
    expect(screen.getByText(/Local file removed by retention/)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Download" })).toBeInTheDocument();
  });

  it("shows when the file is gone everywhere", async () => {
    const run = makeRun("success", {
      file_available: false,
      file_deleted_at: "2026-10-12T10:00:00Z",
      file_deleted_reason: "retention",
      download_available: false,
    });
    mockFetch(() => page(run));
    renderWithProviders(<Runs />);
    expect(await screen.findByRole("button", { name: "Removed locally" })).toBeDisabled();
  });

  it("marks scheduled runs", async () => {
    mockFetch(() => page(makeRun("success", { trigger: "schedule", schedule_id: 4 })));
    renderWithProviders(<Runs />);
    expect(await screen.findByText("Scheduled")).toBeInTheDocument();
  });
});
