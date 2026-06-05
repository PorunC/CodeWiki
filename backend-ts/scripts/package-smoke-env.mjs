export function packageSmokeProcessEnv(baseEnv, npmCacheDir) {
  if (!npmCacheDir) {
    throw new Error("Package smoke npm cache directory is required.");
  }
  return {
    ...baseEnv,
    NPM_CONFIG_CACHE: npmCacheDir,
  };
}
