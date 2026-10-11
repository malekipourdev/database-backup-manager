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

describe("LoginPage two-step verification", () => {
  const pinInputs = () => document.querySelectorAll<HTMLInputElement>(".mantine-PinInput-input");

  it("asks for the authenticator code and signs in with it", async () => {
    const fetchMock = mockFetch((url, init) => {
      if (url.endsWith("/auth/me")) return { status: 401, body: { code: "not_authenticated" } };
      if (url.endsWith("/auth/login/2fa")) {
        const body = JSON.parse(String(init.body));
        return body.code === "123456" && body.challenge === "ch-1"
          ? { status: 200, body: { username: "admin", two_factor_required: false } }
          : { status: 401, body: { code: "invalid_code" } };
      }
      return {
        status: 200,
        body: { username: "admin", two_factor_required: true, challenge: "ch-1" },
      };
    });
    renderWithProviders(<LoginPage />, { path: "/login", route: "/login" });

    await userEvent.type(await screen.findByLabelText(/Username/), "admin");
    await userEvent.type(screen.getByLabelText(/Password/), "right");
    await userEvent.click(screen.getByRole("button", { name: "Sign in" }));

    expect(await screen.findByText("Two-step verification")).toBeInTheDocument();
    expect(screen.queryByTestId("navigated")).not.toBeInTheDocument();
    await userEvent.click(pinInputs()[0]);
    await userEvent.keyboard("123456");

    expect(await screen.findByTestId("navigated")).toBeInTheDocument();
    expect(fetchMock.mock.calls.some(([url]) => String(url).endsWith("/auth/login/2fa"))).toBe(
      true,
    );
  });

  it("shows an error for a wrong code and accepts a recovery code", async () => {
    mockFetch((url, init) => {
      if (url.endsWith("/auth/me")) return { status: 401, body: { code: "not_authenticated" } };
      if (url.endsWith("/auth/login/2fa")) {
        const body = JSON.parse(String(init.body));
        return body.code === "abcd-efgh-jkmn"
          ? { status: 200, body: { username: "admin", two_factor_required: false } }
          : { status: 401, body: { code: "invalid_code" } };
      }
      return {
        status: 200,
        body: { username: "admin", two_factor_required: true, challenge: "ch-1" },
      };
    });
    renderWithProviders(<LoginPage />, { path: "/login", route: "/login" });

    await userEvent.type(await screen.findByLabelText(/Username/), "admin");
    await userEvent.type(screen.getByLabelText(/Password/), "right");
    await userEvent.click(screen.getByRole("button", { name: "Sign in" }));
    await screen.findByText("Two-step verification");
    await userEvent.click(pinInputs()[0]);
    await userEvent.keyboard("000000");
    expect(await screen.findByRole("alert")).toHaveTextContent(/The code is not valid/);

    await userEvent.click(screen.getByRole("button", { name: "Use a recovery code" }));
    await userEvent.type(screen.getByLabelText("Recovery code"), "abcd-efgh-jkmn");
    await userEvent.click(screen.getByRole("button", { name: "Verify" }));
    expect(await screen.findByTestId("navigated")).toBeInTheDocument();
  });

  it("goes back to the password step when the challenge expired", async () => {
    mockFetch((url) => {
      if (url.endsWith("/auth/me")) return { status: 401, body: { code: "not_authenticated" } };
      if (url.endsWith("/auth/login/2fa"))
        return { status: 401, body: { code: "challenge_expired" } };
      return {
        status: 200,
        body: { username: "admin", two_factor_required: true, challenge: "ch-1" },
      };
    });
    renderWithProviders(<LoginPage />, { path: "/login", route: "/login" });

    await userEvent.type(await screen.findByLabelText(/Username/), "admin");
    await userEvent.type(screen.getByLabelText(/Password/), "right");
    await userEvent.click(screen.getByRole("button", { name: "Sign in" }));
    await screen.findByText("Two-step verification");
    await userEvent.click(pinInputs()[0]);
    await userEvent.keyboard("123456");

    expect(await screen.findByRole("button", { name: "Sign in" })).toBeInTheDocument();
    expect(screen.getByLabelText(/Password/)).toHaveValue("");
  });
});
