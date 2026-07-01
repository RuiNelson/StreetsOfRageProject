#include "Sor.hpp"
#include "config/controls/ControlsConfigUI.hpp"
#include "runtime_tests/controllers/TestControllers.hpp"
#include <CLI/CLI.hpp>
#include <SDL3/SDL.h>
#include <runtime_tests/TestFontPNG.hpp>
#include <runtime_tests/TestFontSDL.hpp>
#include <runtime_tests/sound/AudioHeadlessTest.hpp>
#include <runtime_tests/sound/TestSound.hpp>
#include <runtime_tests/vdp_tests/TestVDP.hpp>
#include <string>

int main(int argc, char *argv[]) {
    CLI::App app{"MegaDrive Environment"};
    app.set_version_flag("-V,--version", "0.1.0");

    bool        testFontSDLFlag       = false;
    bool        testFontPNGFlag       = false;
    bool        testVDPFlag           = false;
    bool        testControllersFlag   = false;
    bool        testSoundFlag         = false;
    bool        testAudioHeadlessFlag = false;
    bool        configControlsFlag    = false;
    bool        runSorFlag            = false;
    bool        sorDebugFlag          = false;
    bool        sorFastFlag           = false;
    bool        silentFlag            = false;
    int         sorVSyncMode          = 0; // 0 = internal timer (default); 1/2/3 = VSync/VSync2/VSync3
    std::string sorRomPath            = "rom/SOR.bin";
    std::string sorAuxAddrFile; // if set, record unknown dispatch targets here
    std::string audioWavPath;
    std::string languagePin = "jp";
    std::string videoHz     = "60";

    app.add_flag("--testFontSDL", testFontSDLFlag, "3D rotating cube with glyphs on faces (SDL window)");
    app.add_flag("--testFontPNG", testFontPNGFlag, "Font PNG export with artistic effects");
    app.add_flag("--testVDP", testVDPFlag, "VDP emulator test suite — 18 tests, exports PNGs");
    app.add_flag("--testControllers", testControllersFlag, "Interactive controller readout via VDP display");
    app.add_flag("--testSound", testSoundFlag, "YM2612/PSG audio output + Z80 CPU test");
    app.add_flag("--testAudioHeadless", testAudioHeadlessFlag, "Headless YM2612/PSG/Z80 audio regression tests");
    app.add_option("--writeAudioWav", audioWavPath, "With --testAudioHeadless: write a 48 kHz stereo diagnostic WAV");
    app.add_flag("--silent", silentFlag, "Disable audio output entirely (chip writes are dropped)");
    app.add_flag("--configControls", configControlsFlag, "Open controller configuration UI");
    app.add_option("--lang", languagePin, "Console language pin: jp=low/Japanese, en=high/overseas")
        ->capture_default_str()
        ->check(CLI::IsMember({"jp", "en"}));
    app.add_option("--hz", videoHz, "Console video frequency pin: 60=low/NTSC, 50=high/PAL")
        ->capture_default_str()
        ->check(CLI::IsMember({"60", "50"}));
    app.add_flag("--runSor", runSorFlag, "Run the recompiled Streets of Rage cartridge");
    app.add_flag("--debug", sorDebugFlag, "With --runSor: log CPU/VDP state once per second");
    app.add_flag("--fast", sorFastFlag, "With --runSor: disable CPU pacing (faster bring-up)");
    app.add_option("--vsync",
                   sorVSyncMode,
                   "With --runSor: frame sync — 0=internal timer from --hz (default), "
                   "1=VSync, 2=VSync2 (½ rate), 3=VSync3 (⅓ rate)")
        ->capture_default_str()
        ->check(CLI::Range(0, 3));
    app.add_option("--rom", sorRomPath, "ROM path for --runSor")->capture_default_str();
    app.add_option("--auxAddrFile",
                   sorAuxAddrFile,
                   "With --runSor: on an indirect dispatch to an unknown address, append it to "
                   "this aux file and exit (42) instead of aborting — for the discovery loop");

    CLI11_PARSE(app, argc, argv);

    auto configureEnvironment = [&](MegaDriveEnvironment &env) {
        env.setLanguagePin(languagePin == "en" ? MegaDriveEnvironment::LanguagePin::Overseas
                                               : MegaDriveEnvironment::LanguagePin::Japanese);
        env.setVideoStandard(videoHz == "50" ? MegaDriveEnvironment::VideoStandard::Hz50
                                             : MegaDriveEnvironment::VideoStandard::Hz60);
        if (silentFlag)
            env.sound().disable();
    };

    if (testAudioHeadlessFlag || !audioWavPath.empty()) {
        return runAudioHeadlessTest({audioWavPath});
    }
    if (configControlsFlag) {
        runControlsConfig();
    }
    if (testFontSDLFlag) {
        testFontSDL();
    }
    if (testFontPNGFlag) {
        testFontPNG();
    }
    if (testVDPFlag) {
        VDPTester tester;
        configureEnvironment(tester);
        tester.boot();
    }
    if (testControllersFlag) {
        TestControllers tester;
        configureEnvironment(tester);
        tester.boot();
    }
    if (testSoundFlag) {
        TestSound tester;
        configureEnvironment(tester);
        tester.boot();
    }
    if (runSorFlag) {
        Sor sor(sorRomPath, static_cast<VDP::Synchronization>(sorVSyncMode));
        configureEnvironment(sor);
        sor.setDebugLog(sorDebugFlag);
        sor.setFastMode(sorFastFlag);
        if (!sorAuxAddrFile.empty()) {
            sor.setAuxAddrFile(sorAuxAddrFile);
        }
        sor.boot();
    }

    return 0;
}
