import { SegmentedControl } from "@mantine/core";
import { useTranslation } from "react-i18next";

import { LANGUAGES } from "../i18n";

export function LanguageSwitcher() {
  const { t, i18n } = useTranslation();
  return (
    <SegmentedControl
      size="xs"
      aria-label={t("language.label")}
      value={i18n.language}
      onChange={(lang) => void i18n.changeLanguage(lang)}
      data={LANGUAGES.map((lang) => ({ value: lang, label: t(`language.${lang}`) }))}
    />
  );
}
