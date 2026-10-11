import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";

import { RemoteStorageForm } from "../src/components/RemoteStorageForm";
import { RetentionSettings } from "../src/components/RetentionSettings";
import { mockFetch, renderWithProviders } from "./render";

const REMOTE = {
  enabled: true,
  provider: "s3",
  endpoint_url: "https://s3.example.com",
  region: "us-east-1",
  bucket: "backups",
  prefix: "panel",
  access_key_id: "AKIA1",
  has_secret: true,
  force_path_style: true,
};

const bodyOf = (init?: RequestInit) => JSON.parse(String(init?.body));

describe("RemoteStorageForm", () => {
  it("never shows the stored secret and keeps it when saving with an empty field", async () => {
    const fetchMock = mockFetch((_url, init) =>
      init.method === "PUT" ? { status: 200, body: REMOTE } : { status: 200, body: REMOTE },
    );
    renderWithProviders(<RemoteStorageForm />);
    expect(await screen.findByDisplayValue("backups")).toBeInTheDocument();
    expect(screen.getByText("A secret is stored. Leave empty to keep it.")).toBeInTheDocument();
    expect(screen.getByLabelText("Secret access key")).toHaveValue("");

    await userEvent.click(screen.getByRole("button", { name: "Save" }));
    await waitFor(() =>
      expect(fetchMock.mock.calls.some(([, i]) => i?.method === "PUT")).toBe(true),
    );
    const put = fetchMock.mock.calls.find(([, i]) => i?.method === "PUT")!;
    expect(bodyOf(put[1])).toMatchObject({ bucket: "backups", secret_access_key: "" });
  });

  it("shows a failed connection test with its reason", async () => {
    mockFetch((url) =>
      url.endsWith("/test")
        ? {
            status: 200,
            body: { ok: false, error_code: "bucket_not_found", error_detail: "NoSuchBucket" },
          }
        : { status: 200, body: REMOTE },
    );
    renderWithProviders(<RemoteStorageForm />);
    await userEvent.click(await screen.findByRole("button", { name: "Test connection" }));
    const result = await screen.findByTestId("remote-test-result");
    expect(result).toHaveTextContent("The bucket does not exist.");
    expect(result).toHaveTextContent("NoSuchBucket");
  });
});

describe("RetentionSettings", () => {
  const EMPTY = {
    local_keep_last: null,
    local_max_age_days: null,
    remote_keep_last: null,
    remote_max_age_days: null,
  };

  it("sends null for empty fields and numbers for filled ones", async () => {
    const fetchMock = mockFetch((_url, init) => ({
      status: 200,
      body: init.method === "PUT" ? bodyOf(init) : EMPTY,
    }));
    renderWithProviders(<RetentionSettings />);
    const [localKeep] = await screen.findAllByLabelText(/Keep the last/);
    await userEvent.type(localKeep, "7");
    await userEvent.click(screen.getByRole("button", { name: "Save" }));
    await waitFor(() =>
      expect(fetchMock.mock.calls.some(([, i]) => i?.method === "PUT")).toBe(true),
    );
    const put = fetchMock.mock.calls.find(([, i]) => i?.method === "PUT")!;
    expect(bodyOf(put[1])).toEqual({ ...EMPTY, local_keep_last: 7 });
  });

  it("previews what would be deleted, then applies it", async () => {
    const report = (dryRun: boolean) => ({
      dry_run: dryRun,
      deleted: [
        {
          run_id: 5,
          target: "local",
          instance_name: "prod",
          database_name: "shop",
          file_name: "shop_old.sql.gz",
          finished_at: "2026-09-01T02:00:00Z",
          error_code: null,
          error_message: null,
        },
      ],
      errors: [],
    });
    const fetchMock = mockFetch((url, init) =>
      url.endsWith("/retention/apply")
        ? { status: 200, body: report(bodyOf(init).dry_run) }
        : { status: 200, body: { ...EMPTY, local_keep_last: 1 } },
    );
    renderWithProviders(<RetentionSettings />);
    await userEvent.click(await screen.findByRole("button", { name: "Preview and apply now" }));
    expect(await screen.findByTestId("retention-report")).toHaveTextContent("shop_old.sql.gz");
    await userEvent.click(screen.getByRole("button", { name: "Delete these files" }));
    await waitFor(() => {
      const applies = fetchMock.mock.calls.filter(([u]) => String(u).endsWith("/retention/apply"));
      expect(applies.map(([, i]) => bodyOf(i).dry_run)).toEqual([true, false]);
    });
  });
});
