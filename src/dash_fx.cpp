// NOS taillight streaks during a Dash.
//
// speed.exe v1.3: the sim side fills the car's render packet with +0x71 = InputControls.nos while the
// engine has nitrous left (0x00740824). The CarRenderConn update (0x007564C0, esi = conn, ebx = its
// CarRenderInfo at conn+0x44) copies it across every frame:
//   00756516 movzx edx, byte ptr [edi + 0x71]
//   0075651A mov dword ptr [ebx + 0x117C], edx
// and the light trail pass (0x00744FB1) draws the streaks from the brake light markers while
// CarRenderInfo+0x117C is set. The handling keeps NOS out of InputControls, so the copy is patched to
// also set it for the player's conn while a Dash runs. Only the visual is touched: no nitrous is used.
#include "dash_fx.h"

#include <windows.h>

#include <cstdint>
#include <cstring>

#include "log.h"
#include "patch.h"

namespace ctmw {

namespace {

constexpr std::uintptr_t kNosCopySite = 0x00756516;
constexpr std::uintptr_t kNosCopyResume = 0x00756520;
constexpr std::uint8_t kNosCopyBytes[] = {0x0F, 0xB6, 0x57, 0x71, 0x89, 0x93, 0x7C, 0x11, 0x00, 0x00};

void* g_player_conn = nullptr;
std::uint32_t g_dash_on = 0;
std::uintptr_t g_resume = 0;

__declspec(naked) void nos_copy_stub() {
    __asm {
        movzx edx, byte ptr [edi + 0x71]
        cmp esi, g_player_conn
        jne store
        or edx, g_dash_on
    store:
        mov dword ptr [ebx + 0x117C], edx
        jmp dword ptr [g_resume]
    }
}

}  // namespace

void dash_fx_set_player_conn(void* conn) { g_player_conn = conn; }

void dash_fx_set(bool on) { g_dash_on = on ? 1 : 0; }

bool dash_fx_install() {
    if (!bytes_match(kNosCopySite, kNosCopyBytes, sizeof kNosCopyBytes)) {
        log("dash_fx: NOS flag copy at %08x is not stock; no Dash streaks", static_cast<unsigned>(kNosCopySite));
        return false;
    }
    g_resume = va(kNosCopyResume);
    auto* p = reinterpret_cast<std::uint8_t*>(va(kNosCopySite));
    std::uint8_t code[sizeof kNosCopyBytes];
    std::memset(code, 0x90, sizeof code);
    code[0] = 0xE9;
    const auto rel = static_cast<std::int32_t>(reinterpret_cast<std::uintptr_t>(&nos_copy_stub) -
                                               (reinterpret_cast<std::uintptr_t>(p) + 5));
    std::memcpy(code + 1, &rel, 4);
    DWORD old;
    VirtualProtect(p, sizeof code, PAGE_EXECUTE_READWRITE, &old);
    std::memcpy(p, code, sizeof code);
    VirtualProtect(p, sizeof code, old, &old);
    FlushInstructionCache(GetCurrentProcess(), p, sizeof code);
    log("dash_fx: installed");
    return true;
}

}  // namespace ctmw
