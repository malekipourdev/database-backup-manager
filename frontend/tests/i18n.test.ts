import { describe, expect, it } from "vitest";

import i18n from "../src/i18n";
import en from "../src/i18n/locales/en.json";
import fa from "../src/i18n/locales/fa.json";

function keys(obj: Record<string, unknown>, prefix = ""): string[] {
  return Object.entries(obj).flatMap(([key, value]) =>
    value && typeof value === "object"
      ? keys(value as Record<string, unknown>, `${prefix}${key}.`)
      : [`${prefix}${key}`],
  );
}

describe("translations", () => {
  it("fa and en have exactly the same keys", () => {
    const faKeys = new Set(keys(fa));
    const enKeys = new Set(keys(en));
    expect([...enKeys].filter((k) => !faKeys.has(k))).toEqual([]);
    expect([...faKeys].filter((k) => !enKeys.has(k))).toEqual([]);
  });

  it("has no empty values", () => {
    for (const [name, locale] of [
      ["fa", fa],
      ["en", en],
    ] as const) {
      const empty = keys(locale).filter((k) => i18n.getResource(name, "translation", k) === "");
      expect(empty).toEqual([]);
    }
  });

  it("switches document direction with the language", async () => {
    await i18n.changeLanguage("en");
    expect(document.documentElement.dir).toBe("ltr");
    expect(document.documentElement.lang).toBe("en");
    await i18n.changeLanguage("fa");
    expect(document.documentElement.dir).toBe("rtl");
    expect(document.documentElement.lang).toBe("fa");
  });
});
