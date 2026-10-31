"use client";

import { useEffect, useState } from "react";
import { createPortal } from "react-dom";
import type { StepProps } from "@/lib/steps";
import { createShortcut, platformInfo, shortcutStatus, type Platform, type Shortcut, type ShortcutLocation } from "@/lib/tauri";

const LOCATIONS: { id: ShortcutLocation; name: string; description: string }[] = [
  { id: "applications", name: "/Applications", description: "With your other apps, in Launchpad and Spotlight." },
  { id: "home", name: "~", description: "In your home folder." },
];

function errorText(error: unknown) {
  return typeof error === "string" ? error : error instanceof Error ? error.message : String(error);
}

export function ShortcutStep({ setReady, setBusy: setWizardBusy, actions, projectPath }: StepProps) {
  const [platform, setPlatform] = useState<Platform | null>(null);
  const [location, setLocation] = useState<ShortcutLocation>("applications");
  const [done, setDone] = useState<Shortcut | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // The shortcut is optional: Finish is always available.
  useEffect(() => setReady(true), [setReady]);

  useEffect(() => {
    platformInfo().then((info) => setPlatform(info.platform)).catch(() => {});
  }, []);

  // Coming back to this step with the shortcuts already made.
  useEffect(() => {
    shortcutStatus()
      .then((found) => {
        if (!found) return;
        setDone(found);
        if (found.location) setLocation(found.location);
      })
      .catch(() => {});
  }, []);

  const create = async () => {
    if (!projectPath) return;
    setBusy(true);
    setWizardBusy(true);
    setError(null);
    try {
      setDone(await createShortcut(projectPath, platform === "macos" ? location : null));
    } catch (e) {
      setError(errorText(e));
    } finally {
      setBusy(false);
      setWizardBusy(false);
    }
  };

  if (!projectPath) {
    return <div className="notice warning">Download the project first (step 2).</div>;
  }

  return (
    <div className="shortcut">
      <div className="notice">
        {platform === "macos" ? (
          <p>
            Creates a <strong>StreetsOfRageProject</strong> folder with two apps: <strong>StreetsOfRageRecompilation</strong>{" "}
            starts the game, and <strong>StreetsOfRageRecompilation Launcher</strong> opens the launcher window, with all the
            options. The game app holds its own copy of everything it needs, including your ROM, so keep it to yourself.
          </p>
        ) : (
          <p>
            Adds two shortcuts to your desktop: <strong>StreetsOfRageRecompilation</strong> starts the game, and{" "}
            <strong>StreetsOfRageRecompilation Launcher</strong> opens the launcher window, with all the options.
          </p>
        )}
      </div>
      {platform === "macos" && (
        <fieldset className="chips" disabled={busy}>
          <legend>Where to put the folder</legend>
          {LOCATIONS.map((l) => (
            <label key={l.id} className={location === l.id ? "selected" : ""}>
              <input type="radio" name="location" checked={location === l.id} onChange={() => setLocation(l.id)} />
              <span>
                <strong>{l.name}</strong>
                <small>{l.description}</small>
              </span>
            </label>
          ))}
        </fieldset>
      )}
      {done && (
        <div className="notice ok">
          <p>{platform === "macos" ? "The apps are ready." : "The shortcuts are on your desktop."} You are all set: have fun!</p>
          {done.paths.map((path) => (
            <code key={path}>{path}</code>
          ))}
        </div>
      )}
      {error && <pre className="notice error">{error}</pre>}

      {actions &&
        createPortal(
          <button className={done ? "" : "primary"} disabled={busy} onClick={create}>
            {busy ? "Adding…" : done ? "Add them again" : platform === "macos" ? "Create apps" : "Add shortcuts"}
          </button>,
          actions,
        )}
    </div>
  );
}
