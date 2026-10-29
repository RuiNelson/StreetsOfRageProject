import { invoke } from "@tauri-apps/api/core";

export type Platform = "windows" | "macos" | "linux";

export interface PlatformInfo {
  platform: Platform;
  packageManager: "winget" | "brew" | "apt";
}

export interface Dependency {
  id: string;
  name: string;
  description: string;
  state: "ok" | "missing" | "unknown";
  detail: string | null;
  installable: boolean;
}

export interface Manager {
  name: string;
  available: boolean;
  helpUrl: string | null;
  message: string | null;
  /** Linux without apt: Debian package names to install by hand. */
  manualPackages: string[];
}

export interface DependenciesReport {
  manager: Manager;
  dependencies: Dependency[];
  ready: boolean;
}

export const platformInfo = () => invoke<PlatformInfo>("platform_info");
export const checkDependencies = () => invoke<DependenciesReport>("check_dependencies");
/** Resolves with notes to show; rejects with the failure text. */
export const installDependencies = (ids: string[]) => invoke<string[]>("install_dependencies", { ids });
