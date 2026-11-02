"use client";

import { useEffect, useRef } from "react";

/** The whole output of a long-running script, scrolling as it grows, with a bar when asked and the lines carry a percentage. */

/** A build prints tens of thousands of lines at most; this only keeps a runaway script from filling memory. */
const KEPT = 5000;

export const appendLine = (lines: string[], line: string) => [...lines.slice(-(KEPT - 1)), line];

/** `[ 45%]` (Makefiles) or `[12/340]` (Ninja), from the latest line that has one. */
function percent(lines: string[]): number | null {
  for (let i = lines.length - 1; i >= 0; i--) {
    const pct = /^\[\s*(\d+)%\]/.exec(lines[i]);
    if (pct) return Number(pct[1]);
    const count = /^\[(\d+)\/(\d+)\]/.exec(lines[i]);
    if (count && Number(count[2]) > 0) return Math.round((100 * Number(count[1])) / Number(count[2]));
  }
  return null;
}

export function Progress({ lines, bar = true }: { lines: string[]; /** Off when the percentages describe something else than the step's work. */ bar?: boolean }) {
  const value = bar ? percent(lines) : null;
  const box = useRef<HTMLDivElement>(null);
  const log = useRef<HTMLDivElement>(null);
  // Follow the output unless the user has scrolled up to read; scrolling back to the end resumes following.
  const following = useRef(true);
  // It appears below the fold in a small window: bring it into view when the work starts.
  useEffect(() => {
    box.current?.scrollIntoView({ block: "end" });
  }, []);
  useEffect(() => {
    const el = log.current;
    if (el && following.current) el.scrollTop = el.scrollHeight;
  }, [lines]);
  return (
    <div className="notice progress" ref={box}>
      {value !== null && (
        <div className="bar" role="progressbar" aria-valuenow={value} aria-valuemin={0} aria-valuemax={100}>
          <div style={{ width: `${value}%` }} />
        </div>
      )}
      <div
        className="log"
        ref={log}
        onScroll={(e) => {
          const el = e.currentTarget;
          following.current = el.scrollHeight - el.scrollTop - el.clientHeight < 24;
        }}
      >
        {lines.map((line, i) => (
          <div key={i}>{line}</div>
        ))}
      </div>
    </div>
  );
}
