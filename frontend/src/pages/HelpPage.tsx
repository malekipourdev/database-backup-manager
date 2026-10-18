import {
  Alert,
  Anchor,
  Badge,
  Button,
  Group,
  Loader,
  NavLink,
  Paper,
  Stack,
  Text,
  TextInput,
  Title,
} from "@mantine/core";
import { useQuery } from "@tanstack/react-query";
import type { Icon as PhosphorIcon } from "@phosphor-icons/react";
import { useEffect, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import { Link, useParams } from "react-router-dom";

import { type HelpCategory, type HelpIcon, allArticles, loadGuide, searchGuide } from "../help";
import { HelpMarkdown } from "../components/HelpMarkdown";
import {
  Archive,
  ArrowLeft,
  ArrowRight,
  Bell,
  BookOpen,
  Cloud,
  Cube,
  Database,
  Flag,
  HardDrives,
  MagnifyingGlass,
  Question,
  RocketLaunch,
  ShieldCheck,
  Wrench,
} from "../components/Icons";
import { PageHeader } from "../components/PageHeader";
import { formatNumber } from "../i18n";

const ICONS: Record<HelpIcon, PhosphorIcon> = {
  start: Flag,
  databases: Database,
  backups: Archive,
  storage: Cloud,
  alerts: Bell,
  servers: HardDrives,
  containers: Cube,
  projects: RocketLaunch,
  account: ShieldCheck,
  maintenance: Wrench,
  faq: Question,
};

function useGuide() {
  const { i18n } = useTranslation();
  return useQuery({
    queryKey: ["guide", i18n.language],
    queryFn: () => loadGuide(i18n.language),
    staleTime: Infinity,
  });
}

function Contents({ guide, current }: { guide: HelpCategory[]; current: string | undefined }) {
  return (
    <Stack gap={2}>
      {guide.map((category) => {
        const Icon = ICONS[category.icon];
        const open = category.articles.some((a) => a.id === current);
        return (
          <NavLink
            key={category.id}
            label={category.title}
            leftSection={<Icon size={16} />}
            defaultOpened={open}
            childrenOffset={22}
          >
            {category.articles.map((article) => (
              <NavLink
                key={article.id}
                component={Link}
                to={`/help/${article.id}`}
                label={article.title}
                active={article.id === current}
              />
            ))}
          </NavLink>
        );
      })}
    </Stack>
  );
}

function Home({ guide }: { guide: HelpCategory[] }) {
  const { t, i18n } = useTranslation();
  return (
    <div
      style={{
        display: "grid",
        gridTemplateColumns: "repeat(auto-fill, minmax(260px, 1fr))",
        gap: 12,
      }}
    >
      {guide.map((category) => {
        const Icon = ICONS[category.icon];
        return (
          <Paper key={category.id} withBorder p="md" data-testid={`help-category-${category.id}`}>
            <Group gap="sm" mb="sm" wrap="nowrap">
              <span className="cl-icon-tile">
                <Icon size={20} />
              </span>
              <div>
                <Text fw={600}>{category.title}</Text>
                <Text size="xs" c="dimmed">
                  {t("help.articles", {
                    count: category.articles.length,
                    n: formatNumber(category.articles.length, i18n.language),
                  })}
                </Text>
              </div>
            </Group>
            <Stack gap={4}>
              {category.articles.map((article) => (
                <Anchor key={article.id} component={Link} to={`/help/${article.id}`} size="sm">
                  {article.title}
                </Anchor>
              ))}
            </Stack>
          </Paper>
        );
      })}
    </div>
  );
}

function Results({ guide, query }: { guide: HelpCategory[]; query: string }) {
  const { t, i18n } = useTranslation();
  const results = searchGuide(guide, query);
  if (!results.length) {
    return (
      <Paper withBorder p="lg">
        <Text c="dimmed">{t("help.noResults", { query })}</Text>
      </Paper>
    );
  }
  return (
    <Stack gap="xs">
      <Text size="sm" c="dimmed">
        {t("help.results", { n: formatNumber(results.length, i18n.language) })}
      </Text>
      {results.map(({ article, category }) => (
        <Paper
          key={article.id}
          withBorder
          p="md"
          component={Link}
          to={`/help/${article.id}`}
          className="cl-help-result"
        >
          <Group gap="xs" mb={4}>
            <Text fw={600}>{article.title}</Text>
            <Badge variant="light" color="gray">
              {category.title}
            </Badge>
          </Group>
          <Text size="sm" c="dimmed">
            {article.summary}
          </Text>
        </Paper>
      ))}
    </Stack>
  );
}

function Article({ guide, id }: { guide: HelpCategory[]; id: string }) {
  const { t, i18n } = useTranslation();
  const flat = allArticles(guide);
  const index = flat.findIndex((x) => x.article.id === id);
  if (index < 0) {
    return (
      <Alert color="yellow">
        {t("help.notFound")}{" "}
        <Anchor component={Link} to="/help">
          {t("help.allTopics")}
        </Anchor>
      </Alert>
    );
  }
  const { article, category } = flat[index];
  const prev = flat[index - 1]?.article;
  const next = flat[index + 1]?.article;
  const rtl = i18n.dir(i18n.language) === "rtl";
  const Back = rtl ? ArrowRight : ArrowLeft;
  const Forward = rtl ? ArrowLeft : ArrowRight;
  return (
    <Paper withBorder p="lg" data-testid="help-article">
      <Group gap={6} mb="xs">
        <Anchor component={Link} to="/help" size="sm">
          {t("help.title")}
        </Anchor>
        <Text size="sm" c="dimmed">
          /
        </Text>
        <Text size="sm" c="dimmed">
          {category.title}
        </Text>
      </Group>
      <Group justify="space-between" align="flex-start" mb="xs">
        <Title order={2} size="h3">
          {article.title}
        </Title>
        {article.page && (
          <Button component={Link} to={article.page} variant="light" size="xs">
            {t("help.openPage")}
          </Button>
        )}
      </Group>
      <Text c="dimmed" mb="md">
        {article.summary}
      </Text>
      <HelpMarkdown source={article.body} />
      <Group
        justify="space-between"
        mt="xl"
        pt="md"
        style={{ borderTop: "1px solid var(--mantine-color-default-border)" }}
      >
        {prev ? (
          <Button
            variant="subtle"
            component={Link}
            to={`/help/${prev.id}`}
            leftSection={<Back size={14} />}
          >
            {prev.title}
          </Button>
        ) : (
          <span />
        )}
        {next && (
          <Button
            variant="subtle"
            component={Link}
            to={`/help/${next.id}`}
            rightSection={<Forward size={14} />}
          >
            {next.title}
          </Button>
        )}
      </Group>
    </Paper>
  );
}

export function HelpPage() {
  const { t, i18n } = useTranslation();
  const { articleId } = useParams();
  const guide = useGuide();
  const [query, setQuery] = useState("");

  // Opening an article (from a link or the contents) shows it instead of search results.
  useEffect(() => {
    setQuery("");
    window.scrollTo?.({ top: 0 });
  }, [articleId]);

  const count = useMemo(() => (guide.data ? allArticles(guide.data).length : 0), [guide.data]);

  return (
    <Stack gap={18}>
      <PageHeader
        title={t("help.title")}
        subtitle={t("help.subtitle", { n: formatNumber(count, i18n.language) })}
      />
      {guide.isPending && <Loader />}
      {guide.isError && <Alert color="red">{t("help.loadFailed")}</Alert>}
      {guide.data && (
        <div className="cl-help-layout" data-article={articleId ? "yes" : "no"}>
          <aside className="cl-help-aside">
            <Stack gap="sm">
              <TextInput
                placeholder={t("help.search")}
                aria-label={t("help.search")}
                leftSection={<MagnifyingGlass size={16} />}
                value={query}
                onChange={(e) => setQuery(e.currentTarget.value)}
              />
              <div className="cl-help-contents">
                <Contents guide={guide.data} current={articleId} />
              </div>
            </Stack>
          </aside>
          <main style={{ minWidth: 0 }}>
            {query.trim() ? (
              <Results guide={guide.data} query={query} />
            ) : articleId ? (
              <Article guide={guide.data} id={articleId} />
            ) : (
              <Stack gap="md">
                <Group gap="sm">
                  <BookOpen size={20} />
                  <Text>{t("help.intro")}</Text>
                </Group>
                <Home guide={guide.data} />
              </Stack>
            )}
          </main>
        </div>
      )}
    </Stack>
  );
}
