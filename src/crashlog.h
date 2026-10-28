#pragma once

#include <cstdint>

namespace ctmw {

// Logs fatal exceptions (address, registers, speed.exe return addresses) to CrazyTaxiMW.log.
void crashlog_install();

}  // namespace ctmw
