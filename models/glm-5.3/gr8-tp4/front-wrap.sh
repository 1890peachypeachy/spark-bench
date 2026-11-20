#!/bin/sh
# gr8 front end with our served names: the launcher passes no --served-model-name (front end default: glm-5.3 glm53).
# First name is reported in responses. Keeps the pinned profile name GLM-5.3-Flash-EXL3 answering on :8888.
exec /opt/gr8/bin/g6front-rs "$@" --served-model-name GLM-5.3-Flash-EXL3 glm-5.3 glm53
