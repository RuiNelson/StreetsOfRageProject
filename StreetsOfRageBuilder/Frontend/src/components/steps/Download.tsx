"use client";

import { useEffect, useState } from "react";
import { createPortal } from "react-dom";
import { open } from "@tauri-apps/plugin-dialog";
import type { StepProps } from "@/lib/steps";
import { downloadProject, inspectProject, type Downloaded, type Inspection } from "@/lib/tauri";

function errorText(error: unknown) {
  return typeof error === "string" ? error : error instanceof Error ? error.message : String(error);
}

const HINT: Record<Inspection["state"], string> = {
  missing: "The project will be downloaded into this new folder.",
  empty: "The project will be downloaded into this empty folder.",
  clone: "The project is already here: it will be updated to this Builder's version. Local changes to its files are replaced.",
  occupied: "This folder is not empty and is not a copy of the project. Choose an empty folder.",
};

export function Download({ setReady, setBusy, actions, projectPath, setProjectPath }: StepProps) {
  const [inspection, setInspection] = useState<Inspection | null>(null);
  const [folder, setParent] = useState<string | null>(null);
  const [busy, setBusyState] = useState(false);
  const [progress, setProgress] = useState("");
  const [done, setDone] = useState<Downloaded | null>(projectPath ? { path: projectPath, updated: false, commit: "" } : null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => setReady(done !== null), [done, setReady]);
  useEffect(() => setBusy(busy), [busy, setBusy]);

  const choose = async () => {
    try {
      const picked = await open({ directory: true, title: "Choose the folder for Streets of Rage Project (choose it again later to update)" });
      if (typeof picked !== "string") return;
      setParent(picked);
      setInspection(await inspectProject(picked));
      setDone(null);
      setProjectPath(null);
      setError(null);
    } catch (e) {
      setError(errorText(e));
    }
  };

  const download = async () => {
    if (!folder) return;
    setBusyState(true);
    setError(null);
    setProgress("Starting…");
    try {
      const result = await downloadProject(folder, setProgress);
      setDone(result);
      setProjectPath(result.path);
      setInspection(await inspectProject(folder));
    } catch (e) {
      setError(errorText(e));
    } finally {
      setBusyState(false);
    }
  };

  const verb = inspection?.state === "clone" ? "Update" : "Download";

  return (
    <div className="download">
      <div className="notice">
        <p>
          Choose an empty folder to download the project into, or the folder of a previous download to update it. Only
          the version matching this Builder is downloaded (a single commit of history, submodules included), so it is
          small and quick to get.
        </p>
      </div>

      {actions &&
        createPortal(
          <>
            <button disabled={busy} onClick={choose}>{folder ? "Choose another folder…" : "Choose folder…"}</button>
            {inspection && (
              <button className={done ? "" : "primary"} disabled={busy || inspection.state === "occupied"} onClick={download}>
                {busy ? `${verb === "Update" ? "Updating" : "Downloading"}…` : verb}
              </button>
            )}
          </>,
          actions,
        )}

      {inspection && (
        <div className={`notice${inspection.state === "occupied" ? " warning" : ""}`}>
          <p>{HINT[inspection.state]}</p>
          <code>{inspection.path}</code>
        </div>
      )}
      {busy && <div className="notice progress">{progress}</div>}
      {done && !busy && (
        <div className="notice ok">
          <p>{done.commit ? (done.updated ? "Project updated" : "Project downloaded") : "Project ready"}: {done.commit}</p>
          <code>{done.path}</code>
        </div>
      )}
      {error && <pre className="notice error">{error}</pre>}
    </div>
  );
}
