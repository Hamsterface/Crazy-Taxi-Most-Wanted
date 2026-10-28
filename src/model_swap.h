#pragma once

namespace ctmw {

// Makes every in-game render of the player's car (CarRenderUsage::Player) use CarType TAXI
// with its stock parts. The player's vehicle (physics, attributes, save data) is untouched.
bool model_swap_install();

}  // namespace ctmw
