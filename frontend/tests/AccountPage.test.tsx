import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";

import { AccountPage } from "../src/pages/AccountPage";
import { mockFetch, renderWithProviders } from "./render";

const CODES = Array.from({ length: 8 }, (_, i) => `aaaa-bbbb-000${i}`);

describe("AccountPage", () => {
  it("turns two-step verification on and shows the recovery codes once", async () => {
    let enabled = false;
    const fetchMock = mockFetch((url, init) => {
      if (url.endsWith("/auth/me"))
        return { status: 200, body: { username: "admin", two_factor_enabled: enabled } };
      if (url.endsWith("/auth/2fa") && (init.method ?? "GET") === "GET")
        return { status: 200, body: { enabled, recovery_codes_left: enabled ? 8 : 0 } };
      if (url.endsWith("/auth/2fa/setup")) {
        const body = JSON.parse(String(init.body));
        return body.password === "right"
          ? {
              status: 200,
              body: {
                secret: "JBSWY3DPEHPK3PXP",
                otpauth_uri: "otpauth://totp/x",
                qr_svg: "data:image/svg+xml;base64,PHN2Zy8+",
              },
            }
          : {
              status: 403,
              body: { code: "wrong_password", fields: { password: "wrong_password" } },
            };
      }
      if (url.endsWith("/auth/2fa/enable")) {
        enabled = true;
        return { status: 200, body: { recovery_codes: CODES } };
      }
      return { status: 404, body: { code: "not_found" } };
    });
    renderWithProviders(<AccountPage />);

    expect(await screen.findByTestId("two-factor-state")).toHaveTextContent("Off");
    await userEvent.click(screen.getByRole("button", { name: "Turn on" }));
    const dialog = await screen.findByRole("dialog");
    await userEvent.type(within(dialog).getByLabelText(/Password/), "right");
    await userEvent.click(within(dialog).getByRole("button", { name: "Continue" }));

    expect(await within(dialog).findByTestId("totp-qr")).toHaveAttribute(
      "src",
      "data:image/svg+xml;base64,PHN2Zy8+",
    );
    expect(within(dialog).getByDisplayValue("JBSWY3DPEHPK3PXP")).toBeInTheDocument();
    const pins = dialog.querySelectorAll<HTMLInputElement>(".mantine-PinInput-input");
    await userEvent.click(pins[0]);
    await userEvent.keyboard("123456");

    const codes = await within(dialog).findByTestId("recovery-codes");
    expect(within(codes).getAllByText(/aaaa-bbbb-/)).toHaveLength(8);
    const enableCall = fetchMock.mock.calls.find(([u]) => String(u).endsWith("/2fa/enable"));
    expect(JSON.parse(String(enableCall?.[1]?.body))).toEqual({ code: "123456" });

    await userEvent.click(within(dialog).getByRole("button", { name: "I saved them" }));
    expect(await screen.findByTestId("two-factor-state")).toHaveTextContent("On");
    expect(screen.getByText(/Unused recovery codes: 8/)).toBeInTheDocument();
  });

  it("shows a wrong password next to the field", async () => {
    mockFetch((url) => {
      if (url.endsWith("/auth/me")) return { status: 200, body: { username: "admin" } };
      if (url.endsWith("/auth/2fa"))
        return { status: 200, body: { enabled: false, recovery_codes_left: 0 } };
      return {
        status: 403,
        body: { code: "wrong_password", fields: { password: "wrong_password" } },
      };
    });
    renderWithProviders(<AccountPage />);
    await userEvent.click(await screen.findByRole("button", { name: "Turn on" }));
    const dialog = await screen.findByRole("dialog");
    await userEvent.type(within(dialog).getByLabelText(/Password/), "nope");
    await userEvent.click(within(dialog).getByRole("button", { name: "Continue" }));
    expect(await within(dialog).findByText("The password is wrong.")).toBeInTheDocument();
  });

  it("turns two-step verification off with password and code", async () => {
    let enabled = true;
    const fetchMock = mockFetch((url, init) => {
      if (url.endsWith("/auth/me")) return { status: 200, body: { username: "admin" } };
      if (url.endsWith("/auth/2fa"))
        return { status: 200, body: { enabled, recovery_codes_left: 1 } };
      if (url.endsWith("/auth/2fa/disable")) {
        enabled = false;
        expect(JSON.parse(String(init.body))).toEqual({ password: "right", code: "654321" });
        return { status: 204 };
      }
      return { status: 404, body: { code: "not_found" } };
    });
    renderWithProviders(<AccountPage />);

    expect(await screen.findByText(/Few recovery codes are left/)).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Turn off" }));
    const dialog = await screen.findByRole("dialog");
    await userEvent.type(within(dialog).getByLabelText(/Password/), "right");
    await userEvent.type(within(dialog).getByLabelText(/Authenticator code/), "654321");
    await userEvent.click(within(dialog).getByRole("button", { name: "Turn off" }));

    expect(await screen.findByTestId("two-factor-state")).toHaveTextContent("Off");
    expect(fetchMock.mock.calls.some(([u]) => String(u).endsWith("/2fa/disable"))).toBe(true);
  });

  it("shows the current key again to add another device", async () => {
    const fetchMock = mockFetch((url, init) => {
      if (url.endsWith("/auth/me")) return { status: 200, body: { username: "admin" } };
      if (url.endsWith("/auth/2fa"))
        return { status: 200, body: { enabled: true, recovery_codes_left: 8 } };
      if (url.endsWith("/auth/2fa/key")) {
        const body = JSON.parse(String(init.body));
        return body.code === "111222"
          ? {
              status: 200,
              body: {
                secret: "SAMEKEY234567ABC",
                otpauth_uri: "otpauth://totp/x",
                qr_svg: "data:image/svg+xml;base64,PHN2Zy8+",
              },
            }
          : { status: 403, body: { code: "invalid_code", fields: { code: "invalid_code" } } };
      }
      return { status: 404, body: { code: "not_found" } };
    });
    renderWithProviders(<AccountPage />);

    await userEvent.click(await screen.findByRole("button", { name: "Add another device" }));
    const dialog = await screen.findByRole("dialog");
    await userEvent.type(within(dialog).getByLabelText(/Password/), "right");
    await userEvent.type(within(dialog).getByLabelText(/Authenticator code/), "000000");
    await userEvent.click(within(dialog).getByRole("button", { name: "Continue" }));
    expect(await within(dialog).findByText("The code is not valid.")).toBeInTheDocument();

    await userEvent.clear(within(dialog).getByLabelText(/Authenticator code/));
    await userEvent.type(within(dialog).getByLabelText(/Authenticator code/), "111222");
    await userEvent.click(within(dialog).getByRole("button", { name: "Continue" }));
    expect(await within(dialog).findByTestId("totp-qr")).toBeInTheDocument();
    expect(within(dialog).getByDisplayValue("SAMEKEY234567ABC")).toBeInTheDocument();
    expect(fetchMock.mock.calls.some(([u]) => String(u).endsWith("/2fa/key"))).toBe(true);
  });
});
