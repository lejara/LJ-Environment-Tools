import { readFile, writeFile, mkdir, access, rename, unlink } from "node:fs/promises";
import { randomUUID } from "node:crypto";
import { join } from "node:path";
import {
  PROJECT_DATA_VERSION,
  type OpenProjectResult,
  type SerializedProjectData,
} from "@shared/types";

/**
 * Project scaffolding and projectData.json I/O.
 *
 * The folder layout is fixed by the spec:
 *   /root
 *     projectData.json
 *     /image_dump        source textures the user unwraps against
 *     /placeholder slots
 *     /output            everything the exporter writes
 */
export class ProjectFs {
  static readonly DATA_FILE = "projectData.json";
  static readonly IMAGE_DUMP = "image_dump";
  static readonly PLACEHOLDER_SLOTS = "placeholder slots";
  static readonly OUTPUT = "output";

  static imageDumpPath(root: string): string {
    return join(root, ProjectFs.IMAGE_DUMP);
  }

  static outputPath(root: string): string {
    return join(root, ProjectFs.OUTPUT);
  }

  static dataPath(root: string): string {
    return join(root, ProjectFs.DATA_FILE);
  }

  /** Scaffolds a new project folder. Refuses to clobber an existing project. */
  async create(rootPath: string): Promise<OpenProjectResult> {
    if (await this.isProject(rootPath)) {
      throw new Error(
        `"${rootPath}" already contains a ${ProjectFs.DATA_FILE}.`,
      );
    }

    await mkdir(rootPath, { recursive: true });
    await Promise.all([
      mkdir(ProjectFs.imageDumpPath(rootPath), { recursive: true }),
      mkdir(join(rootPath, ProjectFs.PLACEHOLDER_SLOTS), { recursive: true }),
      mkdir(ProjectFs.outputPath(rootPath), { recursive: true }),
    ]);

    const data: SerializedProjectData = {
      version: PROJECT_DATA_VERSION,
      defaults: { defaultTrimResolution: { width: 2048, height: 2048 } },
      sheets: [],
    };
    await this.write(rootPath, data);
    return { rootPath, data };
  }

  async open(rootPath: string): Promise<OpenProjectResult> {
    let raw: string;
    try {
      raw = await readFile(ProjectFs.dataPath(rootPath), "utf-8");
    } catch {
      throw new Error(`No ${ProjectFs.DATA_FILE} found in "${rootPath}".`);
    }

    let data: SerializedProjectData;
    try {
      data = JSON.parse(raw) as SerializedProjectData;
    } catch (err) {
      throw new Error(`${ProjectFs.DATA_FILE} is corrupt: ${String(err)}`);
    }

    // Ensure the folders exist even if the project was opened from a copy that
    // dropped empty directories (git does this).
    await Promise.all([
      mkdir(ProjectFs.imageDumpPath(rootPath), { recursive: true }),
      mkdir(join(rootPath, ProjectFs.PLACEHOLDER_SLOTS), { recursive: true }),
      mkdir(ProjectFs.outputPath(rootPath), { recursive: true }),
    ]);

    return { rootPath, data: this.migrate(data) };
  }

  /** One write at a time per project root — see `write`. */
  private readonly writeQueues = new Map<string, Promise<void>>();

  /**
   * Writes projectData.json atomically: temp file, then rename over the target.
   *
   * The Blender addon reads this file, and the tool autosaves 800 ms after every
   * edit — with a plain writeFile the addon can read a half-written file
   * mid-export and either fail to parse or, worse, resolve a truncated sheet
   * list. A same-directory temp keeps the rename on one filesystem, where it is
   * atomic.
   *
   * Two things make that reliable on Windows, both verified against concurrent
   * readers rather than assumed:
   *
   * 1. **Writes are serialized per root.** Two renames racing for the same
   *    destination is an EPERM waiting to happen, and there is no reason for the
   *    tool to have two saves in flight.
   * 2. **The rename is retried.** A reader holding the destination open makes
   *    `MoveFileEx` fail with EPERM for as long as that handle lives — a few
   *    milliseconds. Retrying is the standard fix; the alternative is losing a
   *    save because the addon happened to be reading.
   */
  async write(rootPath: string, data: SerializedProjectData): Promise<void> {
    const previous = this.writeQueues.get(rootPath) ?? Promise.resolve();
    const next = previous
      .catch(() => undefined)
      .then(() => ProjectFs.writeNow(rootPath, data));
    this.writeQueues.set(rootPath, next);
    try {
      await next;
    } finally {
      if (this.writeQueues.get(rootPath) === next) {
        this.writeQueues.delete(rootPath);
      }
    }
  }

  private static async writeNow(
    rootPath: string,
    data: SerializedProjectData,
  ): Promise<void> {
    const target = ProjectFs.dataPath(rootPath);
    const json = JSON.stringify(data, null, 2);
    const temp = `${target}.${process.pid}.${Date.now()}.tmp`;

    await writeFile(temp, json, "utf-8");
    try {
      await ProjectFs.renameWithRetry(temp, target);
    } catch (err) {
      await unlink(temp).catch(() => undefined);
      // The autosave swallows rejections, so throwing here would lose the
      // user's edit silently. A non-atomic write is the lesser evil: the worst
      // case is one torn read, which the addon already recovers from by keeping
      // its previous snapshot and retrying.
      console.warn(
        `[ProjectFs] atomic write failed (${String(err)}); falling back to a direct write.`,
      );
      await writeFile(target, json, "utf-8");
    }
  }

  /** Windows holds the destination open for a few ms after a reader closes. */
  private static async renameWithRetry(
    temp: string,
    target: string,
  ): Promise<void> {
    let delay = 4;
    for (let attempt = 0; ; attempt += 1) {
      try {
        await rename(temp, target);
        return;
      } catch (err) {
        const code = (err as NodeJS.ErrnoException).code;
        if (attempt >= 6 || (code !== "EPERM" && code !== "EACCES" && code !== "EBUSY")) {
          throw err;
        }
        await new Promise((resolve) => setTimeout(resolve, delay));
        delay *= 2;
      }
    }
  }

  async isProject(rootPath: string): Promise<boolean> {
    try {
      await access(ProjectFs.dataPath(rootPath));
      return true;
    } catch {
      return false;
    }
  }

  /**
   * Brings older projectData.json shapes up to the current version.
   * No shape migrations to run yet — this is the seam for when that changes.
   */
  private migrate(data: SerializedProjectData): SerializedProjectData {
    if (data.version !== PROJECT_DATA_VERSION) {
      console.warn(
        `[ProjectFs] project is version ${data.version}, tool expects ${PROJECT_DATA_VERSION}. Loading as-is.`,
      );
    }
    const sheets = Array.isArray(data.sheets) ? data.sheets : [];
    const migrated: SerializedProjectData = {
      version: PROJECT_DATA_VERSION,
      defaults: data.defaults ?? {
        defaultTrimResolution: { width: 2048, height: 2048 },
      },
      sheets: ProjectFs.enforceUniqueTrimIds(sheets),
    };
    // The cached maps.yaml vocabulary. Carried through untouched — the editor
    // re-stamps it on the next refresh, and dropping it here would blind the
    // Blender addon until then.
    if (data.maps) migrated.maps = data.maps;
    return migrated;
  }

  /**
   * Re-mints any trim id that appears twice in the project.
   *
   * `crypto.randomUUID` is unique in practice, so this never fires from normal
   * use — but a duplicated sheet block or a hand-edited file would collide, and
   * `trim_id` is the Blender addon's ONLY resolution key. A duplicate makes the
   * lookup ambiguous, and the addon would silently transform a slot against the
   * wrong sheet. Cheaper to guarantee uniqueness at the one point of entry.
   *
   * The first occurrence keeps its id, so an already-linked mesh is unaffected;
   * only the copy is re-minted, which shows up as a Missing trim link in Blender
   * rather than as wrong UVs.
   */
  private static enforceUniqueTrimIds(
    sheets: SerializedProjectData["sheets"],
  ): SerializedProjectData["sheets"] {
    const seen = new Set<string>();
    let collisions = 0;

    for (const sheet of sheets) {
      if (!Array.isArray(sheet?.items)) continue;
      for (const item of sheet.items) {
        if (!item) continue;
        if (!item.id || seen.has(item.id)) {
          item.id = randomUUID();
          collisions += 1;
        }
        seen.add(item.id);
      }
    }

    if (collisions > 0) {
      console.warn(
        `[ProjectFs] re-minted ${collisions} duplicate or missing trim id(s). Any Blender mesh linked to a re-minted trim will report a missing trim link.`,
      );
    }
    return sheets;
  }
}
