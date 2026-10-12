import { Alert, Anchor, Code, List, Table, Text, Title } from "@mantine/core";
import type { ReactNode } from "react";
import { Link } from "react-router-dom";

type Block =
  | { kind: "heading"; level: 2 | 3; text: string }
  | { kind: "paragraph"; text: string }
  | { kind: "list"; ordered: boolean; start: number; items: string[] }
  | { kind: "code"; text: string }
  | { kind: "note"; warning: boolean; lines: string[] }
  | { kind: "table"; header: string[]; rows: string[][] };

const ORDERED = /^\d+\.\s+/;

function cells(line: string): string[] {
  return line
    .trim()
    .replace(/^\||\|$/g, "")
    .split("|")
    .map((cell) => cell.trim());
}

/** The guide's Markdown subset (see src/help/types.ts) as blocks. */
export function parseBlocks(source: string): Block[] {
  const lines = source.replace(/\r/g, "").split("\n");
  const blocks: Block[] = [];
  let i = 0;
  while (i < lines.length) {
    const line = lines[i];
    const trimmed = line.trim();
    if (!trimmed) {
      i += 1;
      continue;
    }
    if (trimmed.startsWith("```")) {
      const code: string[] = [];
      i += 1;
      while (i < lines.length && !lines[i].trim().startsWith("```")) code.push(lines[i++]);
      i += 1;
      blocks.push({ kind: "code", text: code.join("\n") });
      continue;
    }
    if (trimmed.startsWith("## ") || trimmed.startsWith("### ")) {
      const level = trimmed.startsWith("### ") ? 3 : 2;
      blocks.push({ kind: "heading", level, text: trimmed.replace(/^#+\s+/, "") });
      i += 1;
      continue;
    }
    if (trimmed.startsWith("|")) {
      const rows: string[][] = [];
      while (i < lines.length && lines[i].trim().startsWith("|")) {
        const row = cells(lines[i++]);
        if (!row.every((cell) => /^:?-+:?$/.test(cell))) rows.push(row);
      }
      blocks.push({ kind: "table", header: rows[0] ?? [], rows: rows.slice(1) });
      continue;
    }
    if (trimmed.startsWith(">")) {
      const note: string[] = [];
      while (i < lines.length && lines[i].trim().startsWith(">")) {
        note.push(lines[i++].trim().replace(/^>\s?/, ""));
      }
      const warning = note[0]?.startsWith("!") ?? false;
      if (warning) note[0] = note[0].replace(/^!\s*/, "");
      blocks.push({ kind: "note", warning, lines: note.filter(Boolean) });
      continue;
    }
    if (trimmed.startsWith("- ") || ORDERED.test(trimmed)) {
      const ordered = ORDERED.test(trimmed);
      // A numbered list interrupted by a code block goes on with its numbering.
      const start = ordered ? Number(/^\d+/.exec(trimmed)?.[0] ?? 1) : 1;
      const items: string[] = [];
      while (i < lines.length) {
        const current = lines[i];
        const t = current.trim();
        if (ordered ? ORDERED.test(t) : t.startsWith("- ")) {
          items.push(t.replace(ordered ? ORDERED : /^-\s+/, ""));
        } else if (t && /^\s{2,}/.test(current) && items.length) {
          items[items.length - 1] += ` ${t}`; // continuation of the previous item
        } else {
          break;
        }
        i += 1;
      }
      blocks.push({ kind: "list", ordered, start, items });
      continue;
    }
    const paragraph: string[] = [];
    while (i < lines.length) {
      const t = lines[i].trim();
      if (!t || /^(```|#{2,3} |\||>|- )/.test(t) || ORDERED.test(t)) break;
      paragraph.push(t);
      i += 1;
    }
    blocks.push({ kind: "paragraph", text: paragraph.join(" ") });
  }
  return blocks;
}

const INLINE = /(`[^`]+`|\*\*[^*]+\*\*|\[[^\]]+\]\([^)\s]+\))/g;

function inline(text: string): ReactNode[] {
  return text.split(INLINE).map((part, index) => {
    if (!part) return null;
    if (part.startsWith("`") && part.endsWith("`") && part.length > 1) {
      return (
        <Code key={index} dir="ltr" style={{ unicodeBidi: "isolate" }}>
          {part.slice(1, -1)}
        </Code>
      );
    }
    if (part.startsWith("**") && part.endsWith("**") && part.length > 4) {
      return <strong key={index}>{part.slice(2, -2)}</strong>;
    }
    const link = /^\[([^\]]+)\]\(([^)\s]+)\)$/.exec(part);
    if (link) {
      const [, label, href] = link;
      if (href.startsWith("#")) {
        return (
          <Anchor key={index} component={Link} to={`/help/${href.slice(1)}`}>
            {label}
          </Anchor>
        );
      }
      if (href.startsWith("/")) {
        return (
          <Anchor key={index} component={Link} to={href}>
            {label}
          </Anchor>
        );
      }
      return (
        <Anchor key={index} href={href} target="_blank" rel="noopener noreferrer">
          {label}
        </Anchor>
      );
    }
    return part;
  });
}

export function HelpMarkdown({ source }: { source: string }) {
  return (
    <div className="cl-help-body">
      {parseBlocks(source).map((block, index) => {
        switch (block.kind) {
          case "heading":
            return (
              <Title key={index} order={block.level === 2 ? 4 : 5} mt="lg" mb={6}>
                {inline(block.text)}
              </Title>
            );
          case "paragraph":
            return (
              <Text key={index} mb="sm" lh={1.9}>
                {inline(block.text)}
              </Text>
            );
          case "list": {
            return (
              <List
                key={index}
                type={block.ordered ? "ordered" : "unordered"}
                start={block.ordered ? block.start : undefined}
                spacing={6}
                mb="sm"
                lh={1.8}
              >
                {block.items.map((item, itemIndex) => (
                  <List.Item key={itemIndex}>{inline(item)}</List.Item>
                ))}
              </List>
            );
          }
          case "code":
            return (
              <Code
                key={index}
                block
                dir="ltr"
                mb="sm"
                style={{ whiteSpace: "pre-wrap", wordBreak: "break-word", textAlign: "left" }}
              >
                {block.text}
              </Code>
            );
          case "note":
            return (
              <Alert key={index} color={block.warning ? "yellow" : "blue"} mb="sm" variant="light">
                {block.lines.map((noteLine, lineIndex) => (
                  <Text key={lineIndex} size="sm" lh={1.8}>
                    {inline(noteLine)}
                  </Text>
                ))}
              </Alert>
            );
          case "table":
            return (
              <Table.ScrollContainer key={index} minWidth={420} mb="sm">
                <Table withTableBorder withColumnBorders striped>
                  <Table.Thead>
                    <Table.Tr>
                      {block.header.map((cell, cellIndex) => (
                        <Table.Th key={cellIndex}>{inline(cell)}</Table.Th>
                      ))}
                    </Table.Tr>
                  </Table.Thead>
                  <Table.Tbody>
                    {block.rows.map((row, rowIndex) => (
                      <Table.Tr key={rowIndex}>
                        {row.map((cell, cellIndex) => (
                          <Table.Td key={cellIndex}>{inline(cell)}</Table.Td>
                        ))}
                      </Table.Tr>
                    ))}
                  </Table.Tbody>
                </Table>
              </Table.ScrollContainer>
            );
          default:
            return null;
        }
      })}
    </div>
  );
}
