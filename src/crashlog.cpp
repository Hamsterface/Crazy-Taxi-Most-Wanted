// Crash reporter: logs the first few access violations / fatal exceptions with registers and the
// speed.exe return addresses found on the stack, so a crash can be traced to game code.
#include "crashlog.h"

#include <windows.h>

#include <atomic>

#include "log.h"

namespace ctmw {

namespace {

std::atomic<int> g_reported{0};
constexpr int kMaxReports = 3;

bool in_module(std::uintptr_t a, std::uintptr_t base, std::uintptr_t size) { return a >= base && a < base + size; }

void module_range(HMODULE m, std::uintptr_t& base, std::uintptr_t& size) {
    base = reinterpret_cast<std::uintptr_t>(m);
    const auto* dos = reinterpret_cast<const IMAGE_DOS_HEADER*>(m);
    const auto* nt = reinterpret_cast<const IMAGE_NT_HEADERS32*>(reinterpret_cast<const char*>(m) + dos->e_lfanew);
    size = nt->OptionalHeader.SizeOfImage;
}

LONG CALLBACK handler(EXCEPTION_POINTERS* ep) {
    const DWORD code = ep->ExceptionRecord->ExceptionCode;
    const bool fatal = code == EXCEPTION_ACCESS_VIOLATION || code == EXCEPTION_ILLEGAL_INSTRUCTION ||
                       code == EXCEPTION_INT_DIVIDE_BY_ZERO || code == EXCEPTION_STACK_OVERFLOW ||
                       code == EXCEPTION_PRIV_INSTRUCTION || code == EXCEPTION_BREAKPOINT;
    if (!fatal || g_reported.fetch_add(1) >= kMaxReports) return EXCEPTION_CONTINUE_SEARCH;

    std::uintptr_t base, size;
    module_range(GetModuleHandleW(nullptr), base, size);
    const CONTEXT* c = ep->ContextRecord;
    const auto* rec = ep->ExceptionRecord;
    log("CRASH code=%08lx eip=%08lx (%s) access=%s addr=%08lx", code, c->Eip,
        in_module(c->Eip, base, size) ? "speed.exe" : "other module",
        rec->NumberParameters >= 2 ? (rec->ExceptionInformation[0] ? "write" : "read") : "?",
        rec->NumberParameters >= 2 ? static_cast<unsigned long>(rec->ExceptionInformation[1]) : 0ul);
    log("  eax=%08lx ebx=%08lx ecx=%08lx edx=%08lx esi=%08lx edi=%08lx ebp=%08lx esp=%08lx", c->Eax, c->Ebx,
        c->Ecx, c->Edx, c->Esi, c->Edi, c->Ebp, c->Esp);

    // Return addresses into speed.exe on the stack (first 32).
    char line[512];
    int n = 0, len = 0;
    const auto* sp = reinterpret_cast<const std::uintptr_t*>(c->Esp);
    for (int i = 0; i < 2048 && n < 32; ++i) {
        std::uintptr_t v;
        if (IsBadReadPtr(sp + i, sizeof v)) break;
        v = sp[i];
        if (in_module(v, base, size) && v > base + 0x1000) {
            len += wsprintfA(line + len, " %08lx", static_cast<unsigned long>(v));
            if (++n % 8 == 0) {
                log("  stack:%s", line);
                len = 0;
            }
        }
    }
    if (len) log("  stack:%s", line);
    return EXCEPTION_CONTINUE_SEARCH;
}

}  // namespace

void crashlog_install() { AddVectoredExceptionHandler(1, handler); }

}  // namespace ctmw
