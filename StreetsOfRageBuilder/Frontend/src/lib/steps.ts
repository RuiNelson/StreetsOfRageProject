export interface StepDefinition {
  id: string;
  title: string;
  summary: string;
}

/** What the wizard builds: the game for this computer, or the title for the PS5 (in a container). */
export type Target = "local" | "ps5";

export interface StepProps {
  /** What was chosen in the first step. */
  target: Target;
  setTarget: (target: Target) => void;
  /** The step tells the wizard whether Next may be enabled. */
  setReady: (ready: boolean) => void;
  /** A step that runs something long sets this, so Back and Next stay disabled meanwhile. */
  setBusy: (busy: boolean) => void;
  /** The wizard footer, left of Next: a step puts its action buttons there with a portal. */
  actions: HTMLElement | null;
  /** Where step 3 put the project; null until it has. */
  projectPath: string | null;
  setProjectPath: (path: string | null) => void;
}

const PROJECT_AND_ROM: StepDefinition[] = [
  { id: "clone", title: "Download Source", summary: "Clone Streets of Rage Project, with its submodules, into a folder." },
  { id: "rom", title: "Copy ROM", summary: "Choose your ROM file; its CRC is verified before continuing." },
];

const TARGET: StepDefinition = { id: "target", title: "Choose Target", summary: "Build the game for this computer, or for the PlayStation 5." };

/** The steps in order; the first is the same for both targets, and the shared ones keep their position. */
export const stepsFor = (target: Target): StepDefinition[] =>
  target === "ps5"
    ? [
        TARGET,
        { id: "dependencies", title: "Install Tools", summary: "Check git and the container engine the PS5 build runs in." },
        ...PROJECT_AND_ROM,
        { id: "sound", title: "Pre-render Soundtrack", summary: "Render the soundtrack from the ROM, in the container." },
        { id: "build", title: "Build for PS5", summary: "Generate the C++ and compile the title with the PS5 toolchain, in the container." },
        { id: "deliver", title: "Send to PS5", summary: "Make the ZIP files, or send the files to the console over FTP." },
        { id: "cleanup", title: "Clean Up", summary: "Remove the container image and the built title." },
      ]
    : [
        TARGET,
        { id: "dependencies", title: "Install Tools", summary: "Check the build tools and install what is missing." },
        ...PROJECT_AND_ROM,
        { id: "sound", title: "Pre-render Soundtrack", summary: "Render the soundtrack from the ROM." },
        { id: "build", title: "Build Executable", summary: "Generate the C++ and compile the game and its dependencies." },
        { id: "shortcut", title: "Create Shortcut", summary: "Add the game and its launcher (scripts/play.py)." },
      ];
