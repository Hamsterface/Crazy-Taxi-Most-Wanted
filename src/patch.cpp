#include "patch.h"

#include <windows.h>

#include <cstring>

#include "log.h"

namespace ctmw {

std::uintptr_t va(std::uintptr_t v13) {
    static const std::uintptr_t base = reinterpret_cast<std::uintptr_t>(GetModuleHandleW(nullptr));
    return v13 - 0x400000 + base;
}

bool bytes_match(std::uintptr_t site, const std::uint8_t* expected, std::size_t len) {
    return std::memcmp(reinterpret_cast<const void*>(va(site)), expected, len) == 0;
}

std::uintptr_t redirect_call(std::uintptr_t site, std::uintptr_t expected_target, const void* detour) {
    auto* p = reinterpret_cast<std::uint8_t*>(va(site));
    if (p[0] != 0xE8) {
        log("patch: %08x is not a call (%02x)", static_cast<unsigned>(site), p[0]);
        return 0;
    }
    std::int32_t rel;
    std::memcpy(&rel, p + 1, 4);
    const std::uintptr_t target = reinterpret_cast<std::uintptr_t>(p) + 5 + rel;
    if (target != va(expected_target)) {
        log("patch: %08x calls %08x, expected %08x (already hooked by another mod?)", static_cast<unsigned>(site),
            static_cast<unsigned>(target), static_cast<unsigned>(va(expected_target)));
        return 0;
    }
    const std::int32_t new_rel =
        static_cast<std::int32_t>(reinterpret_cast<std::uintptr_t>(detour) - (reinterpret_cast<std::uintptr_t>(p) + 5));
    DWORD old;
    VirtualProtect(p, 5, PAGE_EXECUTE_READWRITE, &old);
    std::memcpy(p + 1, &new_rel, 4);
    VirtualProtect(p, 5, old, &old);
    FlushInstructionCache(GetCurrentProcess(), p, 5);
    return target;
}

}  // namespace ctmw
