#!/bin/bash
# spark3, lane DOWN. gr8 a3f44a0 (v1.1.1) + attic client (382a62d6 rebased, regenerated knob tables)
# -> gr8:a3f44a0-attic-base, then the recipe's thin layer (f94ccfd) -> gr8:a3f44a0-attic
cd /var/tmp/gr8-build/src-a3f44a0 || exit 1
LOG=/var/tmp/gr8-build/build-a3f44a0.log
echo "$(date +%T) build start (GR8_WIDTHS=4)" > $LOG
docker build --progress=plain --build-arg GR8_WIDTHS=4 -t gr8:a3f44a0-attic-base . >> $LOG 2>&1; rc=$?
echo "$(date +%T) base build exit=$rc" >> $LOG
[ $rc = 0 ] || { echo BUILD_FAIL >> $LOG; exit 1; }
cd /var/tmp/gr8/recipe && docker build --build-arg GR8_IMAGE=gr8:a3f44a0-attic-base -t gr8:a3f44a0-attic . >> $LOG 2>&1; rc=$?
echo "$(date +%T) thin build exit=$rc" >> $LOG
[ $rc = 0 ] && echo BUILD_OK >> $LOG || echo BUILD_FAIL >> $LOG
