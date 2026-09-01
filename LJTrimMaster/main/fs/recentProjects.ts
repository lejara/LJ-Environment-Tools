import { app } from 'electron'
import { readFile, writeFile, mkdir, access } from 'node:fs/promises'
import { dirname, join } from 'node:path'

const MAX_ENTRIES = 12

/**
 * The Startup screen's "Open Recent" list.
 *
 * Stored in the user-scoped config dir, NOT in any project — a project folder
 * that gets copied or committed shouldn't carry one machine's history with it.
 */
export class RecentProjects {
  private paths: string[] = []

  private get file(): string {
    return join(app.getPath('userData'), 'recent-projects.json')
  }

  async load(): Promise<string[]> {
    try {
      const parsed = JSON.parse(await readFile(this.file, 'utf-8')) as unknown
      this.paths = Array.isArray(parsed)
        ? parsed.filter((entry): entry is string => typeof entry === 'string')
        : []
    } catch {
      // No history yet, or it was hand-edited into nonsense. Either way: empty.
      this.paths = []
    }
    return this.list()
  }

  /** Recents, newest first, with folders that no longer exist filtered out. */
  async listExisting(): Promise<string[]> {
    await this.load()
    const checks = await Promise.all(
      this.paths.map(async (path) => ((await this.exists(path)) ? path : null))
    )
    const alive = checks.filter((path): path is string => path !== null)
    if (alive.length !== this.paths.length) {
      this.paths = alive
      await this.save()
    }
    return alive
  }

  list(): string[] {
    return [...this.paths]
  }

  /** Moves an existing entry to the front rather than duplicating it. */
  async add(path: string): Promise<void> {
    this.paths = [path, ...this.paths.filter((entry) => entry !== path)].slice(0, MAX_ENTRIES)
    await this.save()
  }

  async remove(path: string): Promise<void> {
    this.paths = this.paths.filter((entry) => entry !== path)
    await this.save()
  }

  async save(): Promise<void> {
    try {
      await mkdir(dirname(this.file), { recursive: true })
      await writeFile(this.file, JSON.stringify(this.paths, null, 2), 'utf-8')
    } catch (err) {
      // Losing the recents list is a nuisance, not a failure worth surfacing.
      console.error('[RecentProjects] could not save:', err)
    }
  }

  private async exists(path: string): Promise<boolean> {
    try {
      await access(path)
      return true
    } catch {
      return false
    }
  }
}
