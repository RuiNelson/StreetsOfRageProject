"use client";

import { useEffect, useState } from "react";
import { createPortal } from "react-dom";
import { appendLine, Progress } from "@/components/Progress";
import type { StepProps } from "@/lib/steps";
import { extractSound, soundtrackStatus, type Chip, type Soundtrack } from "@/lib/tauri";

function errorText(error: unknown) {
  return typeof error === "string" ? error : error instanceof Error ? error.message : String(error);
}

const CHIPS: { id: Chip; name: string; description: string }[] = [
  { id: "ym3438", name: "YM3438", description: "The later, CMOS version of the Mega Drive sound chip. Cleaner sound. Recommended." },
  { id: "ym2612", name: "YM2612", description: "The original chip of the first Mega Drive models, with its characteristic rougher sound." },
];

export function ExtractSound({ setReady, setBusy, actions, projectPath }: StepProps) {
  const [chip, setChip] = useState<Chip>("ym3438");
  const [done, setDone] = useState<Soundtrack | null>(null);
  const [busy, setBusyState] = useState(false);
  const [progress, setProgress] = useState<string[]>([]);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => setReady(done !== null), [done, setReady]);
  useEffect(() => setBusy(busy), [busy, setBusy]);

  // Coming back to this step with the soundtrack already rendered.
  useEffect(() => {
    if (projectPath) soundtrackStatus(projectPath).then((found) => found && setDone(found)).catch(() => {});
  }, [projectPath]);

  const extract = async () => {
    if (!projectPath) return;
    setBusyState(true);
    setError(null);
    setProgress(["Starting…"]);
    try {
      setDone(await extractSound(projectPath, chip, (line) => setProgress((lines) => appendLine(lines, line))));
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
    <div className="extract">
      <div className="notice">
        <p>
          The game plays its music and sound effects from recordings made from your ROM, because the real-time sound
          emulation is not good enough. Extract them once; it builds a small tool first, then renders every sound.
        </p>
      </div>
      <div className="notice warning">
        <p>
          <strong>This step can take a long time</strong>: several minutes, and more on slower computers. If the lines
          below pause for a while, it is still working. Keep this window open.
        </p>
      </div>
      <fieldset className="chips" disabled={busy}>
        <legend>Sound chip</legend>
        {CHIPS.map((c) => (
          <label key={c.id} className={chip === c.id ? "selected" : ""}>
            <input type="radio" name="chip" checked={chip === c.id} onChange={() => setChip(c.id)} />
            <span>
              <strong>{c.name}</strong>
              <small>{c.description}</small>
            </span>
          </label>
        ))}
      </fieldset>
      {busy && <Progress lines={progress} bar={false} />}
      {done && !busy && (
        <div className="notice ok">
          <p>Soundtrack ready: {done.files} sounds.</p>
          <code>{done.folder}</code>
        </div>
      )}
      {error && <pre className="notice error">{error}</pre>}

      {actions &&
        createPortal(
          <button className={done ? "" : "primary"} disabled={busy} onClick={extract}>
            {busy ? "Extracting…" : done ? "Extract again" : "Extract soundtrack"}
          </button>,
          actions,
        )}
    </div>
  );
}
