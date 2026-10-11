import i18n from "i18next";
import { initReactI18next } from "react-i18next";

import en from "./locales/en.json";
import fa from "./locales/fa.json";

export const LANGUAGES = ["fa", "en"] as const;
export type Language = (typeof LANGUAGES)[number];

const STORAGE_KEY = "mbp.lang";
const DEFAULT_LANGUAGE: Language = "fa";

function isLanguage(value: unknown): value is Language {
  return value === "fa" || value === "en";
}

function readStoredLanguage(): Language {
  try {
    const stored = localStorage.getItem(STORAGE_KEY);
    if (isLanguage(stored)) return stored;
  } catch {
    // Storage can be unavailable (private mode, blocked site data).
  }
  return DEFAULT_LANGUAGE;
}

function storeLanguage(lang: Language): void {
  try {
    localStorage.setItem(STORAGE_KEY, lang);
  } catch {
    // Remembering the choice is a convenience only.
  }
}

export function directionOf(lang: string): "rtl" | "ltr" {
  return lang === "fa" ? "rtl" : "ltr";
}

function applyToDocument(lang: string): void {
  document.documentElement.lang = lang;
  document.documentElement.dir = directionOf(lang);
  document.title = i18n.t("common.appName");
}

void i18n.use(initReactI18next).init({
  resources: { fa: { translation: fa }, en: { translation: en } },
  lng: readStoredLanguage(),
  fallbackLng: "en",
  interpolation: { escapeValue: false },
});

applyToDocument(i18n.language);
i18n.on("languageChanged", (lng) => {
  applyToDocument(lng);
  if (isLanguage(lng)) storeLanguage(lng);
});

export function localeOf(lang: string): string {
  return lang === "fa" ? "fa-IR" : "en-US";
}

/** Formats an ISO timestamp in the selected language (Persian calendar and digits for fa). */
export function formatDateTime(iso: string, lang: string): string {
  return new Intl.DateTimeFormat(localeOf(lang), {
    dateStyle: "medium",
    timeStyle: "short",
  }).format(new Date(iso));
}

export function formatNumber(value: number, lang: string): string {
  return new Intl.NumberFormat(localeOf(lang)).format(value);
}

export default i18n;
