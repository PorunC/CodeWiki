import { databaseProviderFromUrl, sqlitePathFromUrl } from "../config.js";
import { PgCodeWikiStore } from "./pgStore.js";
import { CodeWikiStore } from "./store.js";
import type { CodeWikiStoreApi } from "./types.js";

export function createCodeWikiStore(databaseUrl: string): CodeWikiStoreApi {
  const provider = databaseProviderFromUrl(databaseUrl);
  if (provider === "postgresql") {
    return new PgCodeWikiStore(databaseUrl);
  }
  return asyncStore(new CodeWikiStore(sqlitePathFromUrl(databaseUrl)));
}

function asyncStore(store: CodeWikiStore): CodeWikiStoreApi {
  return new Proxy(store, {
    get(target, property, receiver) {
      const value = Reflect.get(target, property, receiver) as unknown;
      if (typeof value !== "function") {
        return value;
      }
      return (...args: unknown[]) => Promise.resolve(value.apply(target, args));
    },
  }) as unknown as CodeWikiStoreApi;
}
