"use client";

import { useEffect, useState } from "react";
import { createPortal } from "react-dom";
import { downloadDir } from "@tauri-apps/api/path";
import { open } from "@tauri-apps/plugin-dialog";
import { revealItemInDir } from "@tauri-apps/plugin-opener";
import { appendLine, Progress } from "@/components/Progress";
import { playResult } from "@/lib/sounds";
import type { StepProps } from "@/lib/steps";
import { ps5MakeZips, ps5ProbeConsole, ps5TitleStatus, ps5Upload, type ZipFile } from "@/lib/tauri";

const FTP_DEFAULT_PORT = "2121";

type How = "zip" | "ftp" | "both";

const CHOICES: { id: How; name: string; description: string }[] = [
  { id: "zip", name: "ZIP files", description: "Two ZIP files in a folder you choose, to copy to the console yourself." },
  { id: "ftp", name: "Upload by FTP", description: "The Builder sends the files to the console over your network." },
  { id: "both", name: "Both", description: "Make the ZIP files and upload." },
];

function errorText(error: unknown) {
  return typeof error === "string" ? error : error instanceof Error ? error.message : String(error);
}

function size(bytes: number) {
  return bytes >= 1e9 ? `${(bytes / 1e9).toFixed(1)} GB` : `${Math.max(1, Math.round(bytes / 1e6))} MB`;
}

export function Ps5Deliver({ setReady, setBusy, actions, projectPath }: StepProps) {
  const [how, setHow] = useState<How>("zip");
  const [folder, setFolder] = useState<string | null>(null);
  const [host, setHost] = useState("");
  const [port, setPort] = useState(FTP_DEFAULT_PORT);
  const [busy, setBusyState] = useState(false);
  const [progress, setProgress] = useState<string[]>([]);
  const [zips, setZips] = useState<ZipFile[] | null>(null);
  const [sent, setSent] = useState<number | null>(null);
  const [built, setBuilt] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const wantsZip = how !== "ftp";
  const wantsFtp = how !== "zip";
  const done = (!wantsZip || zips !== null) && (!wantsFtp || sent !== null) && (zips !== null || sent !== null);
  useEffect(() => setReady(done), [done, setReady]);
  useEffect(() => setBusy(busy), [busy, setBusy]);

  useEffect(() => {
    if (projectPath) ps5TitleStatus(projectPath).then((t) => setBuilt(t !== null)).catch(() => {});
  }, [projectPath]);

  const chooseFolder = async () => {
    try {
      const picked = await open({ directory: true, title: "Choose the folder for the ZIP files", defaultPath: await downloadDir().catch(() => undefined) });
      if (typeof picked === "string") setFolder(picked);
    } catch (e) {
      setError(errorText(e));
    }
  };

  const ready = (!wantsZip || folder !== null) && (!wantsFtp || host.trim() !== "");

  const run = async () => {
    if (!projectPath) return;
    setBusyState(true);
    setError(null);
    setZips(null);
    setSent(null);
    setProgress(["Starting…"]);
    const onLine = (line: string) => setProgress((lines) => appendLine(lines, line));
    try {
      if (wantsFtp) {
        // Fail before the long work when the console cannot be reached.
        onLine(`Connecting to ${host.trim()}:${port.trim()}…`);
        await ps5ProbeConsole(host, port);
      }
      if (wantsZip && folder) setZips(await ps5MakeZips(projectPath, folder, onLine));
      if (wantsFtp) setSent(await ps5Upload(projectPath, host, port, onLine));
      playResult(true);
    } catch (e) {
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
    <div className="deliver">
      {!built && (
        <div className="notice warning">
          <p>The PS5 title is not built yet. Finish the build step first.</p>
        </div>
      )}
      <fieldset className="chips" disabled={busy}>
        <legend>How do you want the files?</legend>
        {CHOICES.map((c) => (
          <label key={c.id} className={how === c.id ? "selected" : ""}>
            <input type="radio" name="how" checked={how === c.id} onChange={() => setHow(c.id)} />
            <span>
              <strong>{c.name}</strong>
              <small>{c.description}</small>
            </span>
          </label>
        ))}
      </fieldset>

      {wantsZip && (
        <div className="notice">
          <p>{folder ? "The ZIP files go to:" : "Choose the folder for the two ZIP files."}</p>
          {folder && <code>{folder}</code>}
        </div>
      )}
      {wantsFtp && (
        <>
          <div className="notice">
            <p>
              On the PS5, run an FTP server such as ftpsrv (anonymous login, port {FTP_DEFAULT_PORT} by default). The files
              go to <code>/data/homebrew</code> and <code>/data/sor</code>.
            </p>
          </div>
          <div className="fields">
            <label>
              The console&apos;s IP address
              <input value={host} placeholder="192.168.1.50" disabled={busy} onChange={(e) => setHost(e.target.value)} />
            </label>
            <label>
              FTP port
              <input value={port} inputMode="numeric" size={6} disabled={busy} onChange={(e) => setPort(e.target.value)} />
            </label>
          </div>
        </>
      )}

      {busy && <Progress lines={progress} />}
      {zips && !busy && (
        <div className="notice ok">
          <p>Your ZIP files are ready:</p>
          {zips.map((zip) => (
            <code key={zip.path}>
              {zip.path} ({size(zip.size)})
            </code>
          ))}
          <p>
            Unzip <code>StreetsOfRage-PS5-homebrew.zip</code> into <code>/data/homebrew</code> on the console (or any folder
            ShadowMountPlus 1.7 beta 4 or newer scans), and <code>StreetsOfRage-PS5-data.zip</code> into <code>/data</code>: it
            holds the folder <code>sor</code> with the AI, Python, the soundtrack and your ROM as <code>SOR.bin</code>.
          </p>
          <button onClick={() => revealItemInDir(zips[0].path).catch(() => {})}>Show in folder</button>
        </div>
      )}
      {sent !== null && !busy && (
        <div className="notice ok">
          <p>
            Everything is on the console ({sent} files): the title in <code>/data/homebrew/PPSA99872</code> and the data in{" "}
            <code>/data/sor</code>.
          </p>
        </div>
      )}
      {done && !busy && (
        <div className="notice">
          <p>Mount the title with ShadowMountPlus and start Streets of Rage from the home screen.</p>
        </div>
      )}
      {error && <pre className="notice error">{error}</pre>}

      {actions &&
        createPortal(
          <>
            {wantsZip && (
              <button disabled={busy} onClick={chooseFolder}>
                {folder ? "Choose another folder…" : "Choose folder…"}
              </button>
            )}
            <button className={done ? "" : "primary"} disabled={busy || !ready || !built} onClick={run}>
              {busy ? "Working…" : done ? "Do it again" : wantsFtp && !wantsZip ? "Send to the console" : "Make the files"}
            </button>
          </>,
          actions,
        )}
    </div>
  );
}
