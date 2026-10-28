// Crazy Taxi handling model. Pure logic: no game or OS dependencies, so it can be unit tested.
//
// Works in the car's frame: `fwd` along the nose, `lat` towards the car's right, `up` along its roof.
// Yaw is positive when turning right. The game glue converts to and from world space.
#pragma once

#include "config.h"

namespace ctmw {

enum class Gear { Drive, Reverse };

struct CtInput {
    float steer = 0;  // -1 full left .. +1 full right
    float gas = 0;    // 0..1
    float brake = 0;  // 0..1
    bool shift_drive = false;    // edge
    bool shift_reverse = false;  // edge
    bool hop = false;            // edge
    bool drive_held = false;     // the D button is down right now
};

struct CtMeasured {
    float fwd = 0, lat = 0, up = 0;  // the body's velocity this tick, car frame (m/s)
    bool grounded = true;
};

struct CtOutput {
    bool active = false;  // false: leave the body alone this tick
    float fwd = 0, lat = 0;
    bool set_up = false;
    float up = 0;
    float yaw_rate = 0;   // rad/s, positive = right
};

// handling.cpp's debug log names these in order.
enum class Move { None, Dash, BackDash, LimitCut, Drift, Hop };

class CtCar {
public:
    void reset();
    CtOutput update(float dt, const CtInput& in, const CtMeasured& m, const Tuning& t);

    Gear gear() const { return gear_; }
    bool drifting() const { return drift_; }
    bool dashing(const Tuning& t) const { return since_dash_ < t.dash_time; }
    Move last_move() const { return last_move_; }

private:
    void longitudinal(float dt, const CtInput& in, const Tuning& t);
    void triggers(const CtInput& in, const Tuning& t);
    void dash(const Tuning& t, Move move);

    Gear gear_ = Gear::Drive;
    bool have_state_ = false;
    float fwd_ = 0, lat_ = 0, yaw_ = 0;
    bool drift_ = false;
    float since_dash_ = 99;  // seconds since the last Dash / Back Dash started; shared, so one locks out the other
    Gear dash_gear_ = Gear::Drive;  // Drive for a Dash, Reverse for a Back Dash
    bool limit_cut_ = false;        // the current Dash is a Limit Cut: a Dash with a higher top speed
    bool limit_cut_armed_ = false;  // the last D shift came after a Limit Cut's R hold
    float since_drive_ = 99, since_reverse_ = 99, hop_cooldown_ = 0;
    bool gas_held_ = false;
    Move last_move_ = Move::None;
};

}  // namespace ctmw
