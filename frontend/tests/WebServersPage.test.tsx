import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";

import { type WebSite, daysLeft, domainsOf } from "../src/api/webservers";
import { tokenize } from "../src/components/ConfigCode";
import { WebServersPage } from "../src/pages/WebServersPage";
import { CurrentServerContext } from "../src/server/CurrentServer";
import { EDGE, currentOn } from "./servers";
import { mockFetch, renderWithProviders } from "./render";

const site = (over: Partial<WebSite>): WebSite => ({
  server: "nginx",
  names: [],
  ports: [80],
  ssl: false,
  default_server: false,
  root: null,
  redirect: null,
  backends: [],
  certificate: null,
  file: "/etc/nginx/sites-available/shop",
  line: 1,
  enabled: true,
  logs: { access: "/var/log/nginx/access.log", error: "/var/log/nginx/error.log" },
  ...over,
});

const NGINX = {
  kind: "nginx",
  config: "/etc/nginx/nginx.conf",
  error: null,
  warnings: ["included file not found: /etc/nginx/x.conf (/etc/nginx/nginx.conf:9)"],
  files: 4,
  sites: [
    site({ names: ["shop.example"], redirect: "https://$host$request_uri" }),
    site({
      names: ["shop.example"],
      ports: [443],
      ssl: true,
      line: 9,
      certificate: "/etc/letsencrypt/live/shop.example/fullchain.pem",
      backends: [{ kind: "proxy", target: "http://app", servers: ["127.0.0.1:3000"] }],
    }),
    site({ ports: [8080], default_server: true, root: "/var/www/html" }),
    site({ names: ["old.example"], enabled: false, root: "/srv/old" }),
    site({ names: ["shop.example"], file: "/x/mbp-maintenance-shop", maintenance_page: true }),
  ],
};
const APACHE = {
  kind: "apache",
  config: "/etc/apache2/apache2.conf",
  error: null,
  warnings: [],
  files: 3,
  sites: [
    site({
      server: "apache",
      names: ["blog.example"],
      root: "/var/www/blog",
      file: "/etc/apache2/sites-available/blog.conf",
      maintenance: true,
    }),
  ],
};
const inDays = (days: number) => new Date(Date.now() + days * 86_400_000 + 3_600_000).toISOString();
const SHOP_CONF = "server {\n    listen 80;\n    server_name shop.example; # main\n}\n";

type Handler = Parameters<typeof mockFetch>[0];

function api(overrides: Record<string, ReturnType<Handler>> = {}) {
  const calls: { method: string; url: string; body: unknown }[] = [];
  const handler: Handler = (url, init) => {
    const method = init.method ?? "GET";
    const path = url.replace(/^\/api/, "").split("?")[0];
    calls.push({ method, url, body: init.body ? JSON.parse(String(init.body)) : undefined });
    const key = `${method} ${path}`;
    if (overrides[key]) return overrides[key];
    switch (key) {
      case "GET /webservers":
        return { status: 200, body: { available: true, servers: [NGINX, APACHE] } };
      case "GET /webservers/-/status":
        return {
          status: 200,
          body: {
            servers: [
              {
                kind: "nginx",
                service: "nginx",
                state: "active",
                sub_state: "running",
                since: "Mon 2026-10-26 08:00:00 UTC",
                pid: 10,
                version: "1.24.0",
                last_reload: null,
                panel_reload: null,
                systemd: true,
              },
            ],
          },
        };
      case "GET /webservers/-/settings":
        return {
          status: 200,
          body: {
            read_only: false,
            cert_warning_days: 14,
            check_interval_minutes: 5,
            check_timeout_seconds: 10,
            check_failures: 2,
            acme_email: null,
          },
        };
      case "GET /webservers/-/certificates":
        return {
          status: 200,
          body: {
            certificates: {
              "/etc/letsencrypt/live/shop.example/fullchain.pem": {
                subject: "shop.example",
                names: ["shop.example"],
                issuer: "Let's Encrypt",
                not_before: null,
                not_after: inDays(9),
                error: null,
              },
            },
          },
        };
      case "GET /webservers/-/certbot":
        return {
          status: 200,
          body: {
            installed: true,
            version: "2.9.0",
            auto_renew: "certbot.timer",
            package_manager: "apt",
          },
        };
      case "GET /webservers/-/checks":
        return {
          status: 200,
          body: {
            checks: [
              {
                id: 1,
                server_id: 4,
                url: "https://shop.example/",
                enabled: true,
                created_at: "2026-10-27T08:00:00Z",
                last_checked_at: "2026-10-27T10:00:00Z",
                status: "down",
                last_code: 502,
                last_ms: 120,
                last_error: null,
                failures: 3,
                down_since: "2026-10-27T09:50:00Z",
                uptime: 75,
                recent: [
                  { checked_at: "2026-10-27T09:55:00Z", ok: true, code: 200, ms: 90, error: null },
                  {
                    checked_at: "2026-10-27T10:00:00Z",
                    ok: false,
                    code: 502,
                    ms: 120,
                    error: null,
                  },
                ],
              },
            ],
          },
        };
      case "GET /containers":
        return { status: 200, body: { containers: [], read_only: false } };
      case "GET /webservers/nginx/file":
        return {
          status: 200,
          body: {
            path: "/etc/nginx/sites-available/shop",
            content: SHOP_CONF,
            sha256: "abc",
            size: SHOP_CONF.length,
          },
        };
      case "GET /webservers/-/actions":
        return { status: 200, body: { items: [], total: 0, page: 1, page_size: 25 } };
      default:
        return { status: 200, body: { ok: true, code: null, output: "syntax is ok" } };
    }
  };
  const fetchMock = mockFetch(handler);
  return { calls, fetchMock };
}

function renderPage() {
  return renderWithProviders(
    <CurrentServerContext.Provider value={currentOn(EDGE)}>
      <WebServersPage />
    </CurrentServerContext.Provider>,
  );
}

describe("domainsOf", () => {
  it("merges blocks of one name, keeps catch-alls and disabled sites apart, hides maintenance pages", () => {
    const domains = domainsOf([NGINX, APACHE] as never);
    expect(
      domains.map((d) => [d.name, d.server, d.enabled, d.ports, d.ssl, d.maintenance]),
    ).toEqual([
      ["blog.example", "apache", true, [80], false, true],
      ["shop.example", "nginx", true, [80, 443], true, false],
      ["", "nginx", true, [8080], false, false],
      ["old.example", "nginx", false, [80], false, false],
    ]);
    expect(domains[1].sites).toHaveLength(2);
  });

  it("counts the days a certificate has left", () => {
    expect(daysLeft({ not_after: inDays(9) } as never)).toBe(9);
    expect(daysLeft({ not_after: inDays(-2) } as never)).toBe(-2);
    expect(daysLeft(undefined)).toBeNull();
  });
});

describe("tokenize", () => {
  it("colours directives, strings, variables and comments", () => {
    expect(
      tokenize('    return 301 "https://$host"; # x').filter((t) => t.type !== "text"),
    ).toEqual([
      { type: "directive", text: "return" },
      { type: "number", text: "301" },
      { type: "string", text: '"https://$host"' },
      { type: "punct", text: ";" },
      { type: "comment", text: "# x" },
    ]);
    expect(tokenize("<VirtualHost *:443>")[0]).toEqual({
      type: "section",
      text: "<VirtualHost *:443>",
    });
    expect(tokenize("root ${APACHE_LOG_DIR}/x")[2]).toEqual({
      type: "variable",
      text: "${APACHE_LOG_DIR}",
    });
  });
});

describe("WebServersPage", () => {
  it("shows status, domains, certificates and health", async () => {
    const { calls } = api();
    renderPage();
    const shop = await screen.findByTestId("domain-shop.example");
    expect(calls.some((c) => c.url.startsWith("/api/webservers?server=4"))).toBe(true);
    expect(within(shop).getByText("80, 443")).toBeInTheDocument();
    expect(within(shop).getByText(/http:\/\/app/)).toBeInTheDocument();
    expect(await within(shop).findByText(/9 days left/)).toBeInTheDocument();
    expect(await within(shop).findByText("Down")).toBeInTheDocument();
    expect(screen.getByTestId("domain-blog.example")).toHaveTextContent("Maintenance");
    expect(screen.getByTestId("domain-catch-all")).toBeInTheDocument();
    const card = screen.getByTestId("webserver-nginx");
    expect(card).toHaveTextContent("/etc/nginx/x.conf");
    expect(await within(card).findByText("Running")).toBeInTheDocument();
    expect(within(card).getByText("1.24.0")).toBeInTheDocument();
    expect(await screen.findByText("certbot 2.9.0")).toBeInTheDocument();
    // Disabled sites only under "All"; search.
    expect(screen.queryByTestId("domain-old.example")).not.toBeInTheDocument();
    await userEvent.click(screen.getByRole("radio", { name: /\+1/ }));
    expect(await screen.findByTestId("domain-old.example")).toBeInTheDocument();
    await userEvent.type(screen.getByPlaceholderText(/Search domain/), "blog");
    await waitFor(() =>
      expect(screen.queryByTestId("domain-shop.example")).not.toBeInTheDocument(),
    );
  });

  it("reloads after a test and shows the outcome", async () => {
    const { calls } = api();
    renderPage();
    const card = await screen.findByTestId("webserver-nginx");
    await userEvent.click(within(card).getByRole("button", { name: /Reload/ }));
    expect(await within(card).findByText(/configuration was tested/)).toBeInTheDocument();
    expect(
      calls.some(
        (c) => c.method === "POST" && c.url.includes("/webservers/nginx/control/reload?server=4"),
      ),
    ).toBe(true);
  });

  it("opens a site: highlighted configuration, edit with the read version, rollback output", async () => {
    const { calls } = api({
      "PUT /webservers/nginx/file": {
        status: 200,
        body: {
          ok: false,
          code: "config_test_failed",
          output: "unexpected } in shop:3",
          path: "/etc/nginx/sites-available/shop",
        },
      },
    });
    renderPage();
    await userEvent.click(await screen.findByTestId("domain-shop.example"));
    const code = await screen.findByTestId("config-code");
    expect(code).toHaveTextContent("server_name shop.example;");
    await userEvent.click(screen.getByRole("button", { name: "Edit" }));
    const editor = screen.getByLabelText("Configuration file");
    await userEvent.type(editor, "x");
    await userEvent.click(screen.getByRole("button", { name: "Test, save and reload" }));
    const result = await screen.findByTestId("web-result");
    expect(result).toHaveTextContent("The configuration test failed");
    expect(result).toHaveTextContent("unexpected } in shop:3");
    const put = calls.find((c) => c.method === "PUT")!;
    expect(put.body).toEqual({
      path: "/etc/nginx/sites-available/shop",
      content: `${SHOP_CONF}x`,
      sha256: "abc",
    });
  });

  it("creates a site from a template", async () => {
    const { calls } = api({
      "POST /webservers/nginx/sites": {
        status: 201,
        body: { ok: true, code: null, output: "", path: "/etc/nginx/sites-available/app" },
      },
    });
    renderPage();
    await userEvent.click(await screen.findByRole("button", { name: "New site" }));
    const dialog = await screen.findByRole("dialog");
    await userEvent.click(within(dialog).getByRole("radio", { name: "nginx" }));
    await userEvent.type(within(dialog).getByLabelText(/Domains/), "app.example{enter}");
    await userEvent.click(within(dialog).getByRole("button", { name: /Create, test and reload/ }));
    expect(await within(dialog).findByTestId("web-result")).toHaveTextContent("Done");
    const post = calls.find((c) => c.method === "POST" && c.url.includes("/sites"))!;
    expect(post.body).toMatchObject({
      template: "proxy",
      domains: ["app.example"],
      target: "http://127.0.0.1:8080",
    });
  });

  it("adds a health check", async () => {
    const { calls } = api();
    renderPage();
    await userEvent.click(await screen.findByRole("tab", { name: "Health checks" }));
    expect(await screen.findByTestId("check-https://shop.example/")).toHaveTextContent("75%");
    const input = screen.getByLabelText(/Address/);
    await userEvent.clear(input);
    await userEvent.type(input, "https://blog.example/");
    await userEvent.click(screen.getByRole("button", { name: "Add" }));
    await waitFor(() =>
      expect(calls.find((c) => c.method === "POST" && c.url.includes("/checks"))?.body).toEqual({
        url: "https://blog.example/",
      }),
    );
  });

  it("read-only disables changes", async () => {
    api({
      "GET /webservers/-/settings": {
        status: 200,
        body: {
          read_only: true,
          cert_warning_days: 14,
          check_interval_minutes: 5,
          check_timeout_seconds: 10,
          check_failures: 2,
          acme_email: null,
        },
      },
    });
    renderPage();
    expect(await screen.findByText("Read-only")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "New site" })).toBeDisabled();
    const card = screen.getByTestId("webserver-nginx");
    expect(within(card).getByRole("button", { name: /Reload/ })).toBeDisabled();
  });

  it("explains a missing mount", async () => {
    api({ "GET /webservers": { status: 200, body: { available: false, servers: [] } } });
    renderWithProviders(<WebServersPage />);
    expect(await screen.findByText(/docker compose up -d --build agent/)).toBeInTheDocument();
  });

  it("names an outdated agent", async () => {
    api({ "GET /webservers": { status: 409, body: { code: "agent_outdated" } } });
    renderWithProviders(<WebServersPage />);
    expect((await screen.findAllByText(/git pull/)).length).toBeGreaterThan(0);
    const hrefs = screen.getAllByRole("link").map((a) => a.getAttribute("href"));
    expect(hrefs).toContain("/containers");
  });
});
