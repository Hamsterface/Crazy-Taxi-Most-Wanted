#pragma once

namespace ctmw {

// Opens scripts\CrazyTaxiMW.log next to the .asi (truncated per launch).
void log_open(const wchar_t* path);
void log(const char* fmt, ...);

}  // namespace ctmw
