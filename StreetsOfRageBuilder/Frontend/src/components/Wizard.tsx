"use client";

import { useEffect, useState } from "react";
import { STEPS } from "@/lib/steps";
import { platformInfo, type PlatformInfo } from "@/lib/tauri";

export function Wizard() {
  const [index, setIndex] = useState(0);
  const [platform, setPlatform] = useState<PlatformInfo | null>(null);
  const step = STEPS[index];

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
          {platform ? `${platform.platform} · ${platform.packageManager ?? "no package manager"}` : "not running in Tauri"}
        </p>
      </aside>
      <section className="content">
        <h2>{step.title}</h2>
        <p>{step.summary}</p>
        <div className="placeholder">Step “{step.id}” is not implemented yet.</div>
        <footer>
          <button disabled={index === 0} onClick={() => setIndex(index - 1)}>
            Back
          </button>
          <button className="primary" disabled={index === STEPS.length - 1} onClick={() => setIndex(index + 1)}>
            Next
          </button>
        </footer>
      </section>
    </main>
  );
}
