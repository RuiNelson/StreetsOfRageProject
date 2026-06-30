#include "ControlsConfigStore.hpp"
#include <fstream>
#include <yaml-cpp/yaml.h>

static constexpr const char *YAML_PATH = "controls.yaml";

// ─── YAML serialization ───────────────────────────────────────────────────────

static YAML::Node playerToNode(const PlayerConfiguration &p) {
    YAML::Node n;
    n["enabled"]      = p.enabled;
    n["device"]       = static_cast<int>(p.deviceType);
    n["gamepad_guid"] = p.gamepadGuid;
    n["gamepad_name"] = p.gamepadName;

    YAML::Node bindings;
    for (const auto &b : p.bindings)
        bindings.push_back(b);
    n["bindings"] = bindings;

    return n;
}

static PlayerConfiguration nodeToPlayer(const YAML::Node &n) {
    PlayerConfiguration p;
    p.enabled     = n["enabled"].as<bool>(false);
    p.deviceType  = static_cast<InputDevice>(n["device"].as<int>(0));
    p.gamepadGuid = n["gamepad_guid"].as<std::string>("");
    p.gamepadName = n["gamepad_name"].as<std::string>("");

    for (const auto &item : n["bindings"])
        p.bindings.push_back(item.as<std::string>());

    return p;
}

// ─── Defaults ─────────────────────────────────────────────────────────────────

static void applyDefaults(PlayerConfiguration &p1, PlayerConfiguration &p2) {
    p1.enabled    = true;
    p1.deviceType = InputDevice::Keyboard;
    p1.bindings   = {"Up@Up", "Down@Down", "Left@Left", "Right@Right", "A@Z", "B@X", "C@C", "Start@V"};

    p2.enabled    = false;
    p2.deviceType = InputDevice::Keyboard;
}

// ─── ControlsConfigStore ──────────────────────────────────────────────────────

ControlsConfigStore::ControlsConfigStore() {
    try {
        YAML::Node root = YAML::LoadFile(YAML_PATH);
        player1         = nodeToPlayer(root["player1"]);
        player2         = nodeToPlayer(root["player2"]);
    } catch (...) {
        applyDefaults(player1, player2);
    }
}

void ControlsConfigStore::save() {
    YAML::Node root;
    root["player1"] = playerToNode(player1);
    root["player2"] = playerToNode(player2);

    std::ofstream out(YAML_PATH);
    out << root;
}
