#!/bin/bash
cd /var/tmp/gr8/recipe
cp .env .env.bak-pre-kv-20261120
grep -q '^KV_STORE=' .env || echo 'KV_STORE=ssd:/var/lib/gr8/home/kv,size=100G,persist=on,keep=all' >> .env
grep -q '^GR8_STOP_GRACE=' .env || echo 'GR8_STOP_GRACE=150s' >> .env
mkdir -p /var/tmp/gr8/home/kv
grep -E '^KV_STORE=|^GR8_STOP_GRACE=' .env
./glm53 check-env 2>&1 | tail -2
ls -ld /var/tmp/gr8/home /var/tmp/gr8/home/kv | awk '{print $3, $9}'
