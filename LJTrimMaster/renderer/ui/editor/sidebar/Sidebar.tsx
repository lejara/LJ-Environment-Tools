import { PropertiesPanel } from './PropertiesPanel'
import { AssetsPanel } from './AssetsPanel'
import { Outliner } from './Outliner'
import { SheetSettingsPanel } from './SheetSettingsPanel'

/**
 * Right-hand region, split into two columns.
 *
 * The Outliner gets a column to itself on the left because it is the only way
 * to select a trim — the Viewport is preview-only — so it is in constant use
 * and benefits from the full height. Everything that acts on the selection sits
 * in the right column, next to it rather than scrolled away below it.
 *
 * Each column scrolls independently, so a long trim list can't push the
 * Properties panel off-screen.
 */
export function Sidebar(): JSX.Element {
  return (
    <aside className="sidebar">
      <div className="sidebar__column sidebar__column--outliner">
        <Outliner />
      </div>
      <div className="sidebar__column">
        <PropertiesPanel />
        <AssetsPanel />
        <SheetSettingsPanel />
      </div>
    </aside>
  )
}
