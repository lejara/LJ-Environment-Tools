import { useCallback, useEffect, useState } from "react";
import { projectService } from "../../services/projectService";
import type { OpenProjectResult } from "@shared/types";

interface StartupScreenProps {
  onOpened(result: OpenProjectResult): void | Promise<void>;
}

/** New / Open Recent / Browse. Recents come from a user-scoped config file. */
export function StartupScreen({ onOpened }: StartupScreenProps): JSX.Element {
  const [recents, setRecents] = useState<string[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    projectService
      .recents()
      .then(setRecents)
      .catch(() => setRecents([]));
  }, []);

  /** Shared body for all three entry points — cancel returns null, not an error. */
  const run = useCallback(
    async (action: () => Promise<OpenProjectResult | null>) => {
      setBusy(true);
      setError(null);
      try {
        const result = await action();
        if (result) await onOpened(result);
      } catch (err) {
        setError(err instanceof Error ? err.message : String(err));
      } finally {
        setBusy(false);
      }
    },
    [onOpened],
  );

  const forget = async (path: string): Promise<void> => {
    await projectService.forgetRecent(path);
    setRecents(await projectService.recents());
  };

  const folderName = (path: string): string =>
    path.split(/[\\/]/).filter(Boolean).pop() ?? path;

  return (
    <div className="startup">
      <div className="startup__panel">
        <header className="startup__header">
          <h1>LJ Trim Master</h1>
          <p>To master all your trims. Author trim sheets or atlases.</p>
        </header>

        <div className="startup__actions">
          <button
            type="button"
            disabled={busy}
            onClick={() => run(projectService.newProject)}
          >
            New Project
          </button>
          <button
            type="button"
            disabled={busy}
            onClick={() => run(projectService.browse)}
          >
            Browse…
          </button>
        </div>

        {error ? <div className="startup__error">{error}</div> : null}

        <section className="startup__recents">
          <h2>Open Recent</h2>
          {recents.length === 0 ? (
            <p className="startup__empty">No recent projects yet.</p>
          ) : (
            <ul>
              {recents.map((path) => (
                <li key={path}>
                  <button
                    type="button"
                    className="startup__recent"
                    disabled={busy}
                    onClick={() => run(() => projectService.open(path))}
                    title={path}
                  >
                    <span className="startup__recent-name">
                      {folderName(path)}
                    </span>
                    <span className="startup__recent-path">{path}</span>
                  </button>
                  <button
                    type="button"
                    className="startup__forget"
                    title="Remove from recents"
                    onClick={() => void forget(path)}
                  >
                    ✕
                  </button>
                </li>
              ))}
            </ul>
          )}
        </section>
      </div>
    </div>
  );
}
