import { useCallback, useEffect, useState } from "react";
import { useProjectStore, useRevision } from "../../state/projectStore";
import { useAssetsStore } from "../../state/assetsStore";
import { usePresetsStore } from "../../state/presetsStore";
import { refreshService } from "../../services/refreshService";
import { exportService } from "../../services/exportService";
import { autoExportService } from "../../services/autoExportService";
import { appBus } from "../../services/appBus";
import { AppEvent } from "@shared/events/AppEvent";

interface ToolbarProps {
  onOpenSettings(): void;
  status: string | null;
  onStatus(message: string | null): void;
}

/**
 * Bottom toolbar: settings gear, Auto Export toggle, Build, and the global
 * Refresh.
 *
 * Refresh is the single entry point for reloading maps.yaml, preset-packs/ and
 * image_dump/ — it emits REFRESH_REQUESTED and lets subscribers react, so other
 * sections can hook in without this button knowing about them.
 */
export function Toolbar({
  onOpenSettings,
  status,
  onStatus,
}: ToolbarProps): JSX.Element {
  const project = useProjectStore((state) => state.project);
  const save = useProjectStore((state) => state.save);
  const setAssets = useAssetsStore((state) => state.setFromSerialized);
  const assets = useAssetsStore((state) => state.assets);
  const setPresets = usePresetsStore((state) => state.setFromSerialized);
  const presets = usePresetsStore((state) => state.presets);
  const rev = useRevision();

  const [autoExport, setAutoExport] = useState(false);
  const [busy, setBusy] = useState(false);

  const activeSheet = project?.activeSheet ?? null;
  const dirtyCount = project?.dirtySheets.length ?? 0;
  void rev;

  const handleRefresh = useCallback(async () => {
    if (!project) return;
    setBusy(true);
    // REFRESH_REQUESTED is emitted locally so renderer-side subscribers see it
    // too; main emits its own on the far side of the invoke.
    appBus.emit(AppEvent.REFRESH_REQUESTED, { projectRoot: project.rootPath });
    try {
      const result = await refreshService.refreshAll(project.rootPath);
      setAssets(result.assets, result.mapConfig);
      setPresets(result.presets, result.warnings);
    } catch (err) {
      onStatus(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  }, [project, setAssets, setPresets, onStatus]);

  /** Manual Build: re-export the active sheet regardless of its dirty flag. */
  const manualExport = useCallback(async () => {
    if (!project || !activeSheet) return;
    setBusy(true);
    try {
      await save();
      await exportService.exportSheet({
        sheet: activeSheet.serialize(),
        assets: assets.map((asset) => asset.serialize()),
        presets: presets.map((preset) => preset.serialize()),
        projectRoot: project.rootPath,
      });
      // Status comes from the EXPORT_* events, not from this return value.
    } catch (err) {
      onStatus(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  }, [project, activeSheet, assets, presets, save, onStatus]);

  const toggleAutoExport = useCallback(async () => {
    const next = !autoExport;
    setAutoExport(next);
    try {
      await autoExportService.setEnabled(next);
      onStatus(
        next
          ? "Auto Export on — dirty sheets re-export automatically."
          : "Auto Export off.",
      );
    } catch (err) {
      setAutoExport(!next);
      onStatus(err instanceof Error ? err.message : String(err));
    }
  }, [autoExport, onStatus]);

  // Persist on edit so a crash can't cost more than the last couple of seconds.
  useEffect(() => {
    if (!project) return;
    const timer = setTimeout(() => void save().catch(() => undefined), 800);
    return () => clearTimeout(timer);
  }, [rev, project, save]);

  return (
    <footer className="toolbar">
      <button
        type="button"
        className="toolbar__icon"
        title="Settings"
        onClick={onOpenSettings}
      >
        ⚙
      </button>

      <button
        type="button"
        className={`toolbar__toggle ${autoExport ? "is-on" : ""}`}
        onClick={() => void toggleAutoExport()}
        title="Re-export sheets automatically when they change"
      >
        Auto Export
        <span className="toolbar__dot" />
      </button>

      <button
        type="button"
        className="toolbar__button"
        disabled={busy || !activeSheet}
        onClick={() => void manualExport()}
        title="Re-export the active sheet now"
      >
        Export
      </button>

      <button
        type="button"
        className="toolbar__button"
        disabled={busy}
        onClick={() => void handleRefresh()}
        title="Re-scan image_dump, preset-packs and maps.yaml"
      >
        ⟳ Refresh
      </button>

      <div className="toolbar__status">
        {dirtyCount > 0 ? (
          <span className="toolbar__dirty">
            {dirtyCount} unsaved sheet{dirtyCount === 1 ? "" : "s"}
          </span>
        ) : null}
        {status ? <span className="toolbar__message">{status}</span> : null}
      </div>

      <div className="toolbar__project" title={project?.rootPath}>
        {project?.name}
      </div>
    </footer>
  );
}
