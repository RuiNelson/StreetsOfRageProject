"use client";

import { useEffect, useState } from "react";
import type { StepProps, Target } from "@/lib/steps";
import { platformInfo, type Platform } from "@/lib/tauri";

const SYSTEM: Record<Platform, string> = { windows: "Windows", macos: "macOS", linux: "Linux" };

export function TargetStep({ target, setTarget, setReady }: StepProps) {
  const [platform, setPlatform] = useState<Platform | null>(null);

  useEffect(() => setReady(true), [setReady]);
  useEffect(() => {
    platformInfo().then((info) => setPlatform(info.platform)).catch(() => {});
  }, []);

  const targets: { id: Target; name: string; description: string }[] = [
    {
      id: "local",
      name: platform ? `This computer (${SYSTEM[platform]})` : "This computer",
      description: "Builds the game with the compiler on this computer, and adds a shortcut to play it.",
    },
    {
      id: "ps5",
      name: "PlayStation 5 (Prospero)",
      description:
        "Cross-compiles a title for a console with homebrew enabled, inside a container. Needs only git and a container engine (Docker, OrbStack or Podman), and about 12 GB of free disk space.",
    },
  ];

  return (
    <fieldset className="chips">
      <legend>Build for</legend>
      {targets.map((t) => (
        <label key={t.id} className={target === t.id ? "selected" : ""}>
          <input type="radio" name="target" checked={target === t.id} onChange={() => setTarget(t.id)} />
          <span>
            <strong>{t.name}</strong>
            <small>{t.description}</small>
          </span>
        </label>
      ))}
    </fieldset>
  );
}
