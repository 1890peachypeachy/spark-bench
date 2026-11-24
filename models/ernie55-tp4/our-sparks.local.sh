#!/usr/bin/env bash
# Fleet config for the ERNIE lane (host-local, git-ignored). Rank order matches the live containers.
NODES=(local spark@10.73.0.1 spark2@10.73.0.2 spark4@10.73.0.4)
FABRIC_IPS=(10.73.0.3 10.73.0.1 10.73.0.2 10.73.0.4)
MODEL_DIR=/var/tmp/models/ERNIE-5.5-Flash-Preview
CACHE_DIR=/var/tmp/ernie55/cache
# Fleet identity contract: every lane serves :8888 under this name so no client config changes on a swap.
SERVED_NAME=GLM-5.3-Flash-EXL3
BIND_HOST=0.0.0.0
