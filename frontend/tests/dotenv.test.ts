import { describe, expect, it } from "vitest";

import { parseDotenv } from "../src/dotenv";

describe("parseDotenv", () => {
  it("reads the forms docker compose reads", () => {
    const text = [
      "﻿# a comment",
      "",
      "PLAIN=value  # trailing comment",
      "export EXPORTED = spaced ",
      "SINGLE='literal $HOME \\n # not a comment'",
      'DOUBLE="line1\\nline2 \\"quoted\\" # kept"',
      'MULTI="first',
      'second"',
      "EMPTY=",
      "HASH=abc#def",
      "PLAIN=again",
      "not a variable",
      "1BAD=x",
      "UNCLOSED='oops",
    ].join("\r\n");
    const { vars, skipped } = parseDotenv(text);
    expect(vars).toEqual([
      { name: "EXPORTED", value: "spaced" },
      { name: "SINGLE", value: "literal $HOME \\n # not a comment" },
      { name: "DOUBLE", value: 'line1\nline2 "quoted" # kept' },
      { name: "MULTI", value: "first\nsecond" },
      { name: "EMPTY", value: "" },
      { name: "HASH", value: "abc#def" },
      { name: "PLAIN", value: "again" },
    ]);
    expect(skipped).toEqual([12, 13, 14]);
  });
});
