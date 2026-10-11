import { MantineProvider } from "@mantine/core";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { ApiError } from "../src/api/client";
import { BackupSettingsForm } from "../src/components/BackupSettingsForm";
import { mockFetch } from "./render";

const settings = {
  storage_dir: "",
  name_pattern: "{instance}/{database}_{date}_{time}",
  compression: "gzip" as const,
};

function renderForm(props: Partial<Parameters<typeof BackupSettingsForm>[0]> = {}) {
  const onSave = vi.fn();
  render(
    <MantineProvider>
      <BackupSettingsForm
        mode="global"
        initial={settings}
        saving={false}
        error={null}
        onSave={onSave}
        {...props}
      />
    </MantineProvider>,
  );
  return onSave;
}

describe("BackupSettingsForm", () => {
  it("shows a live preview from the server", async () => {
    const fetchMock = mockFetch(() => ({
      status: 200,
      body: { path: "prod/shop_2026-10-11_130820.sql.gz" },
    }));
    renderForm();
    expect(await screen.findByTestId("pattern-preview")).toHaveTextContent(
      "prod/shop_2026-10-11_130820.sql.gz",
    );
    expect(String(fetchMock.mock.calls[0][0])).toBe("/api/backup-settings/preview");
  });

  it("sends null for fields that inherit the global value", async () => {
    mockFetch(() => ({ status: 200, body: { path: "x.sql" } }));
    const onSave = renderForm({
      mode: "instance",
      inherited: settings,
      initial: { ...settings, compression: "none" },
      initialOverridden: { storage_dir: false, name_pattern: false, compression: true },
    });
    const toggles = screen.getAllByRole("checkbox", { name: "Override" });
    expect(toggles).toHaveLength(3);

    await userEvent.click(toggles[2]); // compression back to "inherit"
    await userEvent.click(screen.getByRole("button", { name: "Save" }));
    expect(onSave).toHaveBeenCalledWith({
      storage_dir: null,
      name_pattern: null,
      compression: null,
    });
  });

  it("shows translated validation errors from the server", async () => {
    mockFetch(() => ({ status: 200, body: { path: "x.sql" } }));
    renderForm({
      error: new ApiError(422, "validation_error", undefined, {
        name_pattern: "missing_database",
      }),
    });
    await waitFor(() =>
      expect(screen.getByText("The pattern must contain {database}.")).toBeInTheDocument(),
    );
  });

  it("inserts placeholders into the pattern", async () => {
    mockFetch(() => ({ status: 200, body: { path: "x.sql" } }));
    const onSave = renderForm();
    await userEvent.click(screen.getByRole("button", { name: "{server_type}" }));
    await userEvent.click(screen.getByRole("button", { name: "Save" }));
    expect(onSave).toHaveBeenCalledWith({
      ...settings,
      name_pattern: `${settings.name_pattern}{server_type}`,
    });
  });
});
