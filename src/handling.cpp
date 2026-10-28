// Game glue for the Crazy Taxi handling (speed.exe v1.3).
//
// Hook: InputPlayer::OnTaskSimulate(float dt) = slot 6 of InputPlayer's primary vtable (0x008AC6BC),
// stock 0x0068CFE0. It runs once per sim tick for each human player, after which the tick's
// InputControls (InputPlayer+0x50) are filled in.
//
// From InputPlayer:
//   +0x34                ISimable* of the owning PVehicle (PVehicle+0x2C)
//   +0x50                InputControls: +0x04 steering, +0x14 gas, +0x18 brake, +0x1C handbrake, +0x20 action,
//                        +0x21 NOS
//   +0x74 + 0x2B8        IInputPlayer::IsBlocked flag
// From the ISimable S (all verified against PVehicle's IVehicle accessors, IVehicle = S + 0x80):
//   S+0x114 driver class (0 = human), S+0x128 force-stop flags, S+0x131 staging, S+0x104 wheels on ground
//   vtable slot 21: GetRigidBody()
// IRigidBody slots (RigidBody's vtable 0x008AC390, each checked against its Volatile accessor):
//   9 GetLinearVelocity, 10 GetAngularVelocity, 13 GetForwardVector, 14 GetRightVector,
//   15 GetUpVector, 24 SetLinearVelocity, 25 SetAngularVelocity. World space, metres, y up.
//
// Hop shares the action button with Speedbreaker, which the game turns on through
// IPlayer::ToggleGameBreaker = slot 20 of LocalPlayer's IPlayer vtable (0x008B0B10), stock 0x006EDD10.
// Clearing InputControls.action does not stop it, so that slot is hooked too. Slot 16 is InGameBreaker.
//
// IInputPlayer::FetchInput = slot 4 of InputPlayer's IInputPlayer vtable (0x008AC658, at InputPlayer+0x74),
// stock 0x006A8870, drains the action queue into InputControls. Gas, brake and handbrake are rebuilt from
// private fields every time, but NOS starts from the current InputControls.nos and only changes on a
// press/release event, and the action flag flips on each Speedbreaker press. So clearing NOS for the
// drivetrain would also make the game forget that it is held: the hook keeps the real NOS state aside.
//
// The pedals FetchInput copies come from InputPlayer+0x74+0x2A8 (gas) and +0x2AC (brake), clamped 0..1.
// Then, at 0x006A8D89, it calls InputPlayer::AutoReverse(gas, brake) = 0x0069CEF0. Under 2.5 m/s with only
// the brake held, that shifts the gearbox into reverse, and while in reverse it writes gas and brake into
// InputControls the other way round. So the handling reads the private fields, and that call is redirected
// so it never sees the brake while we drive.
#include "handling.h"

#include <windows.h>

#include <cmath>
#include <cstdint>

#include "config.h"
#include "ctphysics.h"
#include "dash_fx.h"
#include "gear_hud.h"
#include "log.h"
#include "patch.h"

namespace ctmw {

namespace {

constexpr std::uintptr_t kInputPlayerVtbl = 0x008AC6BC;
constexpr std::uintptr_t kInputPlayerVtblTaskSimulate = kInputPlayerVtbl + 6 * 4;
constexpr std::uintptr_t kInputPlayerOnTaskSimulate = 0x0068CFE0;

constexpr std::uintptr_t kLocalPlayerVtblToggleGameBreaker = 0x008B0B10 + 20 * 4;
constexpr std::uintptr_t kLocalPlayerToggleGameBreaker = 0x006EDD10;

constexpr std::uintptr_t kIInputPlayerVtblFetchInput = 0x008AC658 + 4 * 4;
constexpr std::uintptr_t kInputPlayerFetchInput = 0x006A8870;
constexpr std::ptrdiff_t kIInputPlayerToControls = 0x50 - 0x74;
constexpr std::ptrdiff_t kInputPlayerGas = 0x74 + 0x2A8;
constexpr std::ptrdiff_t kInputPlayerBrake = 0x74 + 0x2AC;

constexpr std::uintptr_t kFetchInputCallAutoReverse = 0x006A8D89;
constexpr std::uintptr_t kInputPlayerAutoReverse = 0x0069CEF0;

using TaskSimulateFn = void(__thiscall*)(void* self, float dt);
TaskSimulateFn g_orig = nullptr;
using ToggleGameBreakerFn = bool(__thiscall*)(void* self);
ToggleGameBreakerFn g_orig_toggle_gb = nullptr;
using FetchInputFn = void(__thiscall*)(void* self);
FetchInputFn g_orig_fetch_input = nullptr;
using AutoReverseFn = void(__thiscall*)(void* self, float gas, float brake);
AutoReverseFn g_orig_auto_reverse = nullptr;

struct Vec3 {
    float x, y, z;
};
Vec3 operator+(Vec3 a, Vec3 b) { return {a.x + b.x, a.y + b.y, a.z + b.z}; }
Vec3 operator-(Vec3 a, Vec3 b) { return {a.x - b.x, a.y - b.y, a.z - b.z}; }
Vec3 operator*(Vec3 a, float k) { return {a.x * k, a.y * k, a.z * k}; }
float dot(Vec3 a, Vec3 b) { return a.x * b.x + a.y * b.y + a.z * b.z; }
Vec3 cross(Vec3 a, Vec3 b) { return {a.y * b.z - a.z * b.y, a.z * b.x - a.x * b.z, a.x * b.y - a.y * b.x}; }

template <typename R, typename... A>
R vcall(void* obj, int slot, A... args) {
    using F = R(__thiscall*)(void*, A...);
    return (*reinterpret_cast<F**>(obj))[slot](obj, args...);
}

template <typename T>
T& at(void* base, std::ptrdiff_t off) {
    return *reinterpret_cast<T*>(static_cast<char*>(base) + off);
}

struct InputControls {
    float banking, steering, steering_vertical, strafe_vertical, strafe_horizontal;
    float gas, brake, handbrake;
    bool action, nos;
};

// Crazy Taxi-only buttons. D, R and hop sit on the game's NOS, handbrake and action inputs.
struct Buttons {
    bool drive = false, reverse = false, hop = false, toggle = false;
};
Buttons g_held;

bool game_has_focus() {
    DWORD pid = 0;
    GetWindowThreadProcessId(GetForegroundWindow(), &pid);
    return pid == GetCurrentProcessId();
}

bool key_down(int vk) { return vk > 0 && (GetAsyncKeyState(vk) & 0x8000) != 0; }

CtCar g_car;
bool g_on = true;
bool g_driving = false;    // our handling drove the car last tick, so NFS must not see NOS
ULONGLONG g_driven_ms = 0; // when our handling last drove the car. Drag races never tick, so g_driving can be stale.
bool g_nos_held = false;   // the real NOS button state, kept out of InputControls while we drive
float g_handbrake = 0;     // the real handbrake, kept out of InputControls while we drive
float g_game_gas = 0;      // what we last told the NFS engine
float g_log_timer = 0;

// While we drive, NFS's gearbox must not auto-shift into reverse on the brake: it gets our engine gas and
// no brake instead. That also shifts it back out of reverse if it was there when we took over.
// InputPlayerDrag's FetchInput (0x006A8E70) jumps into the same code, so drag races are let through untouched.
void __fastcall on_auto_reverse(void* self, void* /*edx*/, float gas, float brake) {
    if (g_driving && *static_cast<std::uintptr_t*>(self) == va(kInputPlayerVtbl)) {
        gas = g_game_gas;
        brake = 0;
    }
    g_orig_auto_reverse(self, gas, brake);
}

// FetchInput does not run right before OnTaskSimulate: the vehicle sim reads InputControls in between.
// So the pedals are hidden here, not only in tick().
void __fastcall on_fetch_input(void* self, void* /*edx*/) {
    auto& controls = at<InputControls>(self, kIInputPlayerToControls);
    // Put back the state we hid, so this tick's NOS press/release events apply on top of it.
    if (g_driving) controls.nos = g_nos_held;
    g_orig_fetch_input(self);
    g_nos_held = controls.nos;
    g_handbrake = controls.handbrake;
    if (g_driving) {
        controls.nos = false;
        controls.gas = g_game_gas;
        controls.brake = 0;
        controls.handbrake = 0;
    }
}

void tick(void* input_player, float dt) {
    auto& controls = at<InputControls>(input_player, 0x50);
    g_driving = false;
    dash_fx_set(false);
    // on_fetch_input keeps the real NOS and handbrake aside. If that hook is missing, InputControls still
    // holds them here, but D only counts on the press tick and NFS sees them until they are cleared below.
    // Gas and brake come from InputPlayer's own fields, as InputControls has them swapped in NFS's reverse.
    // The action flag flips per press, and clearing it below turns that into one rising edge per press.
    // The game has no input for the toggle, so it stays a raw key.
    const bool hooked = g_orig_fetch_input != nullptr;
    const bool nos = hooked ? g_nos_held : controls.nos;
    const float gas = at<float>(input_player, kInputPlayerGas);
    const float brake = at<float>(input_player, kInputPlayerBrake);
    const float handbrake = hooked ? g_handbrake : controls.handbrake;
    const Buttons held{nos, handbrake > 0.5f, controls.action,
                       game_has_focus() && key_down(g_config.bindings.key_toggle)};
    const Buttons buttons{held.drive && !g_held.drive, held.reverse && !g_held.reverse, held.hop && !g_held.hop,
                          held.toggle && !g_held.toggle};
    g_held = held;
    if (buttons.toggle) {
        g_on = !g_on;
        log("handling: %s", g_on ? "on" : "off");
        g_car.reset();
    }
    if (!g_on) return;

    void* sim = at<void*>(input_player, 0x34);
    if (!sim) return;
    if (at<std::uint32_t>(sim, 0x114) != 0) return;  // not a human driver
    const bool blocked = at<std::uint8_t>(input_player, 0x74 + 0x2B8) != 0;
    const bool staging = at<std::uint8_t>(sim, 0x131) != 0;
    const bool force_stop = at<std::uint8_t>(sim, 0x128) != 0;
    if (blocked || staging || force_stop) {
        g_car.reset();
        return;
    }
    void* rb = vcall<void*>(sim, 21);
    if (!rb) return;

    const Vec3 v = *vcall<const Vec3*>(rb, 9);
    const Vec3 w = *vcall<const Vec3*>(rb, 10);
    Vec3 f, r, u;
    vcall<void, Vec3*>(rb, 13, &f);
    vcall<void, Vec3*>(rb, 14, &r);
    vcall<void, Vec3*>(rb, 15, &u);

    CtInput in;
    in.steer = controls.steering;
    in.gas = gas;
    in.brake = brake;
    in.shift_drive = buttons.drive;
    in.drive_held = held.drive;
    in.shift_reverse = buttons.reverse;
    in.hop = buttons.hop;

    CtMeasured m;
    m.fwd = dot(v, f);
    m.lat = dot(v, r);
    m.up = dot(v, u);
    m.grounded = at<std::uint32_t>(sim, 0x104) >= 2;

    const CtOutput out = g_car.update(dt, in, m, g_config.tuning);
    // The streaks cover the whole (Back) Dash, including a Back Dash that stopped boosting after a D shift.
    dash_fx_set(g_car.dashing(g_config.tuning));

    // The NFS drivetrain still runs (sound, rpm, brake lights) but must not fight us.
    g_game_gas = in.gas;
    controls.gas = in.gas;
    controls.brake = in.brake;
    controls.handbrake = 0;
    controls.nos = false;
    controls.action = false;
    g_driving = true;
    g_driven_ms = GetTickCount64();
    gear_hud_update(g_car.gear() == Gear::Reverse);

    if (out.active) {
        const Vec3 nv = f * out.fwd + r * out.lat + u * (out.set_up ? out.up : m.up);
        vcall<void, const Vec3*>(rb, 24, &nv);
        // Positive yaw turns towards the right vector; work out which way that is about `u`.
        const float turn_sign = dot(cross(u, f), r) >= 0 ? 1.0f : -1.0f;
        const Vec3 nw = w - u * dot(w, u) + u * (out.yaw_rate * turn_sign);
        vcall<void, const Vec3*>(rb, 25, &nw);
    }

    if (g_config.debug_log) {
        g_log_timer += dt;
        if (g_log_timer >= 0.5f || g_car.last_move() != Move::None) {
            g_log_timer = 0;
            static const char* const kMoves[] = {"", "DASH", "BACKDASH", "LIMITCUT", "DRIFT", "HOP"};
            static_assert(sizeof kMoves / sizeof kMoves[0] == static_cast<int>(Move::Hop) + 1);
            log("ct: gear=%c speed=%5.1f lat=%5.1f yaw=%5.2f steer=%5.2f gas=%.2f brake=%.2f Dheld=%d ground=%u %s%s",
                g_car.gear() == Gear::Drive ? 'D' : 'R', out.fwd, out.lat, out.yaw_rate, in.steer, in.gas,
                in.brake, in.drive_held, at<std::uint32_t>(sim, 0x104), g_car.drifting() ? "drifting " : "",
                kMoves[static_cast<int>(g_car.last_move())]);
        }
    }
}

void __fastcall on_task_simulate(void* self, void* /*edx*/, float dt) {
    g_orig(self, dt);
    if (g_config.enable && g_config.handling) tick(self, dt);
}

// While our handling drives, the action button is Hop only. Turning an active Speedbreaker off still works.
// Anywhere else (drag races, F8 off, cutscenes) Speedbreaker is left alone.
bool __fastcall on_toggle_game_breaker(void* self, void* /*edx*/) {
    const bool driving = g_driving && GetTickCount64() - g_driven_ms < 200;
    if (driving && !vcall<bool>(self, 16)) return false;
    return g_orig_toggle_gb(self);
}

// Swap a vtable entry after checking it still holds the stock function. Returns the original or 0.
std::uintptr_t hook_vtable(const char* name, std::uintptr_t slot_va, std::uintptr_t expected, const void* detour) {
    auto* slot = reinterpret_cast<std::uintptr_t*>(va(slot_va));
    if (*slot != va(expected)) {
        log("handling: %s vtable slot holds %08x, expected %08x; not hooking", name, static_cast<unsigned>(*slot),
            static_cast<unsigned>(va(expected)));
        return 0;
    }
    const std::uintptr_t orig = *slot;
    DWORD old;
    VirtualProtect(slot, 4, PAGE_READWRITE, &old);
    *slot = reinterpret_cast<std::uintptr_t>(detour);
    VirtualProtect(slot, 4, old, &old);
    return orig;
}

}  // namespace

bool handling_install() {
    const std::uintptr_t orig = hook_vtable("InputPlayer", kInputPlayerVtblTaskSimulate, kInputPlayerOnTaskSimulate,
                                            reinterpret_cast<const void*>(&on_task_simulate));
    if (!orig) return false;
    g_orig = reinterpret_cast<TaskSimulateFn>(orig);
    if (const std::uintptr_t gb = hook_vtable("LocalPlayer", kLocalPlayerVtblToggleGameBreaker,
                                              kLocalPlayerToggleGameBreaker,
                                              reinterpret_cast<const void*>(&on_toggle_game_breaker))) {
        g_orig_toggle_gb = reinterpret_cast<ToggleGameBreakerFn>(gb);
    }
    if (const std::uintptr_t fi = hook_vtable("IInputPlayer", kIInputPlayerVtblFetchInput, kInputPlayerFetchInput,
                                              reinterpret_cast<const void*>(&on_fetch_input))) {
        g_orig_fetch_input = reinterpret_cast<FetchInputFn>(fi);
    }
    if (const std::uintptr_t ar = redirect_call(kFetchInputCallAutoReverse, kInputPlayerAutoReverse,
                                                reinterpret_cast<const void*>(&on_auto_reverse))) {
        g_orig_auto_reverse = reinterpret_cast<AutoReverseFn>(ar);
    }
    g_on = g_config.handling;
    log("handling: installed (F8 toggles)");
    return true;
}

}  // namespace ctmw
