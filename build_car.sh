#!/usr/bin/env bash
# Rebuilds dist/CARS/TAXI from your own Crazy Taxi 3 and NFS Most Wanted installs.
# Usage: ./build_car.sh [driver]   (default axel; others: gus gena bdjoe hotd cinnamon iceman slash zax venus bixbite angel)
set -euo pipefail
cd "$(dirname "$0")"
DRIVER=${1:-axel}
CT3="Crazy Taxi 3"
NFS="NFS Most Wanted"

# Keep a pristine copy of the stock taxi: the builder clones it, and the game folder may already be modded.
if [ ! -f build/orig/TAXI/GEOMETRY.BIN ]; then
    mkdir -p build/orig/TAXI
    cp "$NFS/CARS/TAXI/"*.BIN build/orig/TAXI/
fi

python -I tools/ct3/export_car.py "$CT3" "build/ct3_$DRIVER" "$DRIVER"
python -I tools/mwcar/build_taxi.py "build/ct3_$DRIVER/$DRIVER.json" build/orig/TAXI dist/CARS/TAXI
