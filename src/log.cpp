#include "log.h"

#include <windows.h>

#include <cstdarg>
#include <cstdio>
#include <mutex>

namespace ctmw {

namespace {
std::FILE* g_file = nullptr;
std::mutex g_mutex;
}  // namespace

void log_open(const wchar_t* path) {
    std::lock_guard lock(g_mutex);
    if (!g_file) g_file = _wfopen(path, L"w");
}

void log(const char* fmt, ...) {
    std::lock_guard lock(g_mutex);
    if (!g_file) return;
    SYSTEMTIME t;
    GetLocalTime(&t);
    std::fprintf(g_file, "[%02d:%02d:%02d.%03d] ", t.wHour, t.wMinute, t.wSecond, t.wMilliseconds);
    va_list ap;
    va_start(ap, fmt);
    std::vfprintf(g_file, fmt, ap);
    va_end(ap);
    std::fputc('\n', g_file);
    std::fflush(g_file);
}

}  // namespace ctmw
