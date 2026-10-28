#pragma once

namespace ctmw {

// Draws Crazy Taxi's D/R gear display in the bottom-right corner, over the game's finished frame, and keeps the
// player's settings in line with it every frame (player_settings.h).
bool gear_hud_install();

// Called by the handling every tick it drives the car. The D/R gear display shows while these keep coming,
// so it hides by itself in menus, the pause screen, cutscenes and drag races, and when F8 turns the handling off.
void gear_hud_update(bool reverse);

}  // namespace ctmw
