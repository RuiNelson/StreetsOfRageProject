"use client";

import { useEffect } from "react";
import type { StepProps } from "@/lib/steps";

export function Placeholder({ id, setReady }: StepProps & { id: string }) {
  useEffect(() => setReady(true), [setReady]);
  return <div className="placeholder">Step “{id}” is not implemented yet.</div>;
}
