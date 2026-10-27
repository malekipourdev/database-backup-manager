import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";

import en from "../src/help/en.md?raw";
import fa from "../src/help/fa.md?raw";
import { type HelpCategory, allArticles, parseGuide, searchGuide } from "../src/help";
import { parseBlocks } from "../src/components/HelpMarkdown";
import i18n from "../src/i18n";
import { HelpPage } from "../src/pages/HelpPage";
import { renderWithProviders } from "./render";

const GUIDES: Record<string, HelpCategory[]> = { fa: parseGuide(fa), en: parseGuide(en) };
const ICONS = new Set([
  "start",
  "databases",
  "backups",
  "storage",
  "alerts",
  "servers",
  "containers",
  "projects",
  "account",
  "maintenance",
  "faq",
]);
// Panel routes an article may link to (see App.tsx).
const PAGES = [
  /^\/overview$/,
  /^\/instances(\/new)?$/,
  /^\/backups$/,
  /^\/schedules$/,
  /^\/servers$/,
  /^\/containers$/,
  /^\/webservers$/,
  /^\/projects(\/new)?$/,
  /^\/notifications$/,
  /^\/bots$/,
  /^\/settings\/backups$/,
  /^\/account$/,
];

function structure(guide: HelpCategory[]) {
  return guide.map((c) => [c.id, c.icon, c.articles.map((a) => [a.id, a.page ?? null])]);
}

describe("the guide", () => {
  it("has the same topics in both languages", () => {
    expect(structure(GUIDES.fa)).toEqual(structure(GUIDES.en));
    expect(GUIDES.fa.length).toBe(11);
    expect(allArticles(GUIDES.fa).length).toBeGreaterThan(40);
  });

  for (const [lang, guide] of Object.entries(GUIDES)) {
    it(`${lang}: every article is complete and every link leads somewhere`, () => {
      const ids = new Set(allArticles(guide).map(({ article }) => article.id));
      expect(ids.size).toBe(allArticles(guide).length);
      for (const category of guide) {
        expect(ICONS.has(category.icon), category.icon).toBe(true);
        expect(category.title).not.toBe("");
      }
      for (const { article } of allArticles(guide)) {
        expect(article.title, article.id).not.toBe("");
        expect(article.summary, article.id).not.toBe("");
        expect(parseBlocks(article.body).length, article.id).toBeGreaterThan(0);
        if (article.page)
          expect(
            PAGES.some((p) => p.test(article.page!)),
            article.page,
          ).toBe(true);
        for (const [, href] of article.body.matchAll(/\]\(([^)\s]+)\)/g)) {
          if (href.startsWith("#"))
            expect(ids.has(href.slice(1)), `${article.id} → ${href}`).toBe(true);
          else
            expect(
              PAGES.some((p) => p.test(href)),
              `${article.id} → ${href}`,
            ).toBe(true);
        }
      }
    });
  }

  it("finds articles by words in their text", () => {
    expect(searchGuide(GUIDES.en, "arvancloud")[0].article.id).toBe("arvancloud");
    expect(searchGuide(GUIDES.fa, "ابرآروان").map((r) => r.article.id)).toContain("arvancloud");
    expect(searchGuide(GUIDES.en, "zzzz-nothing")).toEqual([]);
  });
});

describe("HelpMarkdown", () => {
  it("reads the guide's Markdown subset", () => {
    const blocks = parseBlocks(
      [
        "## Title",
        "Some **bold** text",
        "on two lines.",
        "",
        "1. one",
        "2. two",
        "```bash",
        "echo hi",
        "```",
        "3. three",
        "",
        "- a",
        "  continued",
        "",
        "> ! careful",
        "",
        "| A | B |",
        "|---|---|",
        "| 1 | 2 |",
      ].join("\n"),
    );
    expect(blocks).toEqual([
      { kind: "heading", level: 2, text: "Title" },
      { kind: "paragraph", text: "Some **bold** text on two lines." },
      { kind: "list", ordered: true, start: 1, items: ["one", "two"] },
      { kind: "code", text: "echo hi" },
      { kind: "list", ordered: true, start: 3, items: ["three"] },
      { kind: "list", ordered: false, start: 1, items: ["a continued"] },
      { kind: "note", warning: true, lines: ["careful"] },
      { kind: "table", header: ["A", "B"], rows: [["1", "2"]] },
    ]);
  });
});

describe("HelpPage", () => {
  it("shows the topics, opens an article and searches", async () => {
    await i18n.changeLanguage("en");
    renderWithProviders(<HelpPage />, { path: "/help/:articleId?", route: "/help" });
    expect(await screen.findByTestId("help-category-servers")).toBeInTheDocument();
    await userEvent.click(screen.getAllByRole("link", { name: "Adding a server" })[0]);
    const article = await screen.findByTestId("help-article");
    expect(article).toHaveTextContent("The token is shown only this once.");
    expect(screen.getByRole("link", { name: "Go to this page" })).toHaveAttribute(
      "href",
      "/servers",
    );

    await userEvent.type(screen.getByRole("textbox", { name: "Search the guide" }), "object lock");
    await waitFor(() => expect(screen.queryByTestId("help-article")).toBeNull());
    // A result (title, topic and summary), besides the same title in the contents.
    expect(
      screen.getByRole("link", { name: /7-day protection of remote copies.*Why the panel/ }),
    ).toHaveAttribute("href", "/help/remote-protection");
    await i18n.changeLanguage("fa");
  });
});
