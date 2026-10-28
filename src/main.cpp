// Crazy Taxi Most Wanted: Axel's taxi from Crazy Taxi 3 for NFS Most Wanted (2005) v1.3.
// Loaded by the Ultimate ASI Loader from NFS Most Wanted\scripts\CrazyTaxiMW.asi.
#include <windows.h>

#include <cstring>
#include <string>

#include "config.h"
#include "crashlog.h"
#include "dash_fx.h"
#include "gear_hud.h"
#include "handling.h"
#include "log.h"
#include "model_swap.h"
#include "patch.h"

namespace {

std::wstring module_dir(HMODULE self) {
    wchar_t buf[MAX_PATH];
    const DWORD n = GetModuleFileNameW(self, buf, MAX_PATH);
    std::wstring s(buf, n);
    return s.substr(0, s.find_last_of(L"\\/") + 1);
}

// "Need for Speed Most Wanted" v1.3 has this PE timestamp; anything else gets left alone.
constexpr DWORD kSpeedV13Timestamp = 0x438E4C8C;

bool is_speed_v13() {
    const auto* base = reinterpret_cast<const std::uint8_t*>(GetModuleHandleW(nullptr));
    const auto* dos = reinterpret_cast<const IMAGE_DOS_HEADER*>(base);
    const auto* nt = reinterpret_cast<const IMAGE_NT_HEADERS32*>(base + dos->e_lfanew);
    return nt->FileHeader.TimeDateStamp == kSpeedV13Timestamp;
}

void init(HMODULE self) {
    const std::wstring dir = module_dir(self);
    ctmw::log_open((dir + L"CrazyTaxiMW.log").c_str());
    ctmw::log("Crazy Taxi Most Wanted starting");
    ctmw::crashlog_install();
    if (!is_speed_v13()) {
        ctmw::log("speed.exe is not v1.3; mod disabled");
        return;
    }
    ctmw::config_load((dir + L"CrazyTaxiMW.ini").c_str());
    if (!ctmw::g_config.enable) return;
    // The model swap's hooks also find the player's render conn for the Dash streaks; with ModelSwap = 0
    // they leave the car alone.
    if ((ctmw::g_config.model_swap || ctmw::g_config.handling) && !ctmw::model_swap_install())
        ctmw::log("model swap not installed");
    if (ctmw::g_config.handling) {
        if (!ctmw::handling_install()) ctmw::log("handling not installed");
        ctmw::dash_fx_install();
        ctmw::gear_hud_install();
    }
}

}  // namespace

BOOL WINAPI DllMain(HMODULE self, DWORD reason, LPVOID) {
    if (reason == DLL_PROCESS_ATTACH) {
        DisableThreadLibraryCalls(self);
        // Call-site patches only, no loader-lock-sensitive work: safe to do here, before the game runs.
        init(self);
    }
    return TRUE;
}
