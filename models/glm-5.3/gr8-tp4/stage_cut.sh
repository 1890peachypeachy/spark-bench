#!/bin/bash
cd /var/tmp/gr8/recipe
grep -q '^PORT=' .env && sed -i 's/^PORT=.*/PORT=8888/' .env || echo 'PORT=8888' >> .env
cat > /var/tmp/gr8/front-wrap.sh <<'W'
#!/bin/sh
exec /opt/gr8/bin/g6front-rs "$@" --served-model-name GLM-5.3-Flash-EXL3 glm-5.3 glm53
W
chmod +x /var/tmp/gr8/front-wrap.sh
cat > compose.override.yaml <<'O'
services:
  gr8:
    environment:
      - FRONT_BIN=/opt/gr8/front-wrap.sh
    volumes:
      - /var/tmp/gr8/front-wrap.sh:/opt/gr8/front-wrap.sh:ro
O
grep -E '^PORT=|^VARIANT=|^ATTIC=|^TP=|^PEERS=' .env
