#pragma once

namespace ctmw {

// Shows the NOS taillight streaks on the player's car while a (Back) Dash is running.
bool dash_fx_install();

// The player's CarRenderConn, from model_swap's SetupRide hook.
void dash_fx_set_player_conn(void* conn);

// Called by the handling every tick.
void dash_fx_set(bool on);

}  // namespace ctmw
