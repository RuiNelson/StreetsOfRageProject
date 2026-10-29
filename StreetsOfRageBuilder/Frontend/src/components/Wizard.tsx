"use client";

import { useCallback, useEffect, useState } from "react";
import { STEPS, type StepProps } from "@/lib/steps";
import { finish, platformInfo, type PlatformInfo } from "@/lib/tauri";
import { Dependencies } from "./steps/Dependencies";
import { Download } from "./steps/Download";
import { Rom } from "./steps/Rom";
import { ShortcutStep } from "./steps/ShortcutStep";
import { Build } from "./steps/Build";
import { ExtractSound } from "./steps/ExtractSound";

const COMPONENTS: Record<string, (props: StepProps) => React.ReactNode> = {
  dependencies: Dependencies,
  clone: Download,
  rom: Rom,
  sound: ExtractSound,
  build: Build,
  shortcut: ShortcutStep,
};

export function Wizard() {
  const [index, setIndex] = useState(0);
  const [platform, setPlatform] = useState<PlatformInfo | null>(null);
  const [ready, setReadyState] = useState(false);
  const [busy, setBusy] = useState(false);
  const [actions, setActions] = useState<HTMLElement | null>(null);
  const [projectPath, setProjectPath] = useState<string | null>(null);
  const step = STEPS[index];
  const Step = COMPONENTS[step.id];
  // A step must report ready again every time it is shown.
  const setReady = useCallback((value: boolean) => setReadyState(value), []);
  const shared = { setReady, setBusy, actions, projectPath, setProjectPath };
  const go = (to: number) => {
    setReadyState(false);
    setBusy(false);
    setIndex(to);
  };

  useEffect(() => {
    platformInfo().then(setPlatform).catch(() => setPlatform(null));
  }, []);

  return (
    <main className="wizard">
      <aside className="sidebar">
        <h1>Streets of Rage Builder</h1>
        <ol>
          {STEPS.map((s, i) => (
            <li key={s.id} className={i === index ? "current" : i < index ? "done" : ""}>
              <span className="badge">{i < index ? "✓" : i + 1}</span>
              {s.title}
            </li>
          ))}
        </ol>
        <p className="platform">
          {platform ? `${platform.platform} · ${platform.packageManager}` : "not running in Tauri"}
        </p>
      </aside>
      <section className="content">
        <h2>{step.title}</h2>
        <p>{step.summary}</p>
        <div className="step-body">
          <Step key={step.id} {...shared} />
        </div>
        <footer>
          <button disabled={busy || index === 0} onClick={() => go(index - 1)}>
            Back
          </button>
          <div className="footer-right">
            <div className="step-actions" ref={setActions} />
            <button
              className="primary"
              disabled={busy || !ready}
              onClick={() => (index === STEPS.length - 1 ? finish().catch(() => {}) : go(index + 1))}
            >
              {index === STEPS.length - 1 ? "Finish" : "Next"}
            </button>
          </div>
        </footer>
      </section>
    </main>
  );
}
