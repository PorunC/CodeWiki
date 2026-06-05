import { readFileSync } from "node:fs";
import { resolve } from "node:path";

type PackageMetadata = {
  name: string;
  version: string;
};

export const CODEWIKI_PACKAGE = readPackageMetadata();
export const CODEWIKI_VERSION = CODEWIKI_PACKAGE.version;

function readPackageMetadata(): PackageMetadata {
  const packagePath = resolve(import.meta.dirname, "../package.json");
  const raw = JSON.parse(
    readFileSync(packagePath, "utf8"),
  ) as Partial<PackageMetadata>;
  if (!raw.name || !raw.version) {
    throw new Error(`Invalid package metadata at ${packagePath}`);
  }
  return {
    name: raw.name,
    version: raw.version,
  };
}
