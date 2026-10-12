import type { HelpArticle, HelpCategory, HelpIcon } from "./types";

export type { HelpArticle, HelpCategory, HelpIcon } from "./types";

/**
 * Reads a guide file (src/help/<lang>.md):
 *
 *   @@category <id> <icon> <title>
 *   @@article <id> [<panel page>]
 *   @title <title>
 *   @summary <one line>
 *   <body: the Markdown subset of HelpMarkdown>
 */
export function parseGuide(source: string): HelpCategory[] {
  const guide: HelpCategory[] = [];
  let article: HelpArticle | null = null;
  let body: string[] = [];
  const close = () => {
    if (article) article.body = body.join("\n").trim();
    article = null;
    body = [];
  };
  for (const line of source.replace(/\r/g, "").split("\n")) {
    if (line.startsWith("@@category ")) {
      close();
      const [, id, icon, ...title] = line.split(" ");
      guide.push({ id, icon: icon as HelpIcon, title: title.join(" "), articles: [] });
    } else if (line.startsWith("@@article ")) {
      close();
      const [, id, page] = line.split(" ");
      article = { id, title: "", summary: "", body: "", page: page || undefined };
      guide[guide.length - 1].articles.push(article);
    } else if (article && line.startsWith("@title ")) {
      article.title = line.slice(7).trim();
    } else if (article && line.startsWith("@summary ")) {
      article.summary = line.slice(9).trim();
    } else if (article) {
      body.push(line);
    }
  }
  close();
  return guide;
}

/** The guide in a language; loaded on demand, so it is not in the main bundle. */
export async function loadGuide(lang: string): Promise<HelpCategory[]> {
  const source =
    lang === "en" ? (await import("./en.md?raw")).default : (await import("./fa.md?raw")).default;
  return parseGuide(source);
}

export function allArticles(
  guide: HelpCategory[],
): { article: HelpArticle; category: HelpCategory }[] {
  return guide.flatMap((category) => category.articles.map((article) => ({ article, category })));
}

/** Plain text of an article body, for search. */
export function plainText(body: string): string {
  return body
    .replace(/```[\s\S]*?```/g, " ")
    .replace(/\[([^\]]+)\]\([^)]+\)/g, "$1")
    .replace(/[*`#>|]/g, " ");
}

/** Articles whose title, summary or text contain every word of the query; title hits first. */
export function searchGuide(guide: HelpCategory[], query: string) {
  const words = query.trim().toLowerCase().split(/\s+/).filter(Boolean);
  if (!words.length) return [];
  return allArticles(guide)
    .map(({ article, category }) => {
      const title = article.title.toLowerCase();
      const text = `${title} ${article.summary.toLowerCase()} ${plainText(article.body).toLowerCase()}`;
      if (!words.every((w) => text.includes(w))) return null;
      return { article, category, score: words.filter((w) => title.includes(w)).length };
    })
    .filter((x): x is NonNullable<typeof x> => x !== null)
    .sort((a, b) => b.score - a.score);
}
