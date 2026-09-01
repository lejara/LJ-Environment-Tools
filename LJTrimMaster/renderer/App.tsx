import { useCallback, useState } from 'react'
import { StartupScreen } from './ui/startup/StartupScreen'
import { EditorShell } from './ui/editor/EditorShell'
import { useProjectStore } from './state/projectStore'
import { useAssetsStore } from './state/assetsStore'
import { usePresetsStore } from './state/presetsStore'
import { refreshService } from './services/refreshService'
import type { OpenProjectResult } from '@shared/types'

/**
 * Routes between the startup screen and the editor. There is no router — the
 * app has exactly two states and one transition.
 */
export function App(): JSX.Element {
  const project = useProjectStore((state) => state.project)
  const openFrom = useProjectStore((state) => state.openFrom)
  const setAssets = useAssetsStore((state) => state.setFromSerialized)
  const setPresets = usePresetsStore((state) => state.setFromSerialized)
  const [error, setError] = useState<string | null>(null)

  /** Opening a project always kicks a first refresh so the panels have data. */
  const handleOpened = useCallback(
    async (result: OpenProjectResult) => {
      openFrom(result)
      setError(null)
      try {
        const refreshed = await refreshService.refreshAll(result.rootPath)
        setAssets(refreshed.assets, refreshed.mapConfig)
        setPresets(refreshed.presets, refreshed.warnings)
      } catch (err) {
        // The project is open and usable; the panels are just empty.
        setError(err instanceof Error ? err.message : String(err))
      }
    },
    [openFrom, setAssets, setPresets]
  )

  if (!project) return <StartupScreen onOpened={handleOpened} />
  return <EditorShell startupError={error} />
}
