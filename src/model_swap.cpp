// Render-side car swap.
//
// speed.exe v1.3, CarRenderConn factory (0x0075E6C0):
//   edi = info            ; [info+0x04] model hash, [info+0x0C] CarRenderUsage, [info+0x10] FECustomizationRecord*
//   0075E6E3 mov ecx, 0x9B26A8
//   0075E6E8 call 0x007398D0  ; thiscall CarType lookup(hash) -> CarType or -1
//   ...       new CarRenderConn(pkt, type, info)  (0x0075D320)
// CarRenderConn ctor stores the type at [this+0x2C] (base ctor 0x007591C0), runs the per-wheel setup,
// then builds the RideInfo:
//   0075D695 call 0x0075D220  ; thiscall SetupRide(a1, usage, bool, customization), ret 0x10
//     -> RideInfo::Init(type, usage) (0x00739A70), RideInfo::SetStockParts (0x007594A0),
//        and if customization != null, FECustomizationRecord::WriteRecordIntoRide (0x0056F2B0).
//
// Hook 1 swaps the type to TAXI for the player before the ctor sees it.
// Hook 2 drops the player's customization for that ride so the TAXI keeps its stock parts, and fits
// the wheels (see fit_taxi_wheels).
//
// The ctor's wheel loop (0x0075D5A1) takes each wheel's base position from the car type's render
// attributes: class 0xA5B543B7, collection keyed by the CarTypeInfo name (table at [0x9B09D8], 0xD0
// bytes per type, name at +0x10; key = 0x004549B0(name), collection = 0x00456050(class, key), both
// cdecl). The collection's layout is at +0x18 and holds four (x, y, z, radius) vectors at +0x10.
// After the swap those are the traffic TAXI's, while the physics (and so the ride height) is still
// the player's car: the wheels and the body height offset are refitted to the real car
// (fit_taxi_wheels, fit_render_layout).
#include "model_swap.h"

#include <cstdint>
#include <cstring>

#include "config.h"
#include "dash_fx.h"
#include "log.h"
#include "patch.h"

namespace ctmw {

namespace {

constexpr int kCarTypeTaxi = 81;           // CarType::TAXI
constexpr std::uint32_t kUsagePlayer = 0;  // CarRenderUsage::Player
constexpr int kCarTypeCount = 0x54;        // the factory rejects types >= 84

constexpr std::uintptr_t kFactoryLookupSite = 0x0075E6E8;
constexpr std::uintptr_t kCarTypeLookup = 0x007398D0;
constexpr std::uintptr_t kSetupRideSite = 0x0075D695;
constexpr std::uintptr_t kSetupRide = 0x0075D220;

using LookupFn = int(__thiscall*)(void* table, std::uint32_t hash);
using SetupRideFn = char(__thiscall*)(void* self, int a1, std::uint32_t usage, int flag, void* customization);

LookupFn g_lookup = nullptr;
SetupRideFn g_setup_ride = nullptr;
int g_swapped_from = -1;  // the player's real car type, for the ride being built right now

constexpr std::uintptr_t kCarTypeInfoTable = 0x009B09D8;
constexpr std::size_t kCarTypeInfoSize = 0xD0;
constexpr std::size_t kCarTypeInfoName = 0x10;
constexpr std::uintptr_t kStringToKey = 0x004549B0;
constexpr std::uintptr_t kFindCollection = 0x00456050;
constexpr std::uint32_t kRenderAttribClass = 0xA5B543B7;
constexpr std::size_t kCollectionLayout = 0x18;
constexpr std::size_t kLayoutWheels = 0x10;

// A car type's render attribute layout (class 0xA5B543B7), or null.
const char* render_layout(int type) {
    const auto table = *reinterpret_cast<const char* const*>(va(kCarTypeInfoTable));
    if (!table || type < 0 || type >= kCarTypeCount) return nullptr;
    const char* name = table + type * kCarTypeInfoSize + kCarTypeInfoName;
    const auto key = reinterpret_cast<std::uint32_t(__cdecl*)(const char*)>(va(kStringToKey))(name);
    const auto coll = reinterpret_cast<const char*(__cdecl*)(std::uint32_t, std::uint32_t)>(
        va(kFindCollection))(kRenderAttribClass, key);
    return coll ? *reinterpret_cast<const char* const*>(coll + kCollectionLayout) : nullptr;
}

// The four (x, y, z, radius) wheel vectors from a car type's render attributes, or null.
const float* render_wheels(int type) {
    const char* layout = render_layout(type);
    return layout ? reinterpret_cast<const float*>(layout + kLayoutWheels) : nullptr;
}

struct RenderInfo {
    std::uint32_t unk0;
    std::uint32_t model_hash;
    std::uint32_t unk8;
    std::uint32_t usage;
    void* customization;
};

extern "C" int __cdecl factory_lookup(void* table, std::uint32_t hash, const RenderInfo* info) {
    const int type = g_lookup(table, hash);
    if (!g_config.enable || !g_config.model_swap || !info) return type;
    if (info->usage != kUsagePlayer || type < 0 || type >= kCarTypeCount) return type;
    log("model_swap: player car type %d -> TAXI", type);
    g_swapped_from = type;
    return kCarTypeTaxi;
}

// Replaces `call CarTypeLookup` (thiscall, one stack arg). edi holds the render info at this site.
__declspec(naked) void factory_lookup_stub() {
    __asm {
        push edi                  // info
        push dword ptr [esp + 8]  // hash (above our push and the return address)
        push ecx                  // lookup table
        call factory_lookup
        add esp, 12
        ret 4
    }
}

// Axel's wheel layout (CT3.exe car record 7, converted to NFS metres; the tyre mesh origin sits
// 0.08 m in from the CT3 hub so these are hub centres).
constexpr float kWheelX[2] = {1.55f, 1.55f};  // front, rear: |x| (forward)
constexpr float kWheelY[2] = {0.77f, 0.73f};  // front, rear: |y| (lateral)

// CarRenderConn: per-wheel base position vector4 at +0x90 + 16*i and radius at +0xD0 + 4*i, filled
// from the car type's render attributes in the ctor loop at 0x0075D5A1 (i < 2 are the front wheels).
// RideInfo* at +0x40.
constexpr std::size_t kWheelPos = 0x90;
constexpr std::size_t kWheelRadius = 0xD0;
constexpr std::size_t kRide = 0x40;
constexpr std::size_t kRideCanBeVertexDamaged = 6;

void fit_taxi_wheels(char* conn) {
    const float* real = render_wheels(g_swapped_from);
    if (!real) log("model_swap: no render attributes for car type %d; wheel height left as TAXI's", g_swapped_from);
    for (int i = 0; i < 4; ++i) {
        float* p = reinterpret_cast<float*>(conn + kWheelPos + 16 * i);
        const int axle = i < 2 ? 0 : 1;
        p[0] = p[0] < 0 ? -kWheelX[axle] : kWheelX[axle];
        p[1] = p[1] < 0 ? -kWheelY[axle] : kWheelY[axle];
        if (real) {
            // Put the bottom of the taxi's tyre where the real car's tyre meets the road.
            const float radius = *reinterpret_cast<const float*>(conn + kWheelRadius + 4 * i);
            const float* r = real + 4 * i;
            const float z = r[2] - r[3] + radius + g_config.wheel_height;
            if (i == 0 || i == 2) {
                log("model_swap: wheel %d real hub z %.3f r %.3f, taxi hub z %.3f r %.3f -> z %.3f", i, r[2], r[3],
                    p[2], radius, z);
            }
            p[2] = z;
        }
    }
}

// The renderer keeps reading the render layout every frame through the conn's cached pointer at
// +0x1C (attribute instance at +0x14). The TAXI's is a traffic car's: +0xFC is a body height offset
// in inches (0x007471AD: * 0.0254; TAXI +2, COBALTSS -3), which made the car float, and it also has
// traffic values elsewhere (e.g. +0x58..0x8F all 0 where player cars have 1) that kept the wheels
// off the road. So the player's conn renders with a private copy of the real car's layout, which
// matches its physics, with the taxi's fitted wheel vectors written in. Traffic taxis keep the
// shared original. The layout is 0x120 bytes (the furthest read is a byte at +0x11C).
constexpr std::size_t kConnLayout = 0x1C;
constexpr std::size_t kLayoutSize = 0x120;
constexpr std::size_t kLayoutBodyOffsetInches = 0xFC;
alignas(16) char g_player_layout[kLayoutSize];

void fit_render_layout(char* conn) {
    const char* real = render_layout(g_swapped_from);
    const char* taxi = *reinterpret_cast<const char* const*>(conn + kConnLayout);
    if (!real || !taxi) {
        log("model_swap: no render layout for car type %d; rendering with TAXI's", g_swapped_from);
        return;
    }
    std::memcpy(g_player_layout, real, kLayoutSize);
    for (int i = 0; i < 4; ++i) {
        float wheel[4];
        std::memcpy(wheel, conn + kWheelPos + 16 * i, 12);
        std::memcpy(&wheel[3], conn + kWheelRadius + 4 * i, 4);
        std::memcpy(g_player_layout + kLayoutWheels + 16 * i, wheel, sizeof wheel);
    }
    log("model_swap: rendering with the real car's layout (body offset %.2f in, TAXI's was %.2f in)",
        *reinterpret_cast<const float*>(real + kLayoutBodyOffsetInches),
        *reinterpret_cast<const float*>(taxi + kLayoutBodyOffsetInches));
    *reinterpret_cast<const char**>(conn + kConnLayout) = g_player_layout;
}

char __fastcall setup_ride(void* self, void* /*edx*/, int a1, std::uint32_t usage, int flag, void* customization) {
    char* conn = static_cast<char*>(self);
    if (usage == kUsagePlayer) dash_fx_set_player_conn(conn);
    const bool taxi = g_config.enable && g_config.model_swap && usage == kUsagePlayer &&
                      *reinterpret_cast<int*>(conn + 0x2C) == kCarTypeTaxi;
    if (taxi && customization) {
        log("model_swap: dropping player customization for TAXI ride");
        customization = nullptr;
    }
    const char ok = g_setup_ride(self, a1, usage, flag, customization);
    if (taxi) {
        if (char* ride = *reinterpret_cast<char**>(conn + kRide)) ride[kRideCanBeVertexDamaged] = 0;
        const float* w = reinterpret_cast<const float*>(conn + kWheelPos);
        log("model_swap: stock wheel FL (%.2f %.2f %.2f) RL (%.2f %.2f %.2f)", w[0], w[1], w[2], w[8], w[9], w[10]);
        fit_taxi_wheels(conn);
        fit_render_layout(conn);
    }
    return ok;
}

}  // namespace

bool model_swap_install() {
    const std::uintptr_t lookup = redirect_call(kFactoryLookupSite, kCarTypeLookup, &factory_lookup_stub);
    if (!lookup) return false;
    g_lookup = reinterpret_cast<LookupFn>(lookup);

    const std::uintptr_t setup = redirect_call(kSetupRideSite, kSetupRide, &setup_ride);
    if (!setup) {
        log("model_swap: SetupRide hook failed; taxi will try to use the player's parts");
        return true;
    }
    g_setup_ride = reinterpret_cast<SetupRideFn>(setup);
    log("model_swap: installed");
    return true;
}

}  // namespace ctmw
