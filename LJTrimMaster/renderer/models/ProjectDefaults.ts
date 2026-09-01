import { Resolution } from './Resolution'
import type { SerializedProjectDefaults } from '@shared/types'

/**
 * Project-wide defaults, edited from the Settings modal.
 *
 * These SEED new objects; they never retroactively change existing ones. A new
 * sheet copies `defaultTrimResolution` at creation and owns its copy from then
 * on. Designed to grow — add fields here and a control in SettingsModal.
 */
export class ProjectDefaults {
  constructor(public defaultTrimResolution: Resolution = Resolution.default()) {}

  clone(): ProjectDefaults {
    return new ProjectDefaults(this.defaultTrimResolution.clone())
  }

  serialize(): SerializedProjectDefaults {
    return { defaultTrimResolution: this.defaultTrimResolution.serialize() }
  }

  static deserialize(raw: SerializedProjectDefaults): ProjectDefaults {
    return new ProjectDefaults(Resolution.deserialize(raw.defaultTrimResolution))
  }
}
