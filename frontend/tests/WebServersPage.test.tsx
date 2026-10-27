import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";

import { type WebSite, domainsOf } from "../src/api/webservers";
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
    }),
  ],
};

describe("domainsOf", () => {
  it("merges the blocks of one name and keeps catch-alls and disabled sites apart", () => {
    const domains = domainsOf([NGINX, APACHE] as never);
    expect(domains.map((d) => [d.name, d.server, d.enabled, d.ports, d.ssl])).toEqual([
      ["blog.example", "apache", true, [80], false],
      ["shop.example", "nginx", true, [80, 443], true],
      ["", "nginx", true, [8080], false],
      ["old.example", "nginx", false, [80], false],
    ]);
  });
});

describe("WebServersPage", () => {
  it("lists the domains of the current server", async () => {
    const fetchMock = mockFetch(() => ({
      status: 200,
      body: { available: true, servers: [NGINX, APACHE] },
    }));
    renderWithProviders(
      <CurrentServerContext.Provider value={currentOn(EDGE)}>
        <WebServersPage />
      </CurrentServerContext.Provider>,
    );
    const shop = await screen.findByTestId("domain-shop.example");
    expect(String(fetchMock.mock.calls[0][0])).toContain("/api/webservers?server=4");
    expect(within(shop).getByText("80, 443")).toBeInTheDocument();
    expect(within(shop).getByText(/http:\/\/app/)).toBeInTheDocument();
    expect(within(shop).getByText(/127\.0\.0\.1:3000/)).toBeInTheDocument();
    expect(within(shop).getByRole("link", { name: "shop.example" })).toHaveAttribute(
      "href",
      "https://shop.example",
    );
    expect(screen.getByTestId("domain-blog.example")).toHaveTextContent("/var/www/blog");
    expect(screen.getByTestId("domain-catch-all")).toBeInTheDocument();
    expect(screen.getByTestId("webserver-nginx")).toHaveTextContent("/etc/nginx/x.conf");
    // Disabled sites only under "All".
    expect(screen.queryByTestId("domain-old.example")).not.toBeInTheDocument();
    await userEvent.click(screen.getByRole("radio", { name: /\+1/ }));
    expect(await screen.findByTestId("domain-old.example")).toBeInTheDocument();
    await userEvent.type(screen.getByRole("textbox"), "blog");
    await waitFor(() =>
      expect(screen.queryByTestId("domain-shop.example")).not.toBeInTheDocument(),
    );
    expect(screen.getByTestId("domain-blog.example")).toBeInTheDocument();
  });

  it("explains a missing mount", async () => {
    mockFetch(() => ({ status: 200, body: { available: false, servers: [] } }));
    renderWithProviders(<WebServersPage />);
    expect(await screen.findByText(/docker compose up -d --build agent/)).toBeInTheDocument();
  });

  it("names an outdated agent", async () => {
    mockFetch(() => ({ status: 409, body: { code: "agent_outdated" } }));
    renderWithProviders(<WebServersPage />);
    expect((await screen.findAllByText(/git pull/)).length).toBeGreaterThan(0);
    const hrefs = screen.getAllByRole("link").map((a) => a.getAttribute("href"));
    expect(hrefs).toContain("/containers");
  });
});
