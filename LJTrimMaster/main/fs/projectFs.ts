import { readFile, writeFile, mkdir, access } from "node:fs/promises";
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

  async write(rootPath: string, data: SerializedProjectData): Promise<void> {
    await writeFile(
      ProjectFs.dataPath(rootPath),
      JSON.stringify(data, null, 2),
      "utf-8",
    );
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
   * No migrations to run yet — this is the seam for when the shape changes.
   */
  private migrate(data: SerializedProjectData): SerializedProjectData {
    if (data.version !== PROJECT_DATA_VERSION) {
      console.warn(
        `[ProjectFs] project is version ${data.version}, tool expects ${PROJECT_DATA_VERSION}. Loading as-is.`,
      );
    }
    return {
      version: PROJECT_DATA_VERSION,
      defaults: data.defaults ?? {
        defaultTrimResolution: { width: 2048, height: 2048 },
      },
      sheets: Array.isArray(data.sheets) ? data.sheets : [],
    };
  }
}
