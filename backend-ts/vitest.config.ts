import { defineConfig } from "vitest/config";

export default defineConfig({
  test: {
    hookTimeout: 20_000,
    testTimeout: 20_000,
  },
});
