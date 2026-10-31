export interface StepDefinition {
  id: string;
  title: string;
  summary: string;
}

export interface StepProps {
  /** The step tells the wizard whether Next may be enabled. */
  setReady: (ready: boolean) => void;
  /** A step that runs something long sets this, so Back and Next stay disabled meanwhile. */
  setBusy: (busy: boolean) => void;
  /** The wizard footer, left of Next: a step puts its action buttons there with a portal. */
  actions: HTMLElement | null;
  /** Where step 2 put the project; null until it has. */
  projectPath: string | null;
  setProjectPath: (path: string | null) => void;
}

export const STEPS: StepDefinition[] = [
  { id: "dependencies", title: "Install Tools", summary: "Check the build tools and install what is missing." },
  { id: "clone", title: "Download Source", summary: "Clone Streets of Rage Project, with its submodules, into a folder." },
  { id: "rom", title: "Copy ROM", summary: "Choose your ROM file; its CRC is verified before continuing." },
  { id: "sound", title: "Pre-render Soundtrack", summary: "Render the soundtrack from the ROM." },
  { id: "build", title: "Build Executable", summary: "Generate the C++ and compile the game and its dependencies." },
  { id: "shortcut", title: "Create Shortcut", summary: "Add the game and its launcher (scripts/play.py)." },
];
