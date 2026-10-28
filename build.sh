#!/usr/bin/env bash
# Builds dist/scripts/CrazyTaxiMW.asi (Win32) with the VS 2026 MSVC x86 toolchain.
# Usage: ./build.sh [debug]
set -euo pipefail
cd "$(dirname "$0")"
source build/env.sh

CFG=${1:-release}
OUT=build/asi/$CFG
mkdir -p "$OUT" dist/scripts

# The gear display's textures are compiled in. They are Crazy Taxi's own, so they are not in the repository.
for f in drive reverse; do
    if [ ! -f "build/gear_display/$f.png" ]; then
        echo "missing build/gear_display/$f.png: copy Crazy Taxi's gear display textures (drive.png, reverse.png) there" >&2
        exit 1
    fi
done
python -I tools/hud/gear_textures.py build/gear_display build/gen/gear_textures.h

if [ "$CFG" = debug ]; then OPT="/Od /Zi /MTd"; else OPT="/O2 /Zi /MT /DNDEBUG"; fi

cl /nologo /std:c++20 /EHsc /W4 /permissive- $OPT /utf-8 \
   /DWIN32_LEAN_AND_MEAN /DNOMINMAX /D_CRT_SECURE_NO_WARNINGS \
   /I extern/mwsdk/include /I build/gen \
   /Fo"$OUT/" /Fd"$OUT/" \
   src/*.cpp \
   /link /DLL /INCREMENTAL:NO /OUT:dist/scripts/CrazyTaxiMW.asi /PDB:"$OUT/CrazyTaxiMW.pdb" \
   user32.lib

echo "built dist/scripts/CrazyTaxiMW.asi"
