import { useCallback, useEffect, useState } from 'react'
import { StartupScreen } from './ui/startup/StartupScreen'
import { EditorShell } from './ui/editor/EditorShell'
import { HowToUseModal } from './ui/editor/modals/HowToUseModal'
import { useProjectStore } from './state/projectStore'
import { useAssetsStore } from './state/assetsStore'
import { usePresetsStore } from './state/presetsStore'
import { useBlenderLinksStore } from './state/blenderLinksStore'
import { MapConfig } from '@models/MapConfig'
import { refreshService } from './services/refreshService'
import { bridge } from './services/bridge'
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
  const setBlenderLinks = useBlenderLinksStore((state) => state.setFromSerialized)
  const setMapVocabulary = useProjectStore((state) => state.setMapVocabulary)
  const [error, setError] = useState<string | null>(null)
  const [howToUseOpen, setHowToUseOpen] = useState(false)

  // Help lives at the root rather than inside the editor so it also opens on
  // the startup screen, which is exactly where a first-time user reaches for it.
  useEffect(
    () =>
      bridge().onMenuCommand((command) => {
        if (command === 'howToUse') setHowToUseOpen(true)
      }),
    []
  )

  /** Opening a project always kicks a first refresh so the panels have data. */
  const handleOpened = useCallback(
    async (result: OpenProjectResult) => {
      openFrom(result)
      setError(null)
      try {
        const refreshed = await refreshService.refreshAll(result.rootPath)
        setAssets(refreshed.assets, refreshed.mapConfig)
        setPresets(refreshed.presets, refreshed.warnings)
        setBlenderLinks(refreshed.blenderLinks)
        setMapVocabulary(MapConfig.deserialize(refreshed.mapConfig))
      } catch (err) {
        // The project is open and usable; the panels are just empty.
        setError(err instanceof Error ? err.message : String(err))
      }
    },
    [openFrom, setAssets, setPresets, setBlenderLinks, setMapVocabulary]
  )

  return (
    <>
      {project ? <EditorShell startupError={error} /> : <StartupScreen onOpened={handleOpened} />}
      {howToUseOpen ? <HowToUseModal onClose={() => setHowToUseOpen(false)} /> : null}
    </>
  )
}
