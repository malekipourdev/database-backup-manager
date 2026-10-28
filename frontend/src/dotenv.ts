/** A .env file read the way docker compose reads it, for filling a project's variables. */

export interface DotenvResult {
  vars: { name: string; value: string }[];
  /** Line numbers (1-based) that are not a variable, comments and blank lines aside. */
  skipped: number[];
}

const NAME = /^[A-Za-z_][A-Za-z0-9_]*$/;
const ESCAPES: Record<string, string> = { n: "\n", r: "\r", t: "\t", "\\": "\\", '"': '"', $: "$" };

/**
 * KEY=value lines; `export KEY=value`; '...' literal; "..." with \n \t \" \\ escapes, which may
 * span lines; unquoted values end at " #" (a comment) and are trimmed. A later line wins.
 */
export function parseDotenv(text: string): DotenvResult {
  const lines = text
    .replace(/^\uFEFF/, "")
    .replace(/\r\n?/g, "\n")
    .split("\n");
  const found = new Map<string, string>();
  const skipped: number[] = [];
  for (let i = 0; i < lines.length; i++) {
    const number = i + 1;
    const line = lines[i].trim();
    if (!line || line.startsWith("#")) continue;
    const eq = line.indexOf("=");
    if (eq < 1) {
      skipped.push(number);
      continue;
    }
    const name = line
      .slice(0, eq)
      .trim()
      .replace(/^export\s+/, "");
    if (!NAME.test(name)) {
      skipped.push(number);
      continue;
    }
    let rest = line.slice(eq + 1).trimStart();
    let value: string;
    if (rest.startsWith("'")) {
      const end = rest.indexOf("'", 1);
      if (end === -1) {
        skipped.push(number);
        continue;
      }
      value = rest.slice(1, end);
    } else if (rest.startsWith('"')) {
      // May continue on the following lines until the closing quote.
      let buf = "";
      let closed = false;
      rest = rest.slice(1);
      for (;;) {
        let j = 0;
        while (j < rest.length) {
          const ch = rest[j];
          if (ch === "\\" && j + 1 < rest.length) {
            const next = rest[j + 1];
            buf += ESCAPES[next] ?? `\\${next}`;
            j += 2;
          } else if (ch === '"') {
            closed = true;
            break;
          } else {
            buf += ch;
            j += 1;
          }
        }
        if (closed || i + 1 >= lines.length) break;
        buf += "\n";
        i += 1;
        rest = lines[i];
      }
      if (!closed) {
        skipped.push(number);
        continue;
      }
      value = buf;
    } else {
      const comment = rest.search(/\s#/);
      value = (comment === -1 ? rest : rest.slice(0, comment)).trim();
    }
    found.delete(name); // keep the file's order, with the last value
    found.set(name, value);
  }
  return { vars: [...found].map(([name, value]) => ({ name, value })), skipped };
}
