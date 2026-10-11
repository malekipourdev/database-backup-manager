import { MantineProvider } from "@mantine/core";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import type { DatabaseList } from "../src/api/instances";
import { DatabaseSelectorView } from "../src/components/DatabaseSelector";

const list: DatabaseList = {
  reachable: true,
  error_code: null,
  error_detail: null,
  databases: [
    { name: "blog", is_system: false, selectable: true, selected: true, missing: true },
    {
      name: "information_schema",
      is_system: true,
      selectable: false,
      selected: false,
      missing: false,
    },
    { name: "mysql", is_system: true, selectable: true, selected: false, missing: false },
    { name: "shop", is_system: false, selectable: true, selected: false, missing: false },
  ],
};

function setup(data: DatabaseList = list) {
  const onSave = vi.fn();
  render(
    <MantineProvider>
      <DatabaseSelectorView list={data} saving={false} onSave={onSave} onRetry={() => {}} />
    </MantineProvider>,
  );
  return { onSave };
}

describe("DatabaseSelectorView", () => {
  it("hides system schemas until the toggle is switched on", async () => {
    setup();
    expect(screen.getByText("shop")).toBeInTheDocument();
    expect(screen.queryByText("information_schema")).not.toBeInTheDocument();
    expect(screen.queryByText("mysql")).not.toBeInTheDocument();

    await userEvent.click(screen.getByLabelText("Show system schemas"));
    expect(screen.getByText("information_schema")).toBeInTheDocument();
    expect(screen.getAllByText("system")).toHaveLength(2);
  });

  it("disables non-selectable schemas but allows mysql", async () => {
    setup();
    await userEvent.click(screen.getByLabelText("Show system schemas"));
    expect(screen.getByRole("checkbox", { name: "information_schema" })).toBeDisabled();
    expect(screen.getByRole("checkbox", { name: "mysql" })).toBeEnabled();
  });

  it("marks selected databases missing on the server", () => {
    setup();
    expect(screen.getByText("missing on server")).toBeInTheDocument();
    expect(screen.getByRole("checkbox", { name: "blog" })).toBeChecked();
  });

  it("filters by name and saves the draft selection", async () => {
    const { onSave } = setup();
    await userEvent.type(screen.getByLabelText("Filter by name"), "sho");
    expect(screen.queryByText("blog")).not.toBeInTheDocument();

    await userEvent.click(screen.getByRole("checkbox", { name: "shop" }));
    await userEvent.click(screen.getByRole("button", { name: "Save selection" }));
    expect(onSave).toHaveBeenCalledWith(["blog", "shop"]);
  });

  it("shows the stored selection and an error when unreachable", () => {
    setup({
      reachable: false,
      error_code: "timeout",
      error_detail: null,
      databases: [
        { name: "shop", is_system: false, selectable: true, selected: true, missing: false },
      ],
    });
    expect(screen.getByText("Connection timed out.")).toBeInTheDocument();
    expect(screen.getByRole("checkbox", { name: "shop" })).toBeChecked();
  });

  it("keeps long names inside their own tile, with the full name as a tooltip", () => {
    const long = "kdlsfkdaQAd_Dab4_fdEF31VCfrpQsaS7GHDAa_Fi_Ac9Cou_trZDmGaeKDRS";
    setup({
      ...list,
      databases: [
        { name: long, is_system: false, selectable: true, selected: true, missing: false },
      ],
    });
    const name = screen.getByText(long);
    expect(name).toHaveClass("cl-db-name");
    expect(name).toHaveAttribute("title", long);
    expect(name.closest(".cl-db-tile")).not.toBeNull();
  });
});
