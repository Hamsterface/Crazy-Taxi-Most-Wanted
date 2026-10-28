#include "ctphysics.h"

#include <algorithm>
#include <cmath>

namespace ctmw {

namespace {
float sgn(float x) { return x < 0 ? -1.0f : 1.0f; }
float approach(float v, float target, float step) {
    return v < target ? std::min(v + step, target) : std::max(v - step, target);
}
}  // namespace

void CtCar::reset() { *this = CtCar(); }

void CtCar::dash(const Tuning& t, Move move) {
    if (since_dash_ < t.dash_time + t.dash_cooldown) return;
    since_dash_ = 0;
    dash_gear_ = move == Move::BackDash ? Gear::Reverse : Gear::Drive;
    // Decided once per Dash, so later shifts cannot turn a running Dash into a Limit Cut or back
    limit_cut_ = move == Move::LimitCut;
    last_move_ = move;
}

void CtCar::triggers(const CtInput& in, const Tuning& t) {
    const bool gas_pressed = in.gas >= 0.6f && !gas_held_;
    gas_held_ = gas_pressed || (gas_held_ && in.gas > 0.3f);
    const bool turning = fwd_ >= 0 && std::fabs(in.steer) > 0.3f;

    if (in.shift_reverse) {
        gear_ = Gear::Reverse;
        since_reverse_ = 0;
    }
    if (in.shift_drive) {
        if (gear_ == Gear::Reverse && since_reverse_ < t.dash_window && turning) {
            // Drift input is R -> D; this can overlap with Crazy Dash, so clear since_drive_
            drift_ = true;
            last_move_ = Move::Drift;
            since_drive_ = 99;
        } else {
            since_drive_ = 0;
            limit_cut_armed_ = gear_ == Gear::Reverse && since_reverse_ >= t.min_limit_cut_delay &&
                since_reverse_ < t.max_limit_cut_delay;
        }
        gear_ = Gear::Drive;
    }
    if (gas_pressed) {
        if (gear_ == Gear::Drive && since_drive_ < t.dash_window) {
            dash(t, limit_cut_armed_ ? Move::LimitCut : Move::Dash);
        } else if (gear_ == Gear::Reverse && since_reverse_ < t.dash_window) {
            dash(t, Move::BackDash);
        }
    }
}

void CtCar::longitudinal(float dt, const CtInput& in, const Tuning& t) {
    // Allow Crazy Dash to work on R like CT1, but don't allow Crazy Back Dash to work on D
    const bool dashing = since_dash_ < t.dash_time && !(gear_ == Gear::Drive && dash_gear_ == Gear::Reverse);
    // Top speed gets increased on a limiter cut
    const float top_speed = t.top_speed * (!dashing ? 1.0f : limit_cut_ ? t.limit_cut_mult : t.dash_top_speed_mult);
    const float accel_mult = dashing ? t.dash_accel_mult : 1.0f;

    if (gear_ == Gear::Drive) {
        if (in.brake > 0.05f) {
            // Normal braking
            fwd_ = approach(fwd_, 0.0f, in.brake * t.brake * dt);  // D never reverses on the brake
        } else if (in.gas > 0.05f) {
            if (fwd_ < top_speed) {
                // Forward acceleration, accel_mult added for dashing
                const float k = fwd_ / top_speed;
                fwd_ = std::min(top_speed, fwd_ + in.gas * t.accel * accel_mult * (1.0f - k * k) * dt);
            }
        } else fwd_ = approach(fwd_, 0.0f, t.coast * dt);
    } else { // Reverse
        if (in.brake > 0.05f) {
            // Crazy Stop: braking harder while rolling forward in a Dash
            const float stop_mult = fwd_ > 0 && dashing ? t.crazy_stop_mult : 1.0f;
            fwd_ = approach(fwd_, 0.0f, in.brake * t.brake * stop_mult * dt);
        } else if (in.gas > 0.05f) {
            if (fwd_ > 0) {
                // Reverse acceleration
                // A quick R tap at speed is the first half of a Dash or Drift: don't brake yet.
                if (since_reverse_ >= t.dash_window || dashing) {
                    fwd_ = approach(fwd_, 0.0f, in.gas * t.reverse_accel * accel_mult * dt);
                }
            } else if (-fwd_ < t.reverse_top_speed) {
                const float k = -fwd_ / t.reverse_top_speed;
                fwd_ = std::max(-t.reverse_top_speed,
                                fwd_ - in.gas * t.reverse_accel * accel_mult * (1.0f - k * k) * dt);
            }
        } else fwd_ = approach(fwd_, 0.0f, t.coast * dt);
    }

    // As a Dash fades the car can be above top speed; settle back down.
    if (fwd_ > top_speed && !dashing) fwd_ = std::max(top_speed, fwd_ - t.over_speed_decay * dt);
    if (-fwd_ > t.reverse_top_speed && !dashing) fwd_ = std::min(-t.reverse_top_speed, fwd_ + t.over_speed_decay * dt);
}

CtOutput CtCar::update(float dt, const CtInput& in, const CtMeasured& m, const Tuning& t) {
    CtOutput out;
    dt = std::clamp(dt, 0.0f, 0.1f);
    since_drive_ += dt;
    since_reverse_ += dt;
    hop_cooldown_ = std::max(0.0f, hop_cooldown_ - dt);
    since_dash_ += dt;
    last_move_ = Move::None;

    if (!have_state_) {
        fwd_ = m.fwd;
        lat_ = m.lat;
        have_state_ = true;
    } else {
        // Our previous command, rotated by the yaw we asked for, is what the body should be doing.
        // A big difference means the game hit something: take its answer.
        const float a = yaw_ * dt;
        const float pf = fwd_ * std::cos(a) + lat_ * std::sin(a);
        const float pl = lat_ * std::cos(a) - fwd_ * std::sin(a);
        if (std::hypot(m.fwd - pf, m.lat - pl) > 5) {
            // a difference of more than 5 m/s means something's up
            fwd_ = m.fwd;
            lat_ = m.lat;
            drift_ = false;
        } else {
            fwd_ = pf;
            lat_ = pl;
        }
    }
    
    triggers(in, t);

    if (!m.grounded) {
        // In the air: no traction. Track the body and keep steering inputs out of it.
        fwd_ = m.fwd;
        lat_ = m.lat;
        yaw_ = 0;
        return out;
    }

    longitudinal(dt, in, t);

    // cancel a drift when the D button is no longer held
    drift_ = drift_ && in.drive_held;

    // Yaw rate from the stick, scaled by speed; reversed when rolling backwards.
    const float speed = std::fabs(fwd_);
    float target = in.steer * t.yaw_rate * std::min(1.0f, speed / t.yaw_ramp_speed) /
                   (1.0f + speed / t.yaw_high_speed_falloff);
    if (fwd_ < 0) target = -target;
    if (drift_) target *= t.drift_yaw_mult;
    if (speed < 0.3f) target = 0;
    yaw_ += (target - yaw_) * (1.0f - std::exp(-t.yaw_response * dt));

    // Grip: kill sideways slip, handing part of it back as forward speed.
    const float grip = !drift_ ? t.grip : t.drift_grip;
    // When braking, don't redirect the car's motion forward to do a Crazy Drift Stop 
    const float redirect = !drift_ ? t.grip_redirect: in.brake > 0.05 ? 0.0f : t.drift_redirect;
    // Slip that is killed is turned back into forward speed, never adding to the total speed.
    const float new_lat = lat_ * std::exp(-grip * dt);
    if (speed > 1.0f) fwd_ = sgn(fwd_) * std::sqrt(fwd_ * fwd_ + redirect * (lat_ * lat_ - new_lat * new_lat));
    lat_ = new_lat;

    if (in.hop && hop_cooldown_ <= 0) {
        out.set_up = true;
        out.up = t.hop_speed;
        hop_cooldown_ = t.hop_cooldown;
        last_move_ = Move::Hop;
    }

    out.active = true;
    out.fwd = fwd_;
    out.lat = lat_;
    out.yaw_rate = yaw_;
    return out;
}

}  // namespace ctmw
