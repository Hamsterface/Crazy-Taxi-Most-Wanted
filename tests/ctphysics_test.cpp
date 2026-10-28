// Offline checks for the Crazy Taxi handling model (src/ctphysics.cpp).
// The "body" here simply does what the model asks, like a perfectly obedient NFS rigid body.
#include <cmath>
#include <cstdio>

#include "../src/ctphysics.h"

using namespace ctmw;

namespace {

int g_failures = 0;
#define CHECK(cond, ...)                                  \
    do {                                                  \
        if (!(cond)) {                                    \
            ++g_failures;                                 \
            std::printf("FAIL %s:%d: ", __FILE__, __LINE__); \
            std::printf(__VA_ARGS__);                     \
            std::printf("\n");                            \
        }                                                 \
    } while (0)

struct Sim {
    CtCar car;
    Tuning t;
    float fwd = 0, lat = 0, heading = 0, time = 0;
    bool grounded = true;
    const float dt = 1.0f / 60.0f;
    CtOutput last;

    void step(const CtInput& in) {
        CtMeasured m{fwd, lat, 0, grounded};
        last = car.update(dt, in, m, t);
        if (last.active) {
            // body follows the command, then rotates by the yaw rate
            const float a = last.yaw_rate * dt;
            fwd = last.fwd * std::cos(a) + last.lat * std::sin(a);
            lat = last.lat * std::cos(a) - last.fwd * std::sin(a);
            heading += a;
        }
        time += dt;
    }
    void run(float seconds, const CtInput& in) {
        for (float s = 0; s < seconds; s += dt) step(in);
    }
    // Runs and returns the highest forward speed seen.
    float peak(float seconds, const CtInput& in) {
        float p = fwd;
        for (float s = 0; s < seconds; s += dt) {
            step(in);
            p = std::fmax(p, fwd);
        }
        return p;
    }
};

// Hold the gas until the car is at top speed, however long the tuning takes.
void cruise(Sim& s) {
    for (int i = 0; i < 60 * 300 && s.fwd < s.t.top_speed - 0.2f; ++i) s.step(CtInput{0, 1});
}

CtInput gas(float g = 1, float steer = 0) {
    CtInput in;
    in.gas = g;
    in.steer = steer;
    return in;
}

CtInput shift_d(float g = 0, float steer = 0) {
    CtInput in = gas(g, steer);
    in.shift_drive = true;
    in.drive_held = true;
    return in;
}

CtInput shift_r(float g = 0, float steer = 0) {
    CtInput in = gas(g, steer);
    in.shift_reverse = true;
    return in;
}

// Off the gas for a tick, then shift to D and hit the gas on the same tick.
void dash(Sim& s) {
    s.step(CtInput{});
    s.step(shift_d(1));
}

// Off the gas, hold R for `hold` seconds, then shift to D and hit the gas.
void limit_cut(Sim& s, float hold = 0.5f) {
    s.step(shift_r());
    s.run(hold, CtInput{});
    s.step(shift_d());
    s.step(gas());
}

// At speed and steering, tap R then D quickly with D held.
void drift(Sim& s, float steer = 0.8f) {
    s.step(shift_r(1, steer));
    s.run(0.12f, gas(1, steer));
    s.step(shift_d(1, steer));
}

}  // namespace

int main() {
    {  // Plain acceleration: 0 -> 100 km/h (27.8 m/s), then holds top speed
        Sim s;
        while (s.fwd < 27.8f && s.time < 30) s.step(gas());
        std::printf("0-100 km/h: %.2f s\n", s.time);
        CHECK(s.time > 3.0f && s.time < 15.0f, "0-100 took %.2f s", s.time);
        cruise(s);
        s.run(1, gas());
        CHECK(std::fabs(s.fwd - s.t.top_speed) < 0.5f, "top speed %.2f", s.fwd);
    }
    {  // No free Dash from a fresh or reset car
        Sim s;
        s.step(gas());
        CHECK(!s.car.dashing(s.t), "fresh car is dashing");
        CHECK(s.fwd <= s.t.accel * s.dt + 0.001f, "fresh car accelerates like a dash: %.3f", s.fwd);
        dash(s);
        CHECK(s.car.dashing(s.t), "dash ran");
        s.car.reset();
        s.step(CtInput{});
        CHECK(!s.car.dashing(s.t), "reset car is dashing");
        s.step(shift_d(1));
        CHECK(s.car.last_move() == Move::Dash, "reset blocked the next dash");
    }
    {  // Crazy Dash: shift to D then hit the gas
        Sim s;
        s.step(shift_d());
        s.run(0.2f, CtInput{});
        s.step(gas());
        CHECK(s.car.last_move() == Move::Dash, "shift-then-gas: no dash");
        Sim same_tick;
        dash(same_tick);
        CHECK(same_tick.car.last_move() == Move::Dash, "shift and gas on one tick: no dash");
    }
    {  // Crazy Dash from standstill is much quicker than plain gas, and lasts dash_time
        Sim s, plain;
        dash(s);
        plain.step(CtInput{});
        plain.step(gas());
        s.run(0.5f, gas());
        plain.run(0.5f, gas());
        std::printf("dash from standstill: %.1f m/s after 0.5 s (plain gas %.1f)\n", s.fwd, plain.fwd);
        CHECK(s.fwd > plain.fwd * 2, "dash too weak: %.2f vs %.2f", s.fwd, plain.fwd);
        s.run(s.t.dash_time - 0.6f, gas());
        CHECK(s.car.dashing(s.t), "dash ended early");
        s.run(0.2f, gas());
        CHECK(!s.car.dashing(s.t), "dash lasted over dash_time");
    }
    {  // No Dash without a fresh gas press inside the window
        Sim held;
        held.step(gas());
        held.step(shift_d(1));
        CHECK(held.car.last_move() != Move::Dash, "D shift with gas already held dashed");
        Sim late;
        late.step(shift_d());
        late.run(late.t.dash_window + 0.05f, CtInput{});
        late.step(gas());
        CHECK(late.car.last_move() != Move::Dash, "gas after the window dashed");
        Sim none;
        none.run(1.0f, CtInput{});
        none.step(gas());
        CHECK(none.fwd < 1, "plain gas dashed, speed %.2f", none.fwd);
    }
    {  // No new Dash until dash_time + dash_cooldown after the last one started
        Sim s;
        dash(s);
        s.run(s.t.dash_time + s.t.dash_cooldown - 0.1f, CtInput{});
        s.step(shift_d(1));
        CHECK(s.car.last_move() != Move::Dash, "dashed again during cooldown");
        s.run(0.15f, CtInput{});
        s.step(shift_d(1));
        CHECK(s.car.last_move() == Move::Dash, "no dash after cooldown");
    }
    {  // Crazy Dash at top speed passes it, stays under the cap, then settles back
        Sim s;
        cruise(s);
        const float before = s.fwd;
        dash(s);
        const float peak = s.peak(s.t.dash_time, gas());
        std::printf("dash at speed: %.1f -> peak %.1f m/s\n", before, peak);
        CHECK(peak > before + 3, "no dash at speed: %.2f -> %.2f", before, peak);
        CHECK(peak <= s.t.top_speed * s.t.dash_top_speed_mult + 0.01f, "dash over cap %.2f", peak);
        s.run((s.t.dash_top_speed_mult - 1) * s.t.top_speed / s.t.over_speed_decay + 1, gas());
        CHECK(std::fabs(s.fwd - s.t.top_speed) < 0.5f, "did not settle back to top speed: %.2f", s.fwd);
    }
    {  // A Dash keeps boosting in R: shifting to R mid-Dash stops the car much faster
        Sim s, plain;
        cruise(s);
        cruise(plain);
        const float before = s.fwd;
        dash(s);
        s.step(shift_r(1));
        s.run(0.5f, gas());
        plain.step(shift_r(1));
        plain.run(0.5f, gas());
        std::printf("R with gas for 0.5 s from %.1f m/s: %.1f in a dash, %.1f plain\n", before, s.fwd, plain.fwd);
        CHECK(before - s.fwd > 3 * (before - plain.fwd), "dash did not boost in R: %.2f vs %.2f", s.fwd, plain.fwd);
    }
    {  // Limit Cut: hold R briefly, then Dash. Higher cap than a Dash.
        Sim s;
        cruise(s);
        limit_cut(s);
        CHECK(s.car.last_move() == Move::LimitCut, "no limit cut");
        const float peak = s.peak(s.t.dash_time, gas());
        std::printf("limit cut at speed: peak %.1f m/s (dash cap %.1f)\n", peak,
                    s.t.top_speed * s.t.dash_top_speed_mult);
        CHECK(peak > s.t.top_speed * s.t.dash_top_speed_mult + 1, "limit cut no faster than a dash: %.2f", peak);
        CHECK(peak <= s.t.top_speed * s.t.limit_cut_mult + 0.01f, "limit cut over cap %.2f", peak);
    }
    {  // Limit Cut needs the R hold to be inside its window
        Sim quick;
        limit_cut(quick, quick.t.min_limit_cut_delay - 0.1f);
        CHECK(quick.car.last_move() == Move::Dash, "short R hold: expected a plain dash");
        Sim slow;
        limit_cut(slow, slow.t.max_limit_cut_delay + 0.1f);
        CHECK(slow.car.last_move() == Move::Dash, "long R hold: expected a plain dash");
    }
    {  // A running Dash cannot become a Limit Cut
        Sim s;
        cruise(s);
        dash(s);
        s.run(0.1f, gas());
        s.step(shift_r());
        s.run(0.4f, CtInput{});
        s.step(shift_d());
        const float peak = s.peak(s.t.dash_time, gas());
        CHECK(peak <= s.t.top_speed * s.t.dash_top_speed_mult + 0.01f, "dash turned into a limit cut: %.2f", peak);
    }
    {  // ... and a running Limit Cut is not cancelled by an R tap
        Sim s;
        cruise(s);
        limit_cut(s);
        s.run(0.1f, gas());
        s.step(shift_r(1));
        s.run(0.1f, gas());
        s.step(shift_d(1));
        const float peak = s.peak(s.t.dash_time, gas());
        CHECK(peak > s.t.top_speed * s.t.dash_top_speed_mult + 1, "R tap cancelled the limit cut: %.2f", peak);
    }
    {  // Crazy Back Dash: shift to R then hit the gas, from standstill
        Sim s;
        s.step(shift_r());
        s.run(0.1f, CtInput{});
        s.step(gas());
        CHECK(s.car.last_move() == Move::BackDash, "no back dash");
        s.run(0.5f, gas());
        Sim plain;
        plain.step(shift_r());
        plain.run(1.0f, CtInput{});  // past the dash window, so plain reverse
        plain.step(gas());
        plain.run(0.5f, gas());
        std::printf("back dash from standstill: %.1f m/s after 0.5 s (plain reverse %.1f)\n", s.fwd, plain.fwd);
        CHECK(s.fwd < plain.fwd * 1.5f, "back dash too weak: %.2f vs %.2f", s.fwd, plain.fwd);
        CHECK(-s.fwd <= s.t.reverse_top_speed + 0.01f, "back dash over reverse top speed %.2f", s.fwd);
    }
    {  // A Back Dash stops boosting in D, but still counts as a running Dash
        Sim s;
        s.step(shift_r(1));
        CHECK(s.car.last_move() == Move::BackDash, "no back dash");
        s.run(0.3f, gas());
        const float before = s.fwd, t0 = s.time;
        s.step(shift_d(1));
        s.run(0.3f, gas());
        CHECK(s.fwd - before <= s.t.accel * (s.time - t0) + 0.01f, "back dash boosted in D: %.2f -> %.2f", before,
              s.fwd);
        CHECK(s.car.dashing(s.t), "back dash stopped counting in D");
    }
    {  // Dash and Back Dash share one cooldown
        Sim s;
        dash(s);
        s.run(0.3f, gas());
        s.step(shift_r());
        s.step(gas());
        CHECK(s.car.last_move() != Move::BackDash, "back dash during dash cooldown");
        s.run(s.t.dash_time + s.t.dash_cooldown, CtInput{});
        s.step(shift_r(1));
        CHECK(s.car.last_move() == Move::BackDash, "no back dash after cooldown");
        s.run(0.3f, CtInput{});
        s.step(shift_d(1));
        CHECK(s.car.last_move() != Move::Dash, "dash during back dash cooldown");
    }
    {  // Crazy Stop: Back Dash at speed, then brake. Much faster than braking in R without a Dash.
        Sim a, b;
        cruise(a);
        cruise(b);
        CtInput brake;
        brake.brake = 1;
        a.step(shift_r());
        float ta = 0, tb = 0;
        while (a.fwd > 0.5f && ta < 10) {
            a.step(brake);
            ta += a.dt;
        }
        b.step(CtInput{});
        b.step(shift_r(1));
        CHECK(b.car.last_move() == Move::BackDash, "no back dash");
        while (b.fwd > 0.5f && tb < 10) {
            b.step(brake);
            tb += b.dt;
        }
        std::printf("stop from %.1f m/s: brake in R %.2f s, Crazy Stop %.2f s\n", a.t.top_speed, ta, tb);
        CHECK(tb < ta * 0.6f, "crazy stop not faster (%.2f vs %.2f)", tb, ta);
    }
    {  // Crazy Drift: at speed, steering, R then D quickly. Holding D keeps it going.
        Sim s;
        cruise(s);
        const float before = s.fwd;
        drift(s);
        CHECK(s.car.last_move() == Move::Drift, "no drift move");
        CHECK(s.car.drifting(), "not drifting");
        CtInput hold = gas(1, 0.8f);
        hold.drive_held = true;
        float max_slip = 0;
        const float h0 = s.heading;
        for (int i = 0; i < 60; ++i) {
            s.step(hold);
            max_slip = std::fmax(max_slip, std::fabs(s.lat));
        }
        std::printf("drift: speed %.1f -> %.1f, max slip %.1f m/s, turned %.0f deg in 1 s\n", before, s.fwd, max_slip,
                    (s.heading - h0) * 57.3f);
        CHECK(max_slip > 3, "drift slip too small: %.2f", max_slip);
        CHECK(s.fwd > before * 0.6f, "drift lost too much speed: %.2f", s.fwd);
        s.run(1.0f, hold);
        CHECK(s.car.drifting(), "held drift ended by itself");
        CtInput counter = hold;
        counter.steer = -1;
        s.step(counter);
        CHECK(s.car.drifting(), "counter-steer ended the drift");
        s.step(gas(1, 0.8f));
        CHECK(!s.car.drifting(), "releasing D did not end the drift");
    }
    {  // No drift without steering: R -> D is then a Dash setup
        Sim straight;
        cruise(straight);
        drift(straight, 0);
        CHECK(!straight.car.drifting(), "drifted without steering");
    }
    {  // Drifting from a stop turns the car around. Gas on the R tap would be a Back Dash, so it comes after.
        Sim s;
        s.step(shift_r(0, 1));
        s.run(0.12f, gas(0, 1));
        s.step(shift_d(0, 1));
        CHECK(s.car.drifting(), "no drift from a stop");
        CtInput hold = gas(1, 1);
        hold.drive_held = true;
        const float h0 = s.heading;
        s.run(1.5f, hold);
        std::printf("drift from a stop: turned %.0f deg in 1.5 s, speed %.1f m/s\n", (s.heading - h0) * 57.3f,
                    std::hypot(s.fwd, s.lat));
        CHECK(s.car.drifting(), "drift from a stop ended");
        CHECK(s.heading - h0 > 1.5f, "drift from a stop barely turned: %.0f deg", (s.heading - h0) * 57.3f);
    }
    {  // Ending a drift never makes the car faster than it was going
        Sim s;
        cruise(s);
        drift(s, 1);
        CtInput hold = gas(1, 1);
        hold.drive_held = true;
        s.run(1.0f, hold);
        float peak = 0;
        for (int i = 0; i < 120; ++i) {
            s.step(gas());
            peak = std::fmax(peak, std::hypot(s.fwd, s.lat));
        }
        std::printf("after drift: peak speed %.1f m/s (top %.1f)\n", peak, s.t.top_speed);
        CHECK(peak < s.t.top_speed + 1.0f, "drift exit overshoots to %.2f", peak);
    }
    {  // Crazy Drift Stop: braking in a drift does not hand slip back as forward speed
        Sim s;
        cruise(s);
        drift(s);
        CtInput hold = gas(1, 0.8f);
        hold.drive_held = true;
        s.run(0.3f, hold);
        CtInput stop = hold;
        stop.gas = 0;
        stop.brake = 1;
        Sim straight;
        straight.fwd = std::hypot(s.fwd, s.lat);
        const float before = straight.fwd;
        CtInput brake;
        brake.brake = 1;
        s.run(0.5f, stop);
        straight.run(0.5f, brake);
        const float drift_speed = std::hypot(s.fwd, s.lat);
        std::printf("drift stop: %.1f -> %.1f m/s in 0.5 s (straight brake %.1f)\n", before, drift_speed,
                    straight.fwd);
        CHECK(s.car.drifting(), "braking ended the drift");
        CHECK(drift_speed <= straight.fwd + 0.5f, "drift stop slower than braking: %.2f vs %.2f", drift_speed,
              straight.fwd);
    }
    {  // Normal cornering keeps slip small
        Sim s;
        cruise(s);
        float max_slip = 0;
        for (int i = 0; i < 60; ++i) {
            s.step(gas(1, 1));
            max_slip = std::fmax(max_slip, std::fabs(s.lat));
        }
        std::printf("grip turn at %.1f m/s: max slip %.1f m/s\n", s.t.top_speed, max_slip);
        CHECK(max_slip < 0.2f * s.t.top_speed, "grip turn slips %.2f", max_slip);
    }
    {  // Hop: once, then cooldown
        Sim s;
        CtInput in;
        in.hop = true;
        s.step(in);
        CHECK(s.last.set_up && s.last.up > 0, "no hop");
        CHECK(s.car.last_move() == Move::Hop, "hop not reported");
        s.step(in);
        CHECK(!s.last.set_up, "hop ignored cooldown");
        s.run(s.t.hop_cooldown, CtInput{});
        s.step(in);
        CHECK(s.last.set_up, "no hop after cooldown");
    }
    {  // Collision: the game stopping the body is adopted, not fought
        Sim s;
        s.run(5, gas());
        s.fwd = 0;  // wall
        s.lat = 0;
        s.step(CtInput{});
        CHECK(s.last.fwd < 3, "model ignored the wall, commanded %.2f", s.last.fwd);
    }
    {  // Airborne: hands off
        Sim s;
        s.run(3, gas());
        s.grounded = false;
        s.step(gas(1, 1));
        CHECK(!s.last.active, "model drove the car in the air");
    }
    std::printf(g_failures ? "%d FAILED\n" : "all handling checks passed\n", g_failures);
    return g_failures ? 1 : 0;
}
