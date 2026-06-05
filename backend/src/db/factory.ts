import { databaseProviderFromUrl, sqlitePathFromUrl } from "../config.js";
import { PgCodeWikiStore } from "./pgStore.js";
import { CodeWikiStore } from "./store.js";
import type { CodeWikiStoreApi } from "./types.js";

export function createCodeWikiStore(databaseUrl: string): CodeWikiStoreApi {
  const provider = databaseProviderFromUrl(databaseUrl);
  if (provider === "postgresql") {
    return new PgCodeWikiStore(databaseUrl);
  }
  return new CodeWikiStore(sqlitePathFromUrl(databaseUrl));
}
