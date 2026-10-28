# Crazy Taxi Most Wanted

Drive Axel's taxi from **Crazy Taxi 3** in **Need for Speed: Most Wanted (2005)**, with Crazy Taxi controls.

- Once in game, any selected car will be replaced visually by Axel's taxi. The garage will still show your vanilla car.
- The game now controls like Crazy Taxi, replacing your NOS and Handbrake with D/R gear buttons to perform Crazy Moves.

Requires NFS Most Wanted **v1.3** and the Ultimate ASI Loader.

## AI Disclosure

This mod was made possible through **Claude Code**. This was my experiment into vibe coding to see what it takes to make an AI slop mod. It has, unfortunately, blown away my expectations.

If you are not interested in AI slop, please support one of the many talented human modders working on NFS Most Wanted.

## Install

Download `CrazyTaxiMW.7z`from the Releases page. Extract into your game install next to `speed.exe`. `CrazyTaxiMW.asi` should be in the `/scripts/` folder, and the new model should be in `/CARS/TAXI/`.
It is recommended to back up your vanilla `/CARS/TAXI/` folder before install.


## Controls

The Crazy Taxi controls replace the existing controls:

| Action | Binding |
|---|---|
| Drive gear (**D**) | NOS |
| Reverse gear (**R**) | Handbrake |
| Crazy Hop | Speedbreaker |

### Crazy Moves

| Maneuver | How to Perform |
|---|---|
| Crazy Dash | Shift to **D** and then hit the gas.  |
| Crazy Back Dash | Shift to **R** and then hit the gas. Or, perform a **Crazy Dash**, then shift to **R**. |
| Crazy Drift | While driving, turn and shift **R** then **D** quickly. |
| Crazy Stop | Perform a **Crazy Back Dash**, then hit the brake. |
| Crazy Drift Stop | Perform a **Crazy Drift**, then hold the brake. |
| Crazy Hop | Press the hop button on the ground. |
| Limit Cut | Shift to **R** for a brief moment, then perform a **Crazy Dash**. |


### Toggle

Press F8 to turn the Crazy Taxi controls on and off. You can also disable either the controls or the car model in `/scripts/CrazyTaxiMW.ini`.

## Known Bugs

The car's body will vary in height depending on the car selected. The Cobalt and BMW look fine.

## Tuning Settings

`scripts\CrazyTaxiMW.ini` is created on first launch. All speeds are in mph, and accelerations in mph/s.

| Setting | Description |
|---|---|
| TopSpeed | The top speed without **Dashing**. |
| Accel | The acceleration rate without **Dashing**. |
| Brake | The deceleration rate when holding brake. |
| YawRate | How quickly the car turns. |
| Grip | How much you slide when not **Drifting**. Higher numbers mean less sliding. |
| DashTopSpeedMult and DashAccelMult | Multiplier to your top speed and acceleration while **Dashing**. |
| LimitCutMult | Multiplier to your top speed when using **Limit Cut**. |
| DriftYawMult | How much quicker you can turn the car while drifting. 2.0 means your car turns at **twice** your normal **YawRate**. |
| DriftGrip | How much you slide while **Drifting**. Higher numbers mean less sliding. Should be lower than **Grip**. |
| HopSpeed | How much velocity (meters/s) you gain from a **Hop**. Higher values are more likely to trigger the cinematic jump, even on flat ground. |

## How it works

Claude's notes:

| Part | Where | What |
|---|---|---|
| CT3 model extraction | `tools/ct3/` | Reads CT3's `bankNN.mdl` (GXMD: vertex pools plus Ninja-style strip display lists) and `bankNN.art` (GXTX: Xbox-swizzled 16-bit textures). Axel is driver 8, which is `bank40`. Wheel positions come from CT3.exe's car table at `0x68217C`. |
| NFS car builder | `tools/mwcar/` | Writes `CARS\TAXI\GEOMETRY.BIN` and `TEXTURES.BIN`, using the stock taxi as a template. The serializer reproduces stock files byte for byte. Textures are JDLZ-packed A8R8G8B8. |
| Model swap | `src/model_swap.cpp` | Two call-site hooks in the CarRenderConn factory. The player's render becomes CarType TAXI with stock parts, and the wheels are moved to the taxi's wheelbase. |
| Handling | `src/handling.cpp`, `src/ctphysics.cpp` | Hooks `InputPlayer::OnTaskSimulate` (vtable slot `0x8AC6D4`). The Crazy Taxi model then sets the rigid body's velocity and yaw each sim tick. NFS still handles collisions, gravity, and suspension. |

### Build

#### Requirements

- Visual Studio 2026 with the MSVC x86 tools and a Windows 10 SDK.
- Git for Windows. The build scripts run in Git Bash.
- Python 3 with Pillow (`pip install pillow`).
- Your own copies of Crazy Taxi 3 (PC) and NFS Most Wanted v1.3. No game files are in this repository.

#### Get the source

MWSDK is a submodule, so clone recursively:

```bash
git clone --recursive <repo url>
# or, in an existing clone:
git submodule update --init
```

#### Set up

1. `build/env.sh` finds Visual Studio (through vswhere) and the newest Windows SDK by itself, instead of using vcvars. To use a different toolset or SDK, set `MSVC`, `WK` or `WKV` before running the build scripts.
2. Copy or link your game installs into the repository root, as `Crazy Taxi 3/` (the folder containing `CT3.exe` and `Media/`) and `NFS Most Wanted/` (the folder containing `speed.exe` and `CARS/TAXI/`).
3. Put Crazy Taxi's gear display textures in `build/gear_display/`, named `drive.png` and `reverse.png` (64x64 RGBA). They are compiled into the `.asi`, and `build.sh` stops if they are missing.

#### Build

From Git Bash in the repository root:

```bash
./build_car.sh          # dist/CARS/TAXI from your own CT3 + NFS installs
./build.sh              # dist/scripts/CrazyTaxiMW.asi (./build.sh debug for a debug build)
```

`build_car.sh` takes an optional driver name (default `axel`). It keeps a pristine copy of the stock taxi in `build/orig/TAXI/` the first time it runs, so run it before installing the mod's `CARS/TAXI` over your game.

Then install the contents of `dist/` into your game folder, as described under **Install**.

#### Tests

The handling model has offline tests, built with the same environment:

```bash
source build/env.sh
cl /std:c++20 /EHsc tests/ctphysics_test.cpp src/ctphysics.cpp
./ctphysics_test.exe
```

## Credits

**Claude Code**

Reverse-engineering, file conversion, mod development.

**Ham★**

Lead "programmer", rewrote much of the Crazy Taxi physics code.

**TsyVM**

[MWSDK](https://github.com/tsyvm/mwsdk) (MIT)

**ThirteenAG and contributors**

[Ultimate ASI Loader](https://github.com/ThirteenAG/Ultimate-ASI-Loader) (MIT)

**stashymane**

[taxipatch](https://github.com/stashymane/taxipatch) referenced by Claude to assist in reverse-engineering CT3

