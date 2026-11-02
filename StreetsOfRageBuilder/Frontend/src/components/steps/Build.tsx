"use client";

import { useEffect, useState } from "react";
import { createPortal } from "react-dom";
import { appendLine, Progress } from "@/components/Progress";
import { playResult } from "@/lib/sounds";
import type { StepProps } from "@/lib/steps";
import { buildGame, gameStatus, ps5Build, ps5TitleStatus } from "@/lib/tauri";

/** The game's executable, or the folder of the PS5 title. */
type Built = { path: string };

function errorText(error: unknown) {
  return typeof error === "string" ? error : error instanceof Error ? error.message : String(error);
}

export function Build({ target, setReady, setBusy, actions, projectPath }: StepProps) {
  const [done, setDone] = useState<Built | null>(null);
  const [busy, setBusyState] = useState(false);
  const [progress, setProgress] = useState<string[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [outdated, setOutdated] = useState(false);

  useEffect(() => setReady(done !== null), [done, setReady]);
  useEffect(() => setBusy(busy), [busy, setBusy]);

  // Coming back to this step with the game already built; a build of an older version does not count.
  useEffect(() => {
    if (!projectPath) return;
    const status =
      target === "ps5"
        ? ps5TitleStatus(projectPath).then((t) => t && { path: t.folder, outdated: t.outdated })
        : gameStatus(projectPath).then((g) => g && { path: g.executable, outdated: g.outdated });
    status
      .then((found) => {
        if (!found) return;
        if (found.outdated) setOutdated(true);
        else setDone({ path: found.path });
      })
      .catch(() => {});
  }, [projectPath, target]);

  const build = async () => {
    if (!projectPath) return;
    setBusyState(true);
    setError(null);
    setOutdated(false);
    setProgress(["Starting…"]);
    try {
      const onLine = (line: string) => setProgress((lines) => appendLine(lines, line));
      setDone(
        target === "ps5"
          ? { path: (await ps5Build(projectPath, onLine)).folder }
          : { path: (await buildGame(projectPath, onLine)).executable },
      );
      playResult(true);
    } catch (e) {
      setDone(null);
      setError(errorText(e));
      playResult(false);
    } finally {
      setBusyState(false);
    }
  };

  if (!projectPath) {
    return <div className="notice warning">Download the project first (step 3).</div>;
  }

  return (
    <div className="build">
      <div className="notice">
        <p>
          {target === "ps5"
            ? "This turns your ROM into a title for the PS5: it generates the C++ code and compiles it with the PS5 toolchain, inside the container. It needs about 12 GB of free disk space."
            : "This turns your ROM into a native game: it generates the C++ code, downloads the libraries it needs and compiles everything."}{" "}
          The first build can take several minutes (longer on slower computers) and uses all your processor cores. Keep
          this window open.
        </p>
      </div>
      {outdated && !busy && !done && (
        <div className="notice warning">
          <p>The {target === "ps5" ? "title" : "game"} in this folder was built from an older version of the project. Build it again.</p>
        </div>
      )}
      {busy && <Progress lines={progress} />}
      {done && !busy && (
        <div className="notice ok">
          <p>{target === "ps5" ? "The PS5 title is built." : "The game is built."}</p>
          <code>{done.path}</code>
        </div>
      )}
      {error && <pre className="notice error">{error}</pre>}

      {actions &&
        createPortal(
          <button className={done ? "" : "primary"} disabled={busy} onClick={build}>
            {busy ? "Building…" : done ? "Build again" : target === "ps5" ? "Build the title" : "Build the game"}
          </button>,
          actions,
        )}
    </div>
  );
}
