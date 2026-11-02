"use client";

import { useEffect, useState } from "react";
import { createPortal } from "react-dom";
import type { StepProps } from "@/lib/steps";
import { ps5CleanUp } from "@/lib/tauri";

function errorText(error: unknown) {
  return typeof error === "string" ? error : error instanceof Error ? error.message : String(error);
}

export function Ps5CleanUp({ setReady, setBusy: setWizardBusy, actions, projectPath }: StepProps) {
  const [busy, setBusy] = useState(false);
  const [removed, setRemoved] = useState<string[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  // Cleaning up is optional: Finish is always available.
  useEffect(() => setReady(true), [setReady]);

  const cleanUp = async () => {
    if (!projectPath) return;
    setBusy(true);
    setWizardBusy(true);
    setError(null);
    try {
      setRemoved(await ps5CleanUp(projectPath));
    } catch (e) {
      setError(errorText(e));
    } finally {
      setBusy(false);
      setWizardBusy(false);
    }
  };

  if (!projectPath) {
    return <div className="notice warning">Download the project first (step 3).</div>;
  }

  return (
    <div className="cleanup">
      <div className="notice">
        <p>The container and the built title can be removed now to free the disk space:</p>
        <ul>
          <li>the container image and the build volume (about 5 GB and the compiled objects)</li>
          <li>
            the built title, <code>StreetsOfRageRecompilation/dist-ps5</code>
          </li>
        </ul>
        <p>
          Your ZIP files, your ROM and the rendered soundtrack stay. Keeping everything makes the next build faster:
          press Finish to keep it all.
        </p>
      </div>
      {removed && (
        <div className="notice ok">
          <p>{removed.length > 0 ? `Removed: ${removed.join(", ").toLowerCase()}.` : "There was nothing to remove."}</p>
        </div>
      )}
      {error && <pre className="notice error">{error}</pre>}

      {actions &&
        createPortal(
          <button className={removed ? "" : "primary"} disabled={busy} onClick={cleanUp}>
            {busy ? "Cleaning up…" : removed ? "Clean up again" : "Clean up"}
          </button>,
          actions,
        )}
    </div>
  );
}
