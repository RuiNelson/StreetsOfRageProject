import { Channel, invoke } from "@tauri-apps/api/core";
import type { Target } from "./steps";

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
  /** Pages to get it from, when the app cannot install it. */
  links: { name: string; url: string; note: string }[];
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
export const checkDependencies = (target: Target) => invoke<DependenciesReport>("check_dependencies", { target });
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

export type ShortcutLocation = "applications" | "home";

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

// The PS5 target: the same project built for the console inside a container.

export interface Title {
  folder: string;
  /** Built from an older version of the project: build it again. */
  outdated: boolean;
}

export interface ZipFile {
  path: string;
  size: number;
}

const withProgress = <T>(command: string, args: Record<string, unknown>, onProgress: (line: string) => void) => {
  const progress = new Channel<string>();
  progress.onmessage = onProgress;
  return invoke<T>(command, { ...args, progress });
};

/** The PS5 title already built in the project, or null. */
export const ps5TitleStatus = (project: string) => invoke<Title | null>("ps5_title_status", { project });
/** Renders the soundtrack inside the container (minutes). */
export const ps5RenderSoundtrack = (project: string, chip: Chip, onProgress: (line: string) => void) =>
  withProgress<Soundtrack>("ps5_render_soundtrack", { project, chip }, onProgress);
/** Generates the C++ and compiles the PS5 title inside the container (a long time). */
export const ps5Build = (project: string, onProgress: (line: string) => void) =>
  withProgress<Title>("ps5_build", { project }, onProgress);
/** Writes the two ZIP files into `folder`. */
export const ps5MakeZips = (project: string, folder: string, onProgress: (line: string) => void) =>
  withProgress<ZipFile[]>("ps5_make_zips", { project, folder }, onProgress);
/** Resolves when the console's FTP server answers; rejects with why not. */
export const ps5ProbeConsole = (host: string, port: string) => invoke<void>("ps5_probe_console", { host, port });
/** Sends everything to the console; resolves with the number of files. */
export const ps5Upload = (project: string, host: string, port: string, onProgress: (line: string) => void) =>
  withProgress<number>("ps5_upload", { project, host, port }, onProgress);
/** Removes the container image, the build volume and the built title; resolves with what went. */
export const ps5CleanUp = (project: string) => invoke<string[]>("ps5_clean_up", { project });
