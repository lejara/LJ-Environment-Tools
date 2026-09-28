import { ProjectDefaults } from './ProjectDefaults'
import { MapConfig } from './MapConfig'
import { TrimSheet } from './TrimSheet'
import {
  PROJECT_DATA_VERSION,
  type SerializedProjectData,
  type SerializedProjectFolders
} from '@shared/types'

/**
 * The shape of projectData.json — the project's whole serialization surface.
 * Version-stamped so future shape changes can be migrated on load.
 */
export class ProjectData {
  constructor(
    public version: string = PROJECT_DATA_VERSION,
    public defaults: ProjectDefaults = new ProjectDefaults(),
    /**
     * Cached `maps.yaml` vocabulary, so integrations that can only see the
     * project can still split `wood_BaseColor` the same way the tool does.
     * Null until the first refresh stamps it — see `Project.setMapVocabulary`.
     */
    public maps: MapConfig | null = null,
    /** Custom image_dump / output locations. Empty means the stock folders. */
    public folders: SerializedProjectFolders = {}
  ) {}

  serialize(sheets: TrimSheet[]): SerializedProjectData {
    const data: SerializedProjectData = {
      version: this.version,
      defaults: this.defaults.serialize(),
      sheets: sheets.map((sheet) => sheet.serialize())
    }
    // Omitted entirely rather than written as null, so a project that has never
    // been refreshed looks the same on disk as one written before this existed.
    if (this.maps) data.maps = this.maps.serialize()
    // Same rule: only written once the user has actually moved a folder.
    const folders = ProjectData.cleanFolders(this.folders)
    if (folders.imageDump || folders.output) data.folders = folders
    return data
  }

  static deserialize(raw: SerializedProjectData): ProjectData {
    return new ProjectData(
      raw.version,
      ProjectDefaults.deserialize(raw.defaults),
      raw.maps ? MapConfig.deserialize(raw.maps) : null,
      ProjectData.cleanFolders(raw.folders ?? {})
    )
  }

  /** Drops blank entries, so "reset to default" and "never set" look the same. */
  static cleanFolders(folders: SerializedProjectFolders): SerializedProjectFolders {
    const clean: SerializedProjectFolders = {}
    const imageDump = folders.imageDump?.trim()
    const output = folders.output?.trim()
    if (imageDump) clean.imageDump = imageDump
    if (output) clean.output = output
    return clean
  }
}
