"use client";

import { useCallback, useEffect, useState } from "react";
import { STEPS } from "@/lib/steps";
import { platformInfo, type PlatformInfo } from "@/lib/tauri";
import { Dependencies } from "./steps/Dependencies";
import { Placeholder } from "./steps/Placeholder";

export function Wizard() {
  const [index, setIndex] = useState(0);
  const [platform, setPlatform] = useState<PlatformInfo | null>(null);
  const [ready, setReadyState] = useState(false);
  const step = STEPS[index];
  // A step must report ready again every time it is shown.
  const setReady = useCallback((value: boolean) => setReadyState(value), []);
  const go = (to: number) => {
    setReadyState(false);
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
          {step.id === "dependencies" ? (
            <Dependencies key={step.id} setReady={setReady} />
          ) : (
            <Placeholder key={step.id} id={step.id} setReady={setReady} />
          )}
        </div>
        <footer>
          <button disabled={index === 0} onClick={() => go(index - 1)}>
            Back
          </button>
          <button className="primary" disabled={!ready || index === STEPS.length - 1} onClick={() => go(index + 1)}>
            Next
          </button>
        </footer>
      </section>
    </main>
  );
}
