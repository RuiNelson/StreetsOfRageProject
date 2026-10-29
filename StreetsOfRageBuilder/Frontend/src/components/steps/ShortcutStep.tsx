"use client";

import { useEffect, useState } from "react";
import { createPortal } from "react-dom";
import type { StepProps } from "@/lib/steps";
import { createShortcut, shortcutStatus, type Shortcut } from "@/lib/tauri";

function errorText(error: unknown) {
  return typeof error === "string" ? error : error instanceof Error ? error.message : String(error);
}

export function ShortcutStep({ setReady, actions, projectPath }: StepProps) {
  const [done, setDone] = useState<Shortcut | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // The last step has no Next: nothing to hold back.
  useEffect(() => setReady(true), [setReady]);

  // Coming back to this step with the shortcut already on the desktop.
  useEffect(() => {
    shortcutStatus().then((found) => found && setDone(found)).catch(() => {});
  }, []);

  const create = async () => {
    if (!projectPath) return;
    setBusy(true);
    setError(null);
    try {
      setDone(await createShortcut(projectPath));
    } catch (e) {
      setError(errorText(e));
    } finally {
      setBusy(false);
    }
  };

  if (!projectPath) {
    return <div className="notice warning">Download the project first (step 2).</div>;
  }

  return (
    <div className="shortcut">
      <div className="notice">
        <p>
          Adds a <strong>Streets of Rage</strong> shortcut to your desktop. It opens the game launcher, where you start
          the game.
        </p>
      </div>
      {done && (
        <div className="notice ok">
          <p>The shortcut is on your desktop. You are all set: have fun!</p>
          <code>{done.path}</code>
        </div>
      )}
      {error && <pre className="notice error">{error}</pre>}

      {actions &&
        createPortal(
          <button className={done ? "" : "primary"} disabled={busy} onClick={create}>
            {busy ? "Adding…" : done ? "Add it again" : "Add shortcut"}
          </button>,
          actions,
        )}
    </div>
  );
}
