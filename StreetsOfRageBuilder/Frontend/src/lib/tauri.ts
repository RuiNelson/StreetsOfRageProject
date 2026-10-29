import { invoke } from "@tauri-apps/api/core";

export type Platform = "windows" | "macos" | "linux";

export interface PlatformInfo {
  platform: Platform;
  /** winget, brew or apt; null when the platform's package manager is missing. */
  packageManager: string | null;
}

export const platformInfo = () => invoke<PlatformInfo>("platform_info");
