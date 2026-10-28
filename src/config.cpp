#include "config.h"

#include <windows.h>

#include <cstdio>
#include <cstdlib>
#include <cwchar>

#include "log.h"

namespace ctmw {

Config g_config;

namespace {

const char kDefaultIni[] =
    "; Crazy Taxi Most Wanted\n"
    "; Delete this file to get the defaults back.\n"
    "\n"
    "[General]\n"
    "; 0 turns the whole mod off.\n"
    "Enable = 1\n"
    "; Draw the player's car as Axel's taxi (needs the CARS\\TAXI files from this mod).\n"
    "ModelSwap = 1\n"
    "; Enable the Crazy Taxi controls. F8 toggles it in game. Does not apply to Drag Races.\n"
    "Handling = 1\n"
    "\n"
    "[Controls]\n"
    "; To change taxi controls, rebind the following inputs in your game:\n"
    ";   D Gear: NOS\n"
    ";   R Gear: Handbrake\n"
    ";   Hop:    Speedbreaker\n"
    "\n"
    "; Handling on/off key, a Windows virtual-key code (decimal or 0x hex): F8=0x77.\n"
    "KeyToggle = 0x77\n"
    "\n"
    "[HUD]\n"
    "; Crazy Taxi's gear display, shown while the Crazy Taxi controls drive the car.\n"
    "GearDisplay = 1\n"
    "; Size, and distance from the bottom-right corner, in 1/480ths of the screen height.\n"
    "GearDisplaySize = 64\n"
    "GearDisplayRight = 32\n"
    "GearDisplayBottom = 32\n"
    "\n"
    "[Handling]\n"
    "; Speeds in mph (1 mph = 1.6 kmph), accelerations in mph/s.\n"
    "TopSpeed = 95\n"
    "Accel = 12.0\n"
    "Brake = 50.0\n"
    "\n"
    "YawRate = 4.0\n"
    "Grip = 7.5\n"
    "\n"
    "; Top speed and acceleration are multiplied for the length of a dash.\n"
    "; Effective top speed will depend on how long it takes to accelerate.\n"
    "DashTopSpeedMult = 1.2\n"
    "DashAccelMult = 5.0\n"
    "; Limit Cut is a dash that uses this top speed multiplier instead.\n"
    "LimitCutMult = 2.0\n"
    "\n"
    "DriftYawMult = 2.0\n"
    "DriftGrip = 2.5\n"
    "\n"
    "; Vertical speed in m/s\n"
    "HopSpeed = 10.0\n"
    "\n"
    "; More detailed tuning options can be added, see \"config.h\" in the source for a full list."
    ;

const wchar_t* g_path = nullptr;

bool read_bool(const wchar_t* sec, const wchar_t* key, bool def) {
    return GetPrivateProfileIntW(sec, key, def ? 1 : 0, g_path) != 0;
}

long read_int(const wchar_t* sec, const wchar_t* key, long def) {
    wchar_t buf[64];
    GetPrivateProfileStringW(sec, key, L"", buf, 64, g_path);
    if (!buf[0]) return def;
    return std::wcstol(buf, nullptr, 0);  // accepts 0x.. hex
}

void read_float(const wchar_t* key, float& v, const wchar_t* sec = L"Handling") {
    wchar_t buf[64];
    GetPrivateProfileStringW(sec, key, L"", buf, 64, g_path);
    if (buf[0]) v = static_cast<float>(std::wcstod(buf, nullptr));
}

void read_float_mph(const wchar_t* key, float& v, const wchar_t* sec = L"Handling") {
    const float kMPHtoMS = 0.447f;
    wchar_t buf[64];
    GetPrivateProfileStringW(sec, key, L"", buf, 64, g_path);
    if (buf[0]) v = static_cast<float>(std::wcstod(buf, nullptr)) * kMPHtoMS;
}

}  // namespace

void config_load(const wchar_t* path) {
    g_path = path;
    if (GetFileAttributesW(path) == INVALID_FILE_ATTRIBUTES) {
        if (std::FILE* f = _wfopen(path, L"w")) {
            std::fputs(kDefaultIni, f);
            std::fclose(f);
        }
    }
    Config& c = g_config;
    c.enable = read_bool(L"General", L"Enable", true);
    c.model_swap = read_bool(L"General", L"ModelSwap", true);
    c.handling = read_bool(L"General", L"Handling", true);
    c.debug_log = read_bool(L"General", L"DebugLog", false);
    read_float(L"WheelHeight", c.wheel_height, L"General");

    Bindings& b = c.bindings;
    b.key_toggle = read_int(L"Controls", L"KeyToggle", b.key_toggle);

    Hud& h = c.hud;
    h.gear_display = read_bool(L"HUD", L"GearDisplay", h.gear_display);
    read_float(L"GearDisplaySize", h.gear_size, L"HUD");
    read_float(L"GearDisplayRight", h.gear_right, L"HUD");
    read_float(L"GearDisplayBottom", h.gear_bottom, L"HUD");

    Tuning& t = c.tuning;
    read_float_mph(L"TopSpeed", t.top_speed);
    t.reverse_top_speed = t.top_speed * 0.3f;
    read_float_mph(L"ReverseTopSpeed", t.reverse_top_speed);
    read_float_mph(L"Accel", t.accel);
    t.reverse_accel = t.accel;
    read_float_mph(L"ReverseAccel", t.reverse_accel);
    read_float_mph(L"Brake", t.brake);
    read_float_mph(L"Coast", t.coast);
    read_float_mph(L"OverSpeedDecay", t.over_speed_decay);
    read_float(L"YawRate", t.yaw_rate);
    read_float(L"YawRampSpeed", t.yaw_ramp_speed);
    read_float(L"YawHighSpeedFalloff", t.yaw_high_speed_falloff);
    read_float(L"YawResponse", t.yaw_response);
    read_float(L"Grip", t.grip);
    read_float(L"GripRedirect", t.grip_redirect);
    read_float(L"DashTime", t.dash_time);
    read_float(L"DashCooldown", t.dash_cooldown);
    read_float(L"DashTopSpeedMult", t.dash_top_speed_mult);
    read_float(L"DashAccelMult", t.dash_accel_mult);
    read_float(L"DashWindow", t.dash_window);
    read_float(L"MinLimitCutDelay", t.min_limit_cut_delay);
    read_float(L"MaxLimitCutDelay", t.max_limit_cut_delay);
    read_float(L"LimitCutMult", t.limit_cut_mult);
    read_float(L"DriftGrip", t.drift_grip);
    read_float(L"DriftYawMult", t.drift_yaw_mult);
    read_float(L"DriftRedirect", t.drift_redirect);
    read_float(L"CrazyStopMult", t.crazy_stop_mult);
    read_float(L"HopSpeed", t.hop_speed);
    read_float(L"HopCooldown", t.hop_cooldown);

    log("config: Enable=%d ModelSwap=%d Handling=%d TopSpeed=%.1f", c.enable, c.model_swap,
        c.handling, t.top_speed);
}

}  // namespace ctmw
