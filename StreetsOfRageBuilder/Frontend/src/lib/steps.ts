export interface StepDefinition {
  id: string;
  title: string;
  summary: string;
}

export interface StepProps {
  /** The step tells the wizard whether Next may be enabled. */
  setReady: (ready: boolean) => void;
}

export const STEPS: StepDefinition[] = [
  { id: "dependencies", title: "Dependencies", summary: "Check the build tools and install what is missing." },
  { id: "clone", title: "Download project", summary: "Clone Streets of Rage Project, with its submodules, into a folder." },
  { id: "rom", title: "ROM", summary: "Choose your ROM file; its CRC is verified before continuing." },
  { id: "sound", title: "Extract sound", summary: "Render the soundtrack from the ROM." },
  { id: "build", title: "Build", summary: "Generate the C++ and compile the game and its dependencies." },
  { id: "shortcut", title: "Shortcut", summary: "Add a shortcut that launches scripts/play.py." },
];
