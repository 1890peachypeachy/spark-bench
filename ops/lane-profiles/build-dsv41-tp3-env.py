#!/usr/bin/env python3
"""Build our fleet's .env for the DeepSeek V4.1-Flash-1017 3-Spark (TP3) lane.

Recipe: Mia's MiaAI-Lab/DeepSeek-v4.1-Flash-DGX-Sparks, via our fork
1890peachypeachy/DeepSeek-v4.1-Flash-DGX-Sparks (main). Its .env.example IS the tuned
3-Spark profile (EP1, DSPARK, fp8 draft head, chunked prefill 768, ...), so this builder
changes ONLY:

  1. fleet identity / topology   (spark3 head; spark1 + spark4 workers; per-node users)
  2. the CX7 fabric block        (CRS504 switch, only live rail rocep1s0f1, GID index 3)
  3. the 1017 weight + Engram paths (fresh pack dirs: Engram shards are weight-specific)
  4. the served identity         (:8888 + GLM-5.3-Flash-EXL3, so Hermes configs never change)

Everything else is left exactly as Mia tuned it. Wanting to edit a tuning value here means
the change belongs upstream, not in this file. NFS_DEVICE / NFS_REUSE_EXPORT are computed by
files/nfs-share.sh at `share` time (shared-parent export) and must NOT be pinned here.

Usage:  python3 build-dsv41-tp3-env.py [kit_dir]     writes <kit_dir>/.env, exits 1 on drift.
"""
import os
import re
import sys

KIT = sys.argv[1] if len(sys.argv) > 1 else "."
EXAMPLE = os.path.join(KIT, ".env.example")
OUT = os.path.join(KIT, ".env")

HF_REVISION = "1bae0e1088993b9b82de08f59de5be5a34e42170"
IDENTITY = "GLM-5.3-Flash-EXL3"

OVER = {
    # 1. topology: spark3 head, spark1 (user spark) and spark4 (user spark4) workers
    "HEAD_IP": "10.73.0.3",
    "WORKER1_IP": "10.73.0.1",
    "WORKER2_IP": "10.73.0.4",
    "WORKER1_HOST": "spark@10.73.0.1",
    "WORKER2_HOST": "spark4@10.73.0.4",
    "WORKER_USER": "spark",
    "WORKER_USER_MAP": "10.73.0.1=spark,10.73.0.3=spark3,10.73.0.4=spark4",
    "WORKER_DIR": "/var/tmp/dsv41-3x-spark",
    # 2. CX7 RoCE fabric (proven values from the live TP3 profile)
    "GLOO_SOCKET_IFNAME": "enp1s0f1np1",
    "NCCL_SOCKET_IFNAME": "enp1s0f1np1",
    "IB_HCA": "rocep1s0f1",
    "NCCL_IB_HCA": "rocep1s0f1",
    "NCCL_IB_GID_INDEX": "3",
    "NCCL_IB_ADDR_RANGE": "10.73.0.0/24",
    "NCCL_DEBUG": "WARN",
    "NFS_SERVER_IPS": "10.73.0.3",
    "NFS_SERVER_IP_1": "10.73.0.3",
    "NFS_SERVER_IP_2": "10.73.0.3",
    "NFS_CLIENTS": "10.73.0.0/24",
    # 3. 1017 weights, served from the dsv41-nfs export root /var/tmp/models (shared parent).
    #    COMMON_MODEL must differ from MODEL_DIR: `ln -sfn MODEL_DIR COMMON_MODEL` onto an
    #    existing real dir plants a self-link INSIDE the checkpoint.
    "MODEL_DIR": "/var/tmp/models/DeepSeek-V4.1-Flash-1017",
    "COMMON_MODEL": "/var/tmp/DeepSeek-V4.1-Flash-1017",
    # TP3 packs are NOT interchangeable with the TP4 packs (shard names carry the TP size,
    # and the owned rows differ), so TP3 gets its own dirs.
    "ENGRAM_DIR": "/var/tmp/dsv41-engram-1017-tp3",
    "WORKER_ENGRAM_DIR": "/var/tmp/dsv41-engram-1017-tp3",
    # 4. stable client identity
    "PORT": "8888",
    "SERVED_MODEL_NAME": IDENTITY,
}

# Keys that must never be pinned: computed by nfs-share.sh at share time.
FORBIDDEN = ("NFS_DEVICE", "NFS_REUSE_EXPORT")


def main():
    with open(EXAMPLE) as fh:
        lines = fh.read().splitlines()

    present = set()
    for i, line in enumerate(lines):
        m = re.match(r"^([A-Z_][A-Z0-9_]*)=", line)
        if m and m.group(1) in OVER:
            lines[i] = f"{m.group(1)}={OVER[m.group(1)]}"
            present.add(m.group(1))
    missing = [k for k in OVER if k not in present]
    if missing:
        lines.append("")
        lines.append("# -- fleet overrides added by spark-bench build-dsv41-tp3-env.py --")
        lines.extend(f"{k}={OVER[k]}" for k in missing)

    with open(OUT, "w") as fh:
        fh.write("\n".join(lines).rstrip() + "\n")

    active = {}
    for line in lines:
        m = re.match(r"^([A-Z_][A-Z0-9_]*)=(.*)$", line)
        if m:
            active[m.group(1)] = m.group(2)

    checks = [
        ("HEAD_IP", "10.73.0.3"), ("WORKER1_HOST", "spark@10.73.0.1"), ("WORKER2_HOST", "spark4@10.73.0.4"),
        ("IB_HCA", "rocep1s0f1"), ("NCCL_IB_HCA", "rocep1s0f1"), ("NCCL_IB_GID_INDEX", "3"),
        ("MODEL_DIR", "/var/tmp/models/DeepSeek-V4.1-Flash-1017"),
        ("COMMON_MODEL", "/var/tmp/DeepSeek-V4.1-Flash-1017"),
        ("ENGRAM_DIR", "/var/tmp/dsv41-engram-1017-tp3"),
        ("PORT", "8888"), ("SERVED_MODEL_NAME", IDENTITY),
        ("TP_SIZE", "3"), ("EP_SIZE", "1"), ("NNODES", "3"), ("NFS_SHARE", "1"),
    ]
    bad = []
    print(f"wrote {OUT}  ({len(lines)} lines, example={os.path.basename(EXAMPLE)})")
    for k, want in checks:
        got = active.get(k, "<missing>")
        ok = got == want
        print(f"  {'OK  ' if ok else 'FAIL'} {k}={got}")
        if not ok:
            bad.append(f"{k}={got} (want {want})")
    for k in FORBIDDEN:
        if k in active:
            bad.append(f"{k} is pinned ({active[k]}); nfs-share.sh computes it")
    if active.get("MODEL_DIR") == active.get("COMMON_MODEL"):
        bad.append("COMMON_MODEL equals MODEL_DIR (self-link trap)")
    if active.get("ENGRAM_DIR", "").rstrip("/") in ("/var/tmp/dsv41-engram-1017", "/home/spark3/dsv41-engram-1017",
                                                      "/var/tmp/dsv41-engram"):
        bad.append("ENGRAM_DIR collides with an existing TP4/old pack dir")
    if (active.get("API_KEY") or "").strip():
        bad.append("API_KEY is set; fleet lanes are open on the tailnet")
    # start.sh pins the 1017 revision as its default; make sure nothing overrides it elsewhere.
    rev = active.get("HF_REVISION", HF_REVISION)
    if rev != HF_REVISION:
        bad.append(f"HF_REVISION={rev} (want {HF_REVISION})")
    if bad:
        print("\nBUILD FAILED:")
        for b in bad:
            print(f"  - {b}")
        sys.exit(1)
    print("RESULT: PASS - .env ready")


if __name__ == "__main__":
    main()
