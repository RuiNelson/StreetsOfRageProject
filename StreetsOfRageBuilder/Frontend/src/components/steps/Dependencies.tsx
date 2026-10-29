"use client";

import { useCallback, useEffect, useState } from "react";
import { createPortal } from "react-dom";
import { openUrl } from "@tauri-apps/plugin-opener";
import type { StepProps } from "@/lib/steps";
import { checkDependencies, installDependencies, type DependenciesReport, type Dependency } from "@/lib/tauri";

const ICON = { ok: "✓", missing: "✗", unknown: "?" } as const;

function errorText(error: unknown) {
  return typeof error === "string" ? error : error instanceof Error ? error.message : String(error);
}

export function Dependencies({ setReady, actions }: StepProps) {
  const [report, setReport] = useState<DependenciesReport | null>(null);
  const [checking, setChecking] = useState(true);
  const [installing, setInstalling] = useState<string[]>([]);
  const [notes, setNotes] = useState<string[]>([]);
  const [error, setError] = useState<string | null>(null);

  const check = useCallback(async () => {
    setChecking(true);
    try {
      const next = await checkDependencies();
      setReport(next);
      setReady(next.ready);
    } catch (e) {
      setError(errorText(e));
      setReady(false);
    } finally {
      setChecking(false);
    }
  }, [setReady]);

  useEffect(() => {
    check();
    // The installers run in a terminal: look again when the user comes back.
    window.addEventListener("focus", check);
    return () => window.removeEventListener("focus", check);
  }, [check]);

  const install = async (ids: string[]) => {
    setInstalling(ids);
    setError(null);
    setNotes([]);
    try {
      setNotes(await installDependencies(ids));
    } catch (e) {
      setError(errorText(e));
    } finally {
      setInstalling([]);
      await check();
    }
  };

  if (!report) {
    return <div className="placeholder">{error ?? "Checking your system…"}</div>;
  }

  const { manager, dependencies } = report;
  const missing = dependencies.filter((d) => d.state === "missing" && d.installable);
  const busy = installing.length > 0;

  return (
    <div className="dependencies">
      {!manager.available && (
        <div className="notice warning">
          <p>{manager.message}</p>
          {manager.helpUrl && (
            <button onClick={() => openUrl(manager.helpUrl!)}>Open {new URL(manager.helpUrl).host}</button>
          )}
          {manager.manualPackages.length > 0 && <code>{manager.manualPackages.join(" ")}</code>}
        </div>
      )}

      <ul className="deps">
        {dependencies.map((d) => (
          <DependencyRow key={d.id} dependency={d} installing={installing.includes(d.id)} disabled={busy || checking} onInstall={() => install([d.id])} />
        ))}
      </ul>

      {notes.map((n) => (
        <div key={n} className="notice">{n}</div>
      ))}
      {error && <pre className="notice error">{error}</pre>}

      {actions &&
        createPortal(
          <>
            <button disabled={busy || checking} onClick={check}>{checking ? "Checking…" : "Re-check"}</button>
            {missing.length > 1 && (
              <button className="primary" disabled={busy || checking} onClick={() => install(missing.map((d) => d.id))}>
                Install all missing
              </button>
            )}
          </>,
          actions,
        )}
    </div>
  );
}

function DependencyRow({ dependency: d, installing, disabled, onInstall }: {
  dependency: Dependency;
  installing: boolean;
  disabled: boolean;
  onInstall: () => void;
}) {
  return (
    <li className={`dep ${d.state}`}>
      <span className="status">{ICON[d.state]}</span>
      <div className="info">
        <strong>{d.name}</strong>
        <span>{d.description}</span>
        {d.detail && <small>{d.detail}</small>}
      </div>
      {d.state !== "ok" && d.installable && (
        <button disabled={disabled} onClick={onInstall}>{installing ? "Installing…" : "Install"}</button>
      )}
    </li>
  );
}
