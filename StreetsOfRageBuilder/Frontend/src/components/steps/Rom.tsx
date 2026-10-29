"use client";

import { useCallback, useEffect, useState } from "react";
import { createPortal } from "react-dom";
import { getCurrentWebview } from "@tauri-apps/api/webview";
import { open } from "@tauri-apps/plugin-dialog";
import type { StepProps } from "@/lib/steps";
import { installedRom, verifyRom, type RomReport } from "@/lib/tauri";

function errorText(error: unknown) {
  return typeof error === "string" ? error : error instanceof Error ? error.message : String(error);
}

export function Rom({ setReady, actions, projectPath }: StepProps) {
  const [report, setReport] = useState<RomReport | null>(null);
  const [busy, setBusy] = useState(false);
  const [over, setOver] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const ok = report?.state === "ok";
  useEffect(() => setReady(ok), [ok, setReady]);

  // Coming back to this step with the ROM already in the project.
  useEffect(() => {
    if (projectPath) installedRom(projectPath).then((found) => found && setReport(found)).catch(() => {});
  }, [projectPath]);

  const verify = useCallback(
    async (path: string) => {
      if (!projectPath) return;
      setBusy(true);
      setError(null);
      try {
        setReport(await verifyRom(path, projectPath));
      } catch (e) {
        setReport(null);
        setError(errorText(e));
      } finally {
        setBusy(false);
      }
    },
    [projectPath],
  );

  // Dropping a file anywhere on the window.
  useEffect(() => {
    let unlisten: (() => void) | undefined;
    let cancelled = false;
    const listen = async () => {
      const fn = await getCurrentWebview().onDragDropEvent((event) => {
        const { type } = event.payload;
        if (type === "enter" || type === "over") setOver(true);
        else if (type === "leave") setOver(false);
        else if (type === "drop") {
          setOver(false);
          const [first] = event.payload.paths;
          if (first) verify(first);
        }
      });
      if (cancelled) fn();
      else unlisten = fn;
    };
    listen().catch(() => {}); // not running inside Tauri
    return () => {
      cancelled = true;
      unlisten?.();
    };
  }, [verify]);

  const choose = async () => {
    try {
      const picked = await open({
        title: "Choose your Streets of Rage ROM",
        filters: [
          { name: "Mega Drive ROM", extensions: ["md", "gen", "bin", "smd"] },
          { name: "All files", extensions: ["*"] },
        ],
      });
      if (typeof picked === "string") await verify(picked);
    } catch (e) {
      setError(errorText(e));
    }
  };

  if (!projectPath) {
    return <div className="notice warning">Download the project first (step 2).</div>;
  }

  return (
    <div className="rom">
      <div className={`dropzone${over ? " over" : ""}${ok ? " done" : ""}`}>
        {busy ? (
          <p>Verifying…</p>
        ) : ok ? (
          <p>
            <strong>ROM verified</strong> and copied into the project.
          </p>
        ) : (
          <p>
            <strong>Drag your ROM here</strong>, or choose the file.
          </p>
        )}
        {report && <small>{report.fileName} · CRC32 {report.crc || "—"}</small>}
      </div>

      {report?.state === "smd" && (
        <div className="notice warning">
          <p>
            This is a Super Magic Drive dump (<code>.smd</code>), which is not supported directly. Convert it to a raw dump
            (<code>.bin</code>, <code>.md</code> or <code>.gen</code>) with a ROM converter, then choose the converted file.
          </p>
        </div>
      )}
      {report?.state === "mismatch" && (
        <div className="notice warning">
          <p>
            This file is not valid, or unfortunately your cartridge version is not compatible with this project. Please
            get a copy of the original version of the game: the version needed is <strong>Rev. A</strong>.
          </p>
        </div>
      )}
      {error && <pre className="notice error">{error}</pre>}

      <div className="notice">
        <p>
          The version needed is <strong>Streets of Rage (Rev. A)</strong>, as a raw dump (<code>.bin</code>, <code>.md</code> or <code>.gen</code>).
        </p>
      </div>

      <p className="legal">Use only a ROM you legally obtained, for example a dump of a cartridge you own. It is copied into the project folder and never uploaded.</p>

      {actions &&
        createPortal(
          <button className={ok ? "" : "primary"} disabled={busy} onClick={choose}>
            {ok ? "Choose another ROM…" : "Choose ROM…"}
          </button>,
          actions,
        )}
    </div>
  );
}
