#pragma once

#include <string>

struct AudioHeadlessOptions {
    std::string wavPath;
};

int runAudioHeadlessTest(const AudioHeadlessOptions &options);
