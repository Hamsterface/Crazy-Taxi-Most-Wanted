// speed.exe v1.3: FEDatabase (cFrontendDatabase*) is at 0x0091CF90, and its +0x10 is the current UserProfile*.
// The profile's PlayerSettings[2] start at +0x80, 0x14 bytes each (MWSDK Types/UserProfile.h, reference
// confidence). Checked against the game: the options screen handlers take the address of
// [profile + player * 0x14 + 0x91] (0x0051C5AD, Transmission) and + 0x80 (0x0051C9FD, Gauges), and the race code
// tests the Transmission byte for 0 = Automatic (0x007A4140).
#include "player_settings.h"

#include <cstdint>

#include "log.h"
#include "patch.h"

namespace ctmw {

namespace {

constexpr std::uintptr_t kFEDatabase = 0x0091CF90;
constexpr std::ptrdiff_t kFEDatabaseUserProfile = 0x10;
constexpr std::ptrdiff_t kProfileGaugesOn = 0x80;      // bool
constexpr std::ptrdiff_t kProfileTransmission = 0x91;  // eTransmissionType: Automatic, Manual, Sport, ManualClutch
constexpr std::uint8_t kAutomatic = 0;

bool g_gauges_saved = false;
std::uint8_t g_saved_gauges = 0;  // the player's own Gauges setting, while the gear display hides the gauges

}  // namespace

void player_settings_force(bool gear_display_shown) {
    auto* db = *reinterpret_cast<std::uint8_t**>(va(kFEDatabase));
    if (!db) return;
    auto* profile = *reinterpret_cast<std::uint8_t**>(db + kFEDatabaseUserProfile);
    if (!profile) return;
    std::uint8_t& transmission = profile[kProfileTransmission];
    if (transmission != kAutomatic) {
        log("player_settings: Transmission %u -> %u", transmission, kAutomatic);
        transmission = kAutomatic;
    }

    std::uint8_t& gauges = profile[kProfileGaugesOn];
    if (gear_display_shown && !g_gauges_saved) {
        g_saved_gauges = gauges;
        g_gauges_saved = true;
        gauges = 0;
    } else if (!gear_display_shown && g_gauges_saved) {
        gauges = g_saved_gauges;
        g_gauges_saved = false;
    }
}

}  // namespace ctmw
