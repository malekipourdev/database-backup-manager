import js from "@eslint/js";
import i18next from "eslint-plugin-i18next";
import reactHooks from "eslint-plugin-react-hooks";
import globals from "globals";
import tseslint from "typescript-eslint";

export default tseslint.config(
  { ignores: ["dist/", "node_modules/", "coverage/"] },
  js.configs.recommended,
  ...tseslint.configs.recommended,
  {
    files: ["**/*.cjs"],
    languageOptions: { globals: globals.node, sourceType: "commonjs" },
  },
  {
    files: ["**/*.{ts,tsx}"],
    languageOptions: { globals: globals.browser },
    plugins: { "react-hooks": reactHooks },
    rules: reactHooks.configs.recommended.rules,
  },
  {
    // All user-visible text must come from translation files (Constitution VIII).
    files: ["src/**/*.tsx"],
    plugins: { i18next },
    rules: {
      "i18next/no-literal-string": [
        "error",
        {
          mode: "jsx-only",
          // Only attributes that render text to the user; layout props are not UI text.
          "jsx-attributes": {
            include: ["label", "placeholder", "title", "alt", "aria-label", "description", "body"],
          },
          callees: {
            exclude: [
              "t",
              "i18n(ext)?",
              "getInputProps",
              "setFieldError",
              "header",
              "overrideToggle",
              "disabled",
            ],
          },
        },
      ],
    },
  },
);
