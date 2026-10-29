"use client";

import { useEffect, useState } from "react";
import { createPortal } from "react-dom";
import { appendLine, Progress } from "@/components/Progress";
import type { StepProps } from "@/lib/steps";
import { buildGame, gameStatus, type Game } from "@/lib/tauri";

function errorText(error: unknown) {
  return typeof error === "string" ? error : error instanceof Error ? error.message : String(error);
}

export function Build({ setReady, setBusy, actions, projectPath }: StepProps) {
  const [done, setDone] = useState<Game | null>(null);
  const [busy, setBusyState] = useState(false);
  const [progress, setProgress] = useState<string[]>([]);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => setReady(done !== null), [done, setReady]);
  useEffect(() => setBusy(busy), [busy, setBusy]);

  // Coming back to this step with the game already built.
  useEffect(() => {
    if (projectPath) gameStatus(projectPath).then((found) => found && setDone(found)).catch(() => {});
  }, [projectPath]);

  const build = async () => {
    if (!projectPath) return;
    setBusyState(true);
    setError(null);
    setProgress(["Starting…"]);
    try {
      setDone(await buildGame(projectPath, (line) => setProgress((lines) => appendLine(lines, line))));
    } catch (e) {
      setDone(null);
      setError(errorText(e));
    } finally {
      setBusyState(false);
    }
  };

  if (!projectPath) {
    return <div className="notice warning">Download the project first (step 2).</div>;
  }

  return (
    <div className="build">
      <div className="notice">
        <p>
          This turns your ROM into a native game: it generates the C++ code, downloads the libraries it needs and
          compiles everything. The first build can take several minutes (longer on slower computers) and uses all your
          processor cores. Keep this window open.
        </p>
      </div>
      {busy && <Progress lines={progress} />}
      {done && !busy && (
        <div className="notice ok">
          <p>The game is built.</p>
          <code>{done.executable}</code>
        </div>
      )}
      {error && <pre className="notice error">{error}</pre>}

      {actions &&
        createPortal(
          <button className={done ? "" : "primary"} disabled={busy} onClick={build}>
            {busy ? "Building…" : done ? "Build again" : "Build the game"}
          </button>,
          actions,
        )}
    </div>
  );
}
