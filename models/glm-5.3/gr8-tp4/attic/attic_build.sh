#!/bin/bash
# spark3, lane DOWN. gr8 ca7e874 + attic client (382a62d6) -> gr8:ca7e874-attic-base, then the recipe's thin layer -> gr8:ca7e874-attic
cd /var/tmp/gr8-build/src || exit 1
LOG=/var/tmp/gr8-build/build.log
echo "$(date +%T) build start (GR8_WIDTHS=4)" > $LOG
docker build --progress=plain --build-arg GR8_WIDTHS=4 -t gr8:ca7e874-attic-base . >> $LOG 2>&1; rc=$?
echo "$(date +%T) base build exit=$rc" >> $LOG
[ $rc = 0 ] || { echo BUILD_FAIL >> $LOG; exit 1; }
cd /var/tmp/gr8/recipe && docker build --build-arg GR8_IMAGE=gr8:ca7e874-attic-base -t gr8:ca7e874-attic . >> $LOG 2>&1; rc=$?
echo "$(date +%T) thin build exit=$rc" >> $LOG
[ $rc = 0 ] && echo BUILD_OK >> $LOG || echo BUILD_FAIL >> $LOG
