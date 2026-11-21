#!/bin/bash
cd /var/tmp/gr8/recipe
cp .env .env.bak-pre-attic-20261120
sed -i -E 's|^ATTIC=.*|ATTIC=1|; s|^GR8_IMAGE=.*|GR8_IMAGE=gr8:ca7e874-attic|' .env
grep -E '^ATTIC=|^GR8_IMAGE=|^KV_STORE=' .env | tr '\n' ' '; echo
ATTIC=1 GR8_IMAGE=gr8:ca7e874-attic ./glm53 check-env 2>&1 | tail -1
test -f compose.attic.yaml && echo "compose.attic.yaml present" || echo MISSING-attic-overlay
