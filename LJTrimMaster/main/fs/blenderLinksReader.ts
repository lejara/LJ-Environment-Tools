import { readdir, readFile } from "node:fs/promises";
import { join } from "node:path";
import {
  BLENDER_LINKS_SCHEMA_VERSION,
  type SerializedBlenderLink,
} from "@shared/types";

/**
 * Reads the link files the Blender addon writes into `<root>/blender_links/`.
 *
 * One JSON per `.blend`, named `<stem>-<hash-of-full-path>.json` so two files
 * sharing a stem in different folders don't collide. Contents are one entry per
 * assigned material slot.
 *
 * **The tool treats these as read-only and possibly stale.** The `.blend` may
 * have been moved or deleted since it was written, and nothing here checks — the
 * files exist so the tool can warn before a destructive edit ("3 Blender meshes
 * are unwrapped against this trim"), which is useful even when one of the three
 * has since been deleted. Warn, never block, and never act on them.
 *
 * A malformed or future-schema file is skipped with a warning rather than
 * failing the refresh: the links are advisory, so losing one costs a warning,
 * not the project.
 */
export class BlenderLinksReader {
  static readonly DIR = "blender_links";

  static dirPath(root: string): string {
    return join(root, BlenderLinksReader.DIR);
  }

  async read(
    root: string,
  ): Promise<{ links: SerializedBlenderLink[]; warnings: string[] }> {
    const dir = BlenderLinksReader.dirPath(root);
    const warnings: string[] = [];

    let names: string[];
    try {
      names = await readdir(dir);
    } catch {
      // No addon has ever run against this project. Not a problem.
      return { links: [], warnings };
    }

    const links: SerializedBlenderLink[] = [];
    for (const name of names.filter((n) => n.toLowerCase().endsWith(".json"))) {
      try {
        const raw = JSON.parse(await readFile(join(dir, name), "utf-8")) as unknown;
        links.push(...BlenderLinksReader.parseFile(raw, name, warnings));
      } catch (err) {
        warnings.push(`${BlenderLinksReader.DIR}/${name}: ${String(err)}`);
      }
    }
    return { links, warnings };
  }

  private static parseFile(
    raw: unknown,
    name: string,
    warnings: string[],
  ): SerializedBlenderLink[] {
    if (typeof raw !== "object" || raw === null) {
      warnings.push(`${BlenderLinksReader.DIR}/${name} is not an object.`);
      return [];
    }
    const file = raw as Record<string, unknown>;
    const version = Number(file.schemaVersion);
    if (!Number.isFinite(version) || version > BLENDER_LINKS_SCHEMA_VERSION) {
      warnings.push(
        `${BlenderLinksReader.DIR}/${name} is schema ${String(file.schemaVersion)}; this tool reads ${BLENDER_LINKS_SCHEMA_VERSION}. Skipped.`,
      );
      return [];
    }

    const blendPath = typeof file.blendPath === "string" ? file.blendPath : "";
    const entries = Array.isArray(file.links) ? file.links : [];

    return entries.flatMap((entry): SerializedBlenderLink[] => {
      if (typeof entry !== "object" || entry === null) return [];
      const link = entry as Record<string, unknown>;
      const trimId = typeof link.trimId === "string" ? link.trimId : "";
      if (!trimId) return [];
      return [
        {
          blendPath,
          objectName: String(link.objectName ?? ""),
          meshName: String(link.meshName ?? ""),
          slotIndex: Number(link.slotIndex ?? 0),
          materialName: String(link.materialName ?? ""),
          trimId,
          assetBaseName: String(link.assetBaseName ?? ""),
          sheetId: typeof link.sheetId === "string" ? link.sheetId : null,
          sheetName: typeof link.sheetName === "string" ? link.sheetName : null,
          resolved: link.resolved === true,
          hidden: link.hidden === true,
        },
      ];
    });
  }
}
