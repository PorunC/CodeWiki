import type { CodeWikiSettings } from "../config.js";
import type { CodeWikiStoreApi } from "../db/types.js";
import type { RepoScanner } from "../scanner/scanner.js";
import type { BackendServices } from "../services/backendServices.js";

export type HttpRouteContext = {
  store: CodeWikiStoreApi;
  scanner: RepoScanner;
  settings: CodeWikiSettings;
  services: BackendServices;
};
