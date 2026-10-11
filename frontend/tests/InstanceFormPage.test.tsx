import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";

import type { Instance } from "../src/api/instances";
import { InstanceFormPage } from "../src/pages/InstanceFormPage";
import { mockFetch, renderWithProviders } from "./render";

const instance: Instance = {
  id: 7,
  name: "prod",
  host: "db.internal",
  port: 3306,
  username: "backup",
  notes: "",
  has_password: true,
  server_type: null,
  server_version: null,
  last_test_at: null,
  last_test_ok: null,
  last_test_error_code: null,
  created_at: "2026-10-11T10:00:00Z",
  updated_at: "2026-10-11T10:00:00Z",
};

describe("InstanceFormPage", () => {
  it("edit mode keeps the stored password when the field is left empty", async () => {
    const fetchMock = mockFetch((_url, init) => {
      if (init.method === "PATCH") return { status: 200, body: { ...instance, notes: "x" } };
      return { status: 200, body: instance };
    });
    renderWithProviders(<InstanceFormPage />, {
      path: "/instances/:id/edit",
      route: "/instances/7/edit",
    });

    expect(await screen.findByText("A password is stored. Leave empty to keep it.")).toBeVisible();
    const password = screen.getByLabelText(/Password/) as HTMLInputElement;
    expect(password.value).toBe("");

    await userEvent.type(screen.getByLabelText(/Notes/), "x");
    await userEvent.click(screen.getByRole("button", { name: "Save" }));

    await waitFor(() =>
      expect(fetchMock.mock.calls.some(([, init]) => init?.method === "PATCH")).toBe(true),
    );
    const patch = fetchMock.mock.calls.find(([, init]) => init?.method === "PATCH")!;
    const body = JSON.parse(String(patch[1]!.body));
    expect(body).not.toHaveProperty("password");
    expect(body.notes).toBe("x");
  });

  it("shows a translated error for an invalid port", async () => {
    const fetchMock = mockFetch(() => ({ status: 201, body: instance }));
    renderWithProviders(<InstanceFormPage />, { path: "/instances/new", route: "/instances/new" });

    await userEvent.type(screen.getByLabelText(/Name/), "prod");
    await userEvent.type(screen.getByLabelText(/Host/), "db.internal");
    const port = screen.getByLabelText(/Port/);
    await userEvent.clear(port);
    await userEvent.type(port, "70000");
    await userEvent.type(screen.getByLabelText(/Username/), "backup");
    await userEvent.type(screen.getByLabelText(/Password/), "secret");
    await userEvent.click(screen.getByRole("button", { name: "Save" }));

    expect(
      await screen.findByText("Port must be a number between 1 and 65535."),
    ).toBeInTheDocument();
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("maps name_taken from the server to the name field", async () => {
    mockFetch(() => ({
      status: 409,
      body: { code: "name_taken", fields: { name: "name_taken" } },
    }));
    renderWithProviders(<InstanceFormPage />, { path: "/instances/new", route: "/instances/new" });

    await userEvent.type(screen.getByLabelText(/Name/), "prod");
    await userEvent.type(screen.getByLabelText(/Host/), "db.internal");
    await userEvent.type(screen.getByLabelText(/Username/), "backup");
    await userEvent.type(screen.getByLabelText(/Password/), "secret");
    await userEvent.click(screen.getByRole("button", { name: "Save" }));

    expect(
      await screen.findByText("This name is already used by another instance."),
    ).toBeInTheDocument();
  });
});
