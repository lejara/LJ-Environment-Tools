import { ProjectDefaults } from './ProjectDefaults'
import { MapConfig } from './MapConfig'
import { TrimSheet } from './TrimSheet'
import { PROJECT_DATA_VERSION, type SerializedProjectData } from '@shared/types'

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
    public maps: MapConfig | null = null
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
    return data
  }

  static deserialize(raw: SerializedProjectData): ProjectData {
    return new ProjectData(
      raw.version,
      ProjectDefaults.deserialize(raw.defaults),
      raw.maps ? MapConfig.deserialize(raw.maps) : null
    )
  }
}
