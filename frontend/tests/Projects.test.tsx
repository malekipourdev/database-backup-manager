import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";

import { ProjectDetailPage } from "../src/pages/ProjectDetailPage";
import { ProjectFormPage } from "../src/pages/ProjectFormPage";
import { ProjectsPage } from "../src/pages/ProjectsPage";
import { CurrentServerContext } from "../src/server/CurrentServer";
import { mockFetch, renderWithProviders } from "./render";
import { LOCAL, currentOn } from "./servers";

const DEPLOYMENT = {
  id: 7,
  project_id: 1,
  project_name: "shop",
  status: "success",
  step: "check",
  ref: "main",
  commit_sha: "abcdef1234567890abcdef1234567890abcdef12",
  commit_message: "Add checkout",
  trigger: "panel",
  actor: "admin",
  error_code: null,
  error_detail: null,
  backup_run_ids: [],
  requested_at: "2026-10-12T08:00:00Z",
  started_at: "2026-10-12T08:00:01Z",
  finished_at: "2026-10-12T08:01:31Z",
};
const PROJECT = {
  id: 1,
  name: "shop",
  repo_url: "https://github.com/acme/shop.git",
  branch: "main",
  compose_file: "docker-compose.yml",
  auth_type: "token",
  has_credential: true,
  env_names: ["DB_PASSWORD", "MODE"],
  backup_instance_id: null,
  backup_databases: [],
  backup_required: true,
  web_domains: [],
  web_target: null,
  build_server_id: null,
  build_server_name: null,
  created_at: "2026-10-12T07:00:00Z",
  updated_at: "2026-10-12T07:00:00Z",
  last_deployment: DEPLOYMENT,
  last_success: DEPLOYMENT,
};

describe("Projects", () => {
  it("lists projects with their last deploy", async () => {
    mockFetch(() => ({ status: 200, body: [PROJECT] }));
    renderWithProviders(<ProjectsPage />);
    const card = await screen.findByTestId("project-shop");
    expect(within(card).getByText("Deployed")).toBeInTheDocument();
    expect(within(card).getByText("abcdef12")).toBeInTheDocument();
  });

  it("can build on another server", async () => {
    const fetchMock = mockFetch((url, init) => {
      if (url.endsWith("/instances")) return { status: 200, body: [] };
      if (url.endsWith("/projects") && init.method === "POST")
        return { status: 201, body: { ...PROJECT, last_deployment: null, last_success: null } };
      return { status: 404, body: { code: "not_found" } };
    });
    renderWithProviders(
      <CurrentServerContext.Provider value={currentOn(LOCAL)}>
        <ProjectFormPage />
      </CurrentServerContext.Provider>,
      { path: "/projects/new", route: "/projects/new" },
    );
    await userEvent.type(await screen.findByLabelText(/^Name/), "shop");
    await userEvent.type(screen.getByLabelText(/^Repository/), "https://github.com/acme/shop.git");
    expect(screen.getByText(/happens on the project's server/)).toBeInTheDocument();
    await userEvent.click(screen.getByRole("textbox", { name: "Build on" }));
    // Only other connected servers are offered ("new" is not connected).
    expect(screen.queryByRole("option", { name: "new" })).not.toBeInTheDocument();
    await userEvent.click(await screen.findByRole("option", { name: "edge" }));
    expect(screen.getByText(/streamed through the panel/)).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Save" }));
    await waitFor(() =>
      expect(fetchMock.mock.calls.some(([, init]) => init?.method === "POST")).toBe(true),
    );
    const post = fetchMock.mock.calls.find(([, init]) => init?.method === "POST")!;
    expect(JSON.parse(String(post[1]!.body)).build_server_id).toBe(4);
  });

  it("creates a project without echoing secrets back", async () => {
    const fetchMock = mockFetch((url, init) => {
      if (url.endsWith("/instances")) return { status: 200, body: [] };
      if (url.endsWith("/projects") && init.method === "POST")
        return { status: 201, body: { ...PROJECT, last_deployment: null, last_success: null } };
      return { status: 404, body: { code: "not_found" } };
    });
    renderWithProviders(<ProjectFormPage />, { path: "/projects/new", route: "/projects/new" });
    await userEvent.type(await screen.findByLabelText(/^Name/), "Shop");
    await userEvent.type(screen.getByLabelText(/^Repository/), "https://github.com/acme/shop.git");
    await userEvent.click(screen.getByText("Access token"));
    await userEvent.type(
      screen.getByLabelText(/^Access token/, { selector: "input[type=password]" }),
      "ghp_secret",
    );
    await userEvent.click(screen.getByRole("button", { name: "Add variable" }));
    await userEvent.type(screen.getByLabelText("NAME"), "DB_PASSWORD");
    await userEvent.type(screen.getByLabelText("Value"), "pw-1");
    await userEvent.click(screen.getByRole("button", { name: "Save" }));
    await waitFor(() =>
      expect(fetchMock.mock.calls.some(([, init]) => init?.method === "POST")).toBe(true),
    );
    const post = fetchMock.mock.calls.find(([, init]) => init?.method === "POST")!;
    // Exactly the fields the API accepts (it refuses unknown ones).
    expect(Object.keys(JSON.parse(String(post[1]!.body))).sort()).toEqual([
      "auth_type",
      "backup_databases",
      "backup_instance_id",
      "backup_required",
      "branch",
      "build_server_id",
      "clear_credential",
      "compose_file",
      "credential",
      "env",
      "name",
      "repo_url",
      "server_id",
      "web_domains",
      "web_target",
    ]);
    expect(JSON.parse(String(post[1]!.body))).toMatchObject({
      name: "shop",
      auth_type: "token",
      credential: "ghp_secret",
      env: [{ name: "DB_PASSWORD", value: "pw-1" }],
      server_id: null,
    });
    expect(await screen.findByTestId("navigated")).toBeInTheDocument();
  });

  it("keeps stored values and the credential when editing", async () => {
    const fetchMock = mockFetch((url, init) => {
      if (url.endsWith("/instances")) return { status: 200, body: [] };
      if (url.endsWith("/projects/1") && init.method === "PUT")
        return { status: 200, body: PROJECT };
      if (url.endsWith("/projects/1")) return { status: 200, body: PROJECT };
      return { status: 404, body: { code: "not_found" } };
    });
    renderWithProviders(<ProjectFormPage />, {
      path: "/projects/:id/edit",
      route: "/projects/1/edit",
    });
    expect(await screen.findByDisplayValue("DB_PASSWORD")).toBeInTheDocument();
    expect(screen.getByLabelText(/^Name/)).toBeDisabled();
    await userEvent.click(screen.getAllByRole("button", { name: "Remove variable" })[1]);
    await userEvent.click(screen.getByRole("button", { name: "Save" }));
    await waitFor(() =>
      expect(fetchMock.mock.calls.some(([, init]) => init?.method === "PUT")).toBe(true),
    );
    const put = fetchMock.mock.calls.find(([, init]) => init?.method === "PUT")!;
    expect(JSON.parse(String(put[1]!.body))).toMatchObject({
      credential: null,
      env: [{ name: "DB_PASSWORD", value: null }],
    });
  });

  it("deploys after confirmation and shows the log", async () => {
    let deployed = false;
    const running = { ...DEPLOYMENT, id: 8, status: "running", step: "build", commit_sha: null };
    const fetchMock = mockFetch((url) => {
      if (url.endsWith("/projects/1/deploy")) {
        deployed = true;
        return { status: 202, body: running };
      }
      if (url.endsWith("/projects/1/state"))
        return {
          status: 200,
          body: {
            available: true,
            error_code: null,
            exists: true,
            commit_sha: DEPLOYMENT.commit_sha,
            commit_message: "Add checkout",
          },
        };
      if (url.includes("/projects/1/deployments"))
        return {
          status: 200,
          body: {
            items: deployed ? [running, DEPLOYMENT] : [DEPLOYMENT],
            total: 2,
            page: 1,
            page_size: 15,
          },
        };
      if (url.endsWith("/deployments/8"))
        return {
          status: 200,
          body: { ...running, log: "$ docker compose build\n#1 building", log_size: 30 },
        };
      if (url.endsWith("/deployments/7"))
        return { status: 200, body: { ...DEPLOYMENT, log: "✔ Deployed.", log_size: 11 } };
      if (url.endsWith("/containers"))
        return {
          status: 200,
          body: {
            read_only: false,
            containers: [
              {
                id: "c1",
                name: "shop-web-1",
                project: "shop",
                service: "web",
                state: "running",
                problem: null,
                health: null,
                image: "x",
                ports: [],
                locked: false,
                monitored: true,
                restart_count: 0,
                restart_policy: "no",
                panel: null,
                exit_code: 0,
                oom_killed: false,
                created_at: null,
                started_at: null,
                finished_at: null,
              },
            ],
          },
        };
      if (url.endsWith("/projects/1")) return { status: 200, body: PROJECT };
      return { status: 404, body: { code: "not_found" } };
    });
    renderWithProviders(<ProjectDetailPage />, { path: "/projects/:id", route: "/projects/1" });
    expect(await screen.findByText("web")).toBeInTheDocument();
    expect(await screen.findAllByText("abcdef12")).not.toHaveLength(0);

    await userEvent.click(screen.getByRole("button", { name: "Deploy" }));
    const dialog = await screen.findByRole("dialog");
    expect(within(dialog).getByText(/latest “main” of shop/)).toBeInTheDocument();
    await userEvent.click(within(dialog).getByRole("button", { name: "Deploy" }));
    const log = await screen.findByTestId("deploy-log");
    expect(log).toHaveTextContent("#1 building");
    expect(
      fetchMock.mock.calls.some(
        ([url, init]) => String(url).endsWith("/deploy") && init?.method === "POST",
      ),
    ).toBe(true);
  });

  it("redeploys an old version from its deploy", async () => {
    const fetchMock = mockFetch((url) => {
      if (url.endsWith("/projects/1/deploy"))
        return { status: 202, body: { ...DEPLOYMENT, id: 9, status: "queued" } };
      if (url.includes("/projects/1/deployments"))
        return { status: 200, body: { items: [DEPLOYMENT], total: 1, page: 1, page_size: 15 } };
      if (url.endsWith("/deployments/7"))
        return { status: 200, body: { ...DEPLOYMENT, log: "✔ Deployed.", log_size: 11 } };
      if (url.endsWith("/deployments/9"))
        return {
          status: 200,
          body: { ...DEPLOYMENT, id: 9, status: "queued", log: "", log_size: 0 },
        };
      if (url.endsWith("/projects/1/state"))
        return {
          status: 200,
          body: {
            available: false,
            error_code: "agent_unreachable",
            exists: false,
            commit_sha: null,
            commit_message: null,
          },
        };
      if (url.endsWith("/containers")) return { status: 503, body: { code: "agent_unreachable" } };
      if (url.endsWith("/projects/1")) return { status: 200, body: PROJECT };
      return { status: 404, body: { code: "not_found" } };
    });
    renderWithProviders(<ProjectDetailPage />, { path: "/projects/:id", route: "/projects/1" });
    await userEvent.click(await screen.findByTestId("deployment-7"));
    await userEvent.click(await screen.findByRole("button", { name: "Redeploy this version" }));
    const dialog = await screen.findByRole("dialog", { name: "Redeploy this version" });
    await userEvent.click(within(dialog).getByRole("button", { name: "Redeploy this version" }));
    await waitFor(() => {
      const post = fetchMock.mock.calls.find(([url]) => String(url).endsWith("/deploy"));
      expect(JSON.parse(String(post![1]!.body))).toEqual({ ref: DEPLOYMENT.commit_sha });
    });
  });
});
