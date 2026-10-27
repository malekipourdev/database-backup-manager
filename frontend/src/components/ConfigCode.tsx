import { useEffect, useMemo, useRef } from "react";

/** One coloured piece of a configuration line. */
export interface Token {
  type: "comment" | "string" | "variable" | "directive" | "section" | "number" | "punct" | "text";
  text: string;
}

const COLORS: Record<Token["type"], string | undefined> = {
  comment: "var(--mantine-color-dimmed)",
  string: "var(--mantine-color-green-4)",
  variable: "var(--mantine-color-orange-4)",
  directive: "var(--mantine-color-blue-4)",
  section: "var(--mantine-color-grape-4)",
  number: "var(--mantine-color-yellow-4)",
  punct: "var(--color-neutral-400)",
  text: undefined,
};

const VARIABLE = /^\$(\{[^}]*\}|[A-Za-z_][A-Za-z0-9_]*)/;
const NUMBER = /^\d+[a-z]?\b/;

/** Tokens of one line of nginx or Apache configuration (a light highlighter, not a parser). */
export function tokenize(line: string): Token[] {
  const out: Token[] = [];
  let i = 0;
  let first = true;
  const push = (type: Token["type"], text: string) => {
    const last = out[out.length - 1];
    if (last && last.type === type && type === "text") last.text += text;
    else out.push({ type, text });
  };
  while (i < line.length) {
    const rest = line.slice(i);
    const ch = line[i];
    if (/\s/.test(ch)) {
      push("text", ch);
      i += 1;
      continue;
    }
    if (ch === "#") {
      push("comment", rest);
      break;
    }
    if (first && ch === "<") {
      const end = rest.indexOf(">");
      const tag = end === -1 ? rest : rest.slice(0, end + 1);
      push("section", tag);
      i += tag.length;
      first = false;
      continue;
    }
    if (ch === '"' || ch === "'") {
      let end = i + 1;
      while (end < line.length && line[end] !== ch) end += line[end] === "\\" ? 2 : 1;
      const text = line.slice(i, Math.min(end + 1, line.length));
      push("string", text);
      i += text.length;
      first = false;
      continue;
    }
    if ("{};".includes(ch)) {
      push("punct", ch);
      i += 1;
      // What follows a block or a statement starts a new directive.
      first = true;
      continue;
    }
    const variable = VARIABLE.exec(rest);
    if (variable) {
      push("variable", variable[0]);
      i += variable[0].length;
      first = false;
      continue;
    }
    const word = /^[^\s{};"'$#]+/.exec(rest)?.[0] ?? ch;
    if (first) push("directive", word);
    else push(NUMBER.test(word) ? "number" : "text", word);
    i += word.length;
    first = false;
  }
  return out;
}

/** A configuration file with line numbers and colours; `line` is highlighted and shown. */
export function ConfigCode({ text, line }: { text: string; line?: number | null }) {
  const lines = useMemo(() => text.replace(/\n$/, "").split("\n"), [text]);
  const marked = useRef<HTMLDivElement>(null);
  useEffect(() => {
    marked.current?.scrollIntoView?.({ block: "center" });
  }, [line, text]);
  const width = String(lines.length).length;
  return (
    <pre
      dir="ltr"
      data-testid="config-code"
      style={{
        margin: 0,
        padding: "8px 0",
        fontFamily: "var(--font-mono)",
        fontSize: 12.5,
        lineHeight: 1.6,
        background: "var(--color-neutral-900)",
        borderRadius: 8,
        overflow: "auto",
        maxHeight: "70vh",
        textAlign: "left",
      }}
    >
      {lines.map((content, index) => {
        const number = index + 1;
        const current = number === line;
        return (
          <div
            key={number}
            ref={current ? marked : undefined}
            data-current={current || undefined}
            style={{
              display: "flex",
              background: current ? "var(--color-accent-900)" : undefined,
            }}
          >
            <span
              aria-hidden
              style={{
                flex: "none",
                width: `${width + 2}ch`,
                paddingInlineEnd: 12,
                textAlign: "right",
                color: "var(--color-neutral-600)",
                userSelect: "none",
              }}
            >
              {number}
            </span>
            <code style={{ whiteSpace: "pre", paddingInlineEnd: 12 }}>
              {tokenize(content).map((token, i) => (
                <span key={i} style={{ color: COLORS[token.type] }}>
                  {token.text}
                </span>
              ))}
            </code>
          </div>
        );
      })}
    </pre>
  );
}
