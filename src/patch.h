// Minimal, verified call-site patching for speed.exe v1.3 (x86, fixed base 0x400000).
#pragma once
#include <cstddef>
#include <cstdint>

namespace ctmw {

// Rebase a v1.3 VA onto the loaded image (speed.exe has no relocations, so this is a no-op
// in practice, but it keeps the code honest if a loader ever moves it).
std::uintptr_t va(std::uintptr_t v13);

// Check that `site` holds `E8 rel32` calling `expected_target`, then point it at `detour`.
// Returns the original target (rebased) or 0 if the bytes did not match (nothing patched).
std::uintptr_t redirect_call(std::uintptr_t site, std::uintptr_t expected_target, const void* detour);

// Compare `len` bytes at `site` against `expected`.
bool bytes_match(std::uintptr_t site, const std::uint8_t* expected, std::size_t len);

}  // namespace ctmw
