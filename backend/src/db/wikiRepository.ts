import type { CodeWikiSqliteDatabase } from "./sqlite.js";
import { randomUUID } from "node:crypto";
import type { DocCatalog, DocPage, JsonObject } from "../types.js";
import {
  catalogFromRow,
  isoNow,
  normalizeLanguage,
  pageFromRow,
  stringifyJson,
  type Row,
} from "./mappers.js";

export class WikiRepository {
  constructor(private readonly db: CodeWikiSqliteDatabase) {}

  saveDocCatalog(
    repoId: string,
    options: {
      title: string;
      structure: JsonObject;
      language_code?: string;
      catalog_id?: string;
    },
  ): DocCatalog {
    const catalog: DocCatalog = {
      id: options.catalog_id ?? randomUUID(),
      repo_id: repoId,
      language_code: normalizeLanguage(options.language_code),
      title: options.title,
      structure: options.structure,
      generated_at: isoNow(),
    };
    this.db
      .prepare(
        `
        INSERT INTO doc_catalog (id, repo_id, language_code, title, structure_json, generated_at)
        VALUES (@id, @repo_id, @language_code, @title, @structure_json, @generated_at)
        `,
      )
      .run({ ...catalog, structure_json: stringifyJson(catalog.structure) });
    return catalog;
  }

  getLatestDocCatalog(repoId: string, languageCode = "en"): DocCatalog | null {
    const row = this.db
      .prepare(
        `
        SELECT * FROM doc_catalog
        WHERE repo_id = ? AND language_code = ?
        ORDER BY generated_at DESC, id DESC
        LIMIT 1
        `,
      )
      .get(repoId, normalizeLanguage(languageCode)) as Row | undefined;
    return row ? catalogFromRow(row) : null;
  }

  upsertDocPage(page: DocPage): DocPage {
    this.db
      .prepare(
        `
        INSERT INTO doc_page (
          id, repo_id, language_code, slug, title, parent_slug, markdown,
          source_refs_json, graph_refs_json, status, updated_at
        )
        VALUES (
          @id, @repo_id, @language_code, @slug, @title, @parent_slug, @markdown,
          @source_refs_json, @graph_refs_json, @status, @updated_at
        )
        ON CONFLICT(repo_id, language_code, slug) DO UPDATE SET
          title = excluded.title,
          parent_slug = excluded.parent_slug,
          markdown = excluded.markdown,
          source_refs_json = excluded.source_refs_json,
          graph_refs_json = excluded.graph_refs_json,
          status = excluded.status,
          updated_at = excluded.updated_at
        `,
      )
      .run({
        ...page,
        language_code: normalizeLanguage(page.language_code),
        source_refs_json: stringifyJson(page.source_refs),
        graph_refs_json: stringifyJson(page.graph_refs),
      });
    return this.getDocPage(page.repo_id, page.slug, page.language_code) ?? page;
  }

  getDocPage(
    repoId: string,
    slug: string,
    languageCode = "en",
  ): DocPage | null {
    const row = this.db
      .prepare(
        "SELECT * FROM doc_page WHERE repo_id = ? AND language_code = ? AND slug = ?",
      )
      .get(repoId, normalizeLanguage(languageCode), slug) as Row | undefined;
    return row ? pageFromRow(row) : null;
  }

  listDocPages(repoId: string, languageCode = "en"): DocPage[] {
    return (
      this.db
        .prepare(
          "SELECT * FROM doc_page WHERE repo_id = ? AND language_code = ? ORDER BY slug",
        )
        .all(repoId, normalizeLanguage(languageCode)) as Row[]
    ).map(pageFromRow);
  }

  deleteDocPagesNotIn(
    repoId: string,
    slugs: string[],
    languageCode = "en",
  ): number {
    const normalizedLanguage = normalizeLanguage(languageCode);
    if (!slugs.length) {
      return this.db
        .prepare("DELETE FROM doc_page WHERE repo_id = ? AND language_code = ?")
        .run(repoId, normalizedLanguage).changes;
    }
    const placeholders = slugs.map(() => "?").join(", ");
    return this.db
      .prepare(
        `
        DELETE FROM doc_page
        WHERE repo_id = ? AND language_code = ? AND slug NOT IN (${placeholders})
        `,
      )
      .run(repoId, normalizedLanguage, ...slugs).changes;
  }
}
