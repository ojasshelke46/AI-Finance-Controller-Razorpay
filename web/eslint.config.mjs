import { dirname } from "path";
import { fileURLToPath } from "url";

import { FlatCompat } from "@eslint/eslintrc";
import { defineConfig, globalIgnores } from "eslint/config";

// This eslint-config-next ships LEGACY eslintrc objects ({ extends: [...] }),
// not flat-config arrays, and no "exports" map. Spreading them directly into
// a flat config threw "nextVitals is not iterable", so `npm run lint` never
// ran at all — which is why the react-hooks rules that flag an impure
// setState updater (see components/auto-refresh.tsx) never caught one.
// FlatCompat translates the legacy shape into flat config.
const compat = new FlatCompat({
  baseDirectory: dirname(fileURLToPath(import.meta.url)),
});

const eslintConfig = defineConfig([
  ...compat.extends("next/core-web-vitals", "next/typescript"),
  // Override default ignores of eslint-config-next.
  globalIgnores([
    // Default ignores of eslint-config-next:
    ".next/**",
    "out/**",
    "build/**",
    "next-env.d.ts",
  ]),
]);

export default eslintConfig;
