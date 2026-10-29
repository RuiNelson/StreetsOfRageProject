"use client";

import { useEffect, useRef } from "react";

/** The last lines of a long-running script, with a bar when asked and the lines carry a percentage. */

const KEPT = 6;

export const appendLine = (lines: string[], line: string) => [...lines.slice(-(KEPT - 1)), line];

/** `[ 45%]` (Makefiles) or `[12/340]` (Ninja), from the latest line that has one. */
function percent(lines: string[]): number | null {
  for (const line of [...lines].reverse()) {
    const pct = /^\[\s*(\d+)%\]/.exec(line);
    if (pct) return Number(pct[1]);
    const count = /^\[(\d+)\/(\d+)\]/.exec(line);
    if (count && Number(count[2]) > 0) return Math.round((100 * Number(count[1])) / Number(count[2]));
  }
  return null;
}

export function Progress({ lines, bar = true }: { lines: string[]; /** Off when the percentages describe something else than the step's work. */ bar?: boolean }) {
  const value = bar ? percent(lines) : null;
  const box = useRef<HTMLDivElement>(null);
  // It appears below the fold in a small window: bring it into view when the work starts.
  useEffect(() => {
    box.current?.scrollIntoView({ block: "end" });
  }, []);
  return (
    <div className="notice progress" ref={box}>
      {value !== null && (
        <div className="bar" role="progressbar" aria-valuenow={value} aria-valuemin={0} aria-valuemax={100}>
          <div style={{ width: `${value}%` }} />
        </div>
      )}
      {lines.map((line, i) => (
        <div key={i}>{line}</div>
      ))}
    </div>
  );
}
