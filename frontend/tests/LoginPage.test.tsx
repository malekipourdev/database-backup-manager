import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";

import { LoginPage } from "../src/pages/LoginPage";
import { mockFetch, renderWithProviders } from "./render";

describe("LoginPage", () => {
  it("shows the generic translated error on invalid credentials", async () => {
    mockFetch((url) =>
      url.endsWith("/auth/me")
        ? { status: 401, body: { code: "not_authenticated" } }
        : { status: 401, body: { code: "invalid_credentials" } },
    );
    renderWithProviders(<LoginPage />, { path: "/login", route: "/login" });

    await userEvent.type(await screen.findByLabelText(/Username/), "admin");
    await userEvent.type(screen.getByLabelText(/Password/), "wrong");
    await userEvent.click(screen.getByRole("button", { name: "Sign in" }));

    expect(await screen.findByRole("alert")).toHaveTextContent("Invalid username or password.");
  });

  it("navigates away after a successful sign-in", async () => {
    const fetchMock = mockFetch((url) =>
      url.endsWith("/auth/me")
        ? { status: 401, body: { code: "not_authenticated" } }
        : { status: 200, body: { username: "admin" } },
    );
    renderWithProviders(<LoginPage />, { path: "/login", route: "/login" });

    await userEvent.type(await screen.findByLabelText(/Username/), "admin");
    await userEvent.type(screen.getByLabelText(/Password/), "right");
    await userEvent.click(screen.getByRole("button", { name: "Sign in" }));

    expect(await screen.findByTestId("navigated")).toBeInTheDocument();
    const loginCall = fetchMock.mock.calls.find(([url]) => String(url).endsWith("/auth/login"));
    const headers = loginCall?.[1]?.headers as Record<string, string>;
    expect(headers["X-Requested-With"]).toBe("mbp");
  });

  it("requires both fields", async () => {
    const fetchMock = mockFetch(() => ({ status: 401, body: { code: "not_authenticated" } }));
    renderWithProviders(<LoginPage />, { path: "/login", route: "/login" });
    await userEvent.click(await screen.findByRole("button", { name: "Sign in" }));
    await waitFor(() => expect(screen.getAllByText("This field is required.")).toHaveLength(2));
    expect(fetchMock.mock.calls.some(([url]) => String(url).endsWith("/auth/login"))).toBe(false);
  });
});
