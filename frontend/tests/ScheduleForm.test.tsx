import { MantineProvider } from "@mantine/core";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { ApiError } from "../src/api/client";
import { EMPTY_SCHEDULE, ScheduleForm } from "../src/components/ScheduleForm";
import { mockFetch } from "./render";

const NEXT = ["2026-10-12T02:00:00Z", "2026-10-13T02:00:00Z"];

function renderForm(props: Partial<Parameters<typeof ScheduleForm>[0]> = {}) {
  const onSave = vi.fn();
  render(
    <MantineProvider>
      <ScheduleForm
        initial={EMPTY_SCHEDULE}
        saving={false}
        error={null}
        onSave={onSave}
        onCancel={() => {}}
        {...props}
      />
    </MantineProvider>,
  );
  return onSave;
}

describe("ScheduleForm", () => {
  it("previews the next runs from the server", async () => {
    const fetchMock = mockFetch(() => ({ status: 200, body: { next_runs: NEXT } }));
    renderForm();
    const preview = await screen.findByTestId("schedule-preview");
    expect(preview.querySelectorAll("li")).toHaveLength(2);
    const [url, init] = fetchMock.mock.calls[0];
    expect(String(url)).toBe("/api/schedules/preview");
    expect(JSON.parse(String(init?.body))).toEqual({ cron: "0 2 * * *", timezone: "UTC" });
  });

  it("fills the cron field from a preset and saves without a database for 'all'", async () => {
    mockFetch(() => ({ status: 200, body: { next_runs: NEXT } }));
    const onSave = renderForm();
    await userEvent.type(screen.getByLabelText(/Name/), "  Hourly job ");
    await userEvent.click(screen.getByText("Hourly"));
    expect(screen.getByLabelText("Cron expression")).toHaveValue("0 * * * *");
    await userEvent.click(screen.getByRole("button", { name: "Save" }));
    expect(onSave).toHaveBeenCalledWith({
      name: "Hourly job",
      cron: "0 * * * *",
      timezone: "UTC",
      scope: "all",
      database: null,
      enabled: true,
    });
  });

  it("asks for a database for a single-database schedule", async () => {
    mockFetch(() => ({ status: 200, body: { next_runs: NEXT } }));
    const onSave = renderForm();
    await userEvent.type(screen.getByLabelText(/Name/), "Shop");
    await userEvent.click(screen.getByText("One database"));
    await userEvent.type(screen.getByLabelText(/Database/), "shop");
    await userEvent.click(screen.getByRole("button", { name: "Save" }));
    expect(onSave.mock.calls[0][0]).toMatchObject({ scope: "single", database: "shop" });
  });

  it("shows server validation errors on the field and invalid cron in the preview", async () => {
    mockFetch(() => ({
      status: 422,
      body: { code: "validation_error", fields: { cron: "invalid_cron" } },
    }));
    renderForm({
      error: new ApiError(422, "validation_error", undefined, { cron: "invalid_cron" }),
    });
    await waitFor(() =>
      expect(screen.getAllByText(/Enter a valid 5-field cron expression/)).toHaveLength(2),
    );
  });
});
