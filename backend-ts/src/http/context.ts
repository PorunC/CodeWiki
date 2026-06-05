import type { CodeWikiSettings } from "../config.js";
import type { CodeWikiStore } from "../db/store.js";
import type { RepoScanner } from "../scanner/scanner.js";
import type { BackendServices } from "../services/backendServices.js";

export type HttpRouteContext = {
  store: CodeWikiStore;
  scanner: RepoScanner;
  settings: CodeWikiSettings;
  services: BackendServices;
};
