import {
  type CSSVariablesResolver,
  type MantineColorsTuple,
  type VariantColorsResolver,
  createTheme,
  defaultVariantColorsResolver,
  parseThemeColor,
} from "@mantine/core";

/** Accent ramp of the "Cloud" design (index 4 is the accent). */
const accent: MantineColorsTuple = [
  "#f5f4ff",
  "#e7e5fe",
  "#d2cefd",
  "#b5abfc",
  "#9184d9",
  "#796cbf",
  "#5d5294",
  "#423a6a",
  "#2b2741",
  "#1f1c30",
];

/** Mantine's dark scale on the design's neutrals: 7 is the page, 6 the surface. */
const dark: MantineColorsTuple = [
  "#e9e9ed",
  "#cfd3e5",
  "#b2b6ca",
  "#9397ab",
  "#595d6c",
  "#3f424d",
  "#232532",
  "#161826",
  "#12131f",
  "#0d0e17",
];

/** Tag colors (background, text) per hue, as in the design. */
const STATUS: Record<string, { bg: string; fg: string; solid: string }> = {
  green: { bg: "oklch(0.32 0.06 160)", fg: "oklch(0.88 0.1 160)", solid: "oklch(0.78 0.13 160)" },
  teal: { bg: "oklch(0.32 0.06 180)", fg: "oklch(0.88 0.1 180)", solid: "oklch(0.78 0.11 180)" },
  red: { bg: "oklch(0.32 0.07 25)", fg: "oklch(0.86 0.09 25)", solid: "oklch(0.7 0.15 25)" },
  orange: { bg: "oklch(0.34 0.06 60)", fg: "oklch(0.88 0.1 70)", solid: "oklch(0.78 0.13 60)" },
  yellow: { bg: "oklch(0.34 0.06 80)", fg: "oklch(0.9 0.1 85)", solid: "oklch(0.8 0.13 80)" },
  blue: { bg: "#2b2741", fg: "#d2cefd", solid: "#9184d9" },
  indigo: { bg: "#2b2741", fg: "#d2cefd", solid: "#9184d9" },
  violet: { bg: "#2b2741", fg: "#d2cefd", solid: "#9184d9" },
  accent: { bg: "#2b2741", fg: "#d2cefd", solid: "#9184d9" },
  gray: { bg: "#3f424d", fg: "#f3f5fe", solid: "#9397ab" },
};

const mix = (color: string, percent: number) =>
  `color-mix(in srgb, ${color} ${percent}%, transparent)`;

/**
 * Buttons are outlined, never solid: "filled" draws the accent (or status) outline,
 * "light" a tinted tag, "subtle" a text button; badges use the tinted tag style.
 */
const variantColorResolver: VariantColorsResolver = (input) => {
  const parsed = parseThemeColor({
    color: input.color || input.theme.primaryColor,
    theme: input.theme,
  });
  const name = parsed.isThemeColor ? parsed.color : "accent";
  const status = STATUS[name] ?? STATUS.accent;
  const solid = status.solid;

  if (input.variant === "filled") {
    return {
      background: "transparent",
      hover: mix(solid, 12),
      color: name === "accent" ? "var(--color-accent)" : solid,
      border: `1px solid ${solid}`,
    };
  }
  if (input.variant === "light") {
    return {
      background: status.bg,
      hover: mix(solid, 22),
      color: status.fg,
      border: "1px solid transparent",
    };
  }
  if (input.variant === "subtle") {
    return {
      background: "transparent",
      hover: mix(solid, 10),
      color: name === "accent" ? "var(--color-accent)" : solid,
      border: "1px solid transparent",
    };
  }
  if (input.variant === "outline") {
    return {
      background: "transparent",
      hover: mix(solid, 10),
      color: status.fg,
      border: `1px solid ${solid}`,
    };
  }
  return defaultVariantColorsResolver(input);
};

export const theme = createTheme({
  fontFamily: "Inter, Vazirmatn, system-ui, sans-serif",
  fontFamilyMonospace: "ui-monospace, Menlo, monospace",
  headings: { fontFamily: "Inter, Vazirmatn, system-ui, sans-serif", fontWeight: "500" },
  primaryColor: "accent",
  primaryShade: { light: 4, dark: 4 },
  colors: { accent, dark },
  defaultRadius: "md",
  radius: { xs: "4px", sm: "6px", md: "8px", lg: "14px", xl: "18px" },
  cursorType: "pointer",
  variantColorResolver,
  components: {
    // Explicit variants make Mantine run variantColorResolver (it is skipped without one).
    Button: { defaultProps: { variant: "filled" } },
    ActionIcon: { defaultProps: { variant: "subtle" } },
    Badge: { defaultProps: { variant: "light" } },
    Paper: { defaultProps: { radius: "lg" } },
    Card: { defaultProps: { radius: "lg" } },
    Switch: { defaultProps: { color: "accent" } },
    Checkbox: { defaultProps: { color: "accent" } },
    Loader: { defaultProps: { color: "accent", type: "dots" } },
  },
});

/** The page background behind everything; Mantine reads it for body. */
export const cssVariablesResolver: CSSVariablesResolver = () => ({
  variables: {},
  light: {},
  dark: {
    "--mantine-color-body": "#161826",
  },
});
