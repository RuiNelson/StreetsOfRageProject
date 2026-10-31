import { Channel, invoke } from "@tauri-apps/api/core";

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

/** Ends the wizard (the last step's Finish). */
export const finish = () => invoke<void>("finish");
export const platformInfo = () => invoke<PlatformInfo>("platform_info");
export const checkDependencies = () => invoke<DependenciesReport>("check_dependencies");
/** Resolves with notes to show; rejects with the failure text. */
export const installDependencies = (ids: string[]) => invoke<string[]>("install_dependencies", { ids });

export interface Inspection {
  /** The chosen folder. */
  path: string;
  state: "missing" | "empty" | "clone" | "occupied";
}

export interface Downloaded {
  path: string;
  updated: boolean;
  commit: string;
}

export const inspectProject = (folder: string) => invoke<Inspection>("inspect_project", { folder });
/** Clones (or updates) the project; `onProgress` gets git's progress lines. */
export const downloadProject = (folder: string, onProgress: (line: string) => void) => {
  const progress = new Channel<string>();
  progress.onmessage = onProgress;
  return invoke<Downloaded>("download_project", { folder, progress });
};

export interface RomReport {
  fileName: string;
  size: number;
  /** Eight hex digits (empty when the file was too big to read). */
  crc: string;
  /** ok: right dump, copied into the project; smd: needs converting; mismatch: not the game or another version. */
  state: "ok" | "smd" | "mismatch";
}

/** Verifies the ROM and, when it is the right one, copies it into the project. */
export const verifyRom = (rom: string, project: string) => invoke<RomReport>("use_rom", { rom, project });
/** The right ROM already in the project, or null. */
export const installedRom = (project: string) => invoke<RomReport | null>("installed_rom", { project });

export interface Soundtrack {
  folder: string;
  files: number;
  /** Rendered by an older version of the renderer: render it again. */
  outdated: boolean;
}

/** The finished soundtrack already in the project, or null (`outdated` when the renderer changed since). */
export const soundtrackStatus = (project: string) => invoke<Soundtrack | null>("soundtrack_status", { project });
/** Renders the soundtrack from the ROM (minutes); `onProgress` gets the renderer's output lines. */
export type Chip = "ym3438" | "ym2612";
export const extractSound = (project: string, chip: Chip, onProgress: (line: string) => void) => {
  const progress = new Channel<string>();
  progress.onmessage = onProgress;
  return invoke<Soundtrack>("extract_sound", { project, chip, progress });
};

export interface Game {
  executable: string;
  /** Built from an older version of the project: build it again. */
  outdated: boolean;
}

/** The game already built in the project, or null (`outdated` when the project was updated since). */
export const gameStatus = (project: string) => invoke<Game | null>("game_status", { project });
/** Generates the C++ and compiles the game (many minutes); `onProgress` gets the build output lines. */
export const buildGame = (project: string, onProgress: (line: string) => void) => {
  const progress = new Channel<string>();
  progress.onmessage = onProgress;
  return invoke<Game>("build_game", { project, progress });
};

export type ShortcutLocation = "applications" | "desktop";

export interface Shortcut {
  /** What the user finds: the game, then the Launcher. */
  paths: string[];
  /** macOS only. */
  location: ShortcutLocation | null;
}

/** The game's and the Launcher's shortcuts; on macOS, the two bundles in `location`. */
export const createShortcut = (project: string, location: ShortcutLocation | null) =>
  invoke<Shortcut>("create_shortcut", { project, location });
/** The shortcuts already made, or null. */
export const shortcutStatus = () => invoke<Shortcut | null>("shortcut_status");
