import { AnalysisService } from "../analysis/analysisService.js";
import type { CodeWikiSettings } from "../config.js";
import type { CodeWikiStoreApi } from "../db/types.js";
import { CommunityNamingService } from "../graph/communityNamingService.js";
import { GraphRAGService } from "../graphrag/graphragService.js";
import { CachedLlmService } from "../llm/cache.js";
import { OpenAiCompatibleLlmGateway } from "../llm/gateway.js";
import { QuestionAnswerer } from "../qa/questionAnswerer.js";
import type { RepoScanner } from "../scanner/scanner.js";
import { WikiService } from "../wiki/wikiService.js";
import { RepositoryService } from "./repositoryService.js";

export type BackendServiceDependencies = {
  settings: CodeWikiSettings;
  store: CodeWikiStoreApi;
  scanner: RepoScanner;
};

export type BackendServices = {
  analysis: AnalysisService;
  communityNaming: CommunityNamingService;
  graphRag: GraphRAGService;
  llm: CachedLlmService;
  questionAnswerer: QuestionAnswerer;
  repositories: RepositoryService;
  wiki: WikiService;
};

export type BackendRuntime = BackendServiceDependencies & {
  services: BackendServices;
};

export function createBackendServices({
  settings,
  store,
  scanner,
}: BackendServiceDependencies): BackendServices {
  const llm = new CachedLlmService(
    store,
    new OpenAiCompatibleLlmGateway(settings),
  );
  return {
    analysis: new AnalysisService(store, scanner),
    communityNaming: new CommunityNamingService(store, llm),
    graphRag: new GraphRAGService(store),
    llm,
    questionAnswerer: new QuestionAnswerer(store, llm),
    repositories: new RepositoryService(store, scanner),
    wiki: new WikiService(store, llm),
  };
}

export function createBackendRuntime(
  dependencies: BackendServiceDependencies,
  services: BackendServices = createBackendServices(dependencies),
): BackendRuntime {
  return {
    ...dependencies,
    services,
  };
}
