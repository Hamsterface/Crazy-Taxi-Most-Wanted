#pragma once

namespace ctmw {

// Crazy Taxi handling constants (metres, seconds). Defaults match the CrazyTaxiMW.ini this mod writes;
// every one can be overridden in its [Handling] section.
struct Tuning {
    float top_speed = 42.5f;          // Drive top speed (m/s)
    float reverse_top_speed = 12.7f;  // config_load makes it top_speed * 0.3 unless ReverseTopSpeed is set
    float accel = 5.4f;               // Drive acceleration at standstill (m/s^2)
    float reverse_accel = 5.4f;       // config_load makes it match accel unless ReverseAccel is set
    float brake = 22.4f;              // brake deceleration
    float coast = 2.5f;               // rolling resistance with no pedals
    float over_speed_decay = 6.0f;    // how fast speed above top speed settles back once a Dash ends
    float yaw_rate = 4.0f;            // max yaw rate (rad/s) once rolling
    float yaw_ramp_speed = 6.0f;      // speed at which full steering authority is reached
    float yaw_high_speed_falloff = 20.0f;
    float yaw_response = 9.0f;        // how quickly the yaw rate follows the stick
    float grip = 7.5f;                // lateral slip decay (1/s)
    float grip_redirect = 0.65f;      // share of killed slip that is turned into forward speed
    float dash_time = 1.0f;           // how long a (Back) Dash's boost lasts
    float dash_cooldown = 0.5f;       // after a (Back) Dash ends, wait this long before the next one
    float dash_top_speed_mult = 1.2f;  // top speed multiplier during a (Back) Dash
    float dash_accel_mult = 5.0f;     // acceleration multiplier during a (Back) Dash
    float dash_window = 0.35f;        // seconds for the shift-then-gas (or R->D) combo
    float drift_grip = 2.5f;          // lateral slip decay in a drift while D is still held
    float drift_yaw_mult = 2.0f;
    float drift_redirect = 0.85f;
    float crazy_stop_mult = 2.0f;     // brake multiplier while rolling forward in R during a Dash
    float hop_speed = 10.0f;           // vertical launch speed of a Crazy Hop
    float hop_cooldown = 1.0f;
    float min_limit_cut_delay = 0.25f;  // a Limit Cut's R hold before the D shift: at least this long
    float max_limit_cut_delay = 1.0f;   // ... and shorter than this
    float limit_cut_mult = 2.0f;      // replaces dash_top_speed_mult during a Limit Cut
};

// Drive, reverse and hop come from the game's own NOS, handbrake and action inputs (whatever you
// bound in NFS). Only the handling toggle is a raw virtual-key code.
struct Bindings {
    int key_toggle = 0x77;   // F8: handling on/off
};

// Crazy Taxi's D/R gear display. Sizes are in 1/480ths of the screen height.
struct Hud {
    bool gear_display = true;
    float gear_size = 64;     // width and height of the display
    float gear_right = 32;    // gap between the display and the right edge of the screen
    float gear_bottom = 32;   // gap between the display and the bottom of the screen
};

struct Config {
    bool enable = true;      // master switch
    bool model_swap = true;  // render the player's car as the taxi
    bool handling = true;    // Crazy Taxi handling
    bool debug_log = false;  // log handling state twice a second
    // m added to the taxi's rendered wheel height. The swapped TAXI's wheels (stock model too) render
    // ~0.24 m above the road for a reason not yet found; this default was matched by eye in game.
    float wheel_height = -0.22f;
    Tuning tuning;
    Bindings bindings;
    Hud hud;
};

extern Config g_config;

// Reads CrazyTaxiMW.ini; writes a commented default if it does not exist.
void config_load(const wchar_t* path);

}  // namespace ctmw
