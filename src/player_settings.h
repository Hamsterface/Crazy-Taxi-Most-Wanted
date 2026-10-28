#pragma once

namespace ctmw {

// Called every frame. Keeps player 1's Transmission on Auto in the current user profile, so it is already in place
// when a race (drag races included) is set up; that is saved with the profile. Gauges are turned off only while the
// gear display is shown, and the player's own setting is put back when it hides.
void player_settings_force(bool gear_display_shown);

}  // namespace ctmw
