import { ProjectDefaults } from './ProjectDefaults'
import { TrimSheet } from './TrimSheet'
import { PROJECT_DATA_VERSION, type SerializedProjectData } from '@shared/types'

/**
 * The shape of projectData.json — the project's whole serialization surface.
 * Version-stamped so future shape changes can be migrated on load.
 */
export class ProjectData {
  constructor(
    public version: string = PROJECT_DATA_VERSION,
    public defaults: ProjectDefaults = new ProjectDefaults()
  ) {}

  serialize(sheets: TrimSheet[]): SerializedProjectData {
    return {
      version: this.version,
      defaults: this.defaults.serialize(),
      sheets: sheets.map((sheet) => sheet.serialize())
    }
  }

  static deserialize(raw: SerializedProjectData): ProjectData {
    return new ProjectData(raw.version, ProjectDefaults.deserialize(raw.defaults))
  }
}
