/**
 * The in-panel guide. Each language has the same categories and articles (same ids, in the
 * same order); `body` is a small Markdown subset rendered by HelpMarkdown:
 * "## " headings, paragraphs, "- " and "1. " lists, ``` code blocks, "> " notes ("> !" for a
 * warning), "|" tables, **bold**, `code` and [links](/page or #article-id).
 */
export type HelpIcon =
  | "start"
  | "databases"
  | "backups"
  | "storage"
  | "alerts"
  | "servers"
  | "containers"
  | "projects"
  | "account"
  | "maintenance"
  | "faq";

export interface HelpArticle {
  id: string;
  title: string;
  /** One line under the title, also shown in lists and search results. */
  summary: string;
  body: string;
  /** The panel page this article is about, opened by its button. */
  page?: string;
}

export interface HelpCategory {
  id: string;
  icon: HelpIcon;
  title: string;
  articles: HelpArticle[];
}
