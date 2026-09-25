#!/usr/bin/env python3
"""Build our fleet's .env.tp4 for the DeepSeek V4.1-Flash 4-Spark production line.

Deterministic on purpose: any model can run it and get the same file. It starts from
the kit's own .env.tp4.example (upstream truth) and changes ONLY

  1. fleet identity / topology / paths  (our nodes, our users, our mount points)
  2. the served port                    (PORT=8000, so the OpenAI URL never moves)
  3. the 4-Spark production line         (activate upstream's last EXTRA_CONTAINER_ENV,
                                          EP_SIZE=1, Dockerfile.canary-roce image)

Everything else - memory split, MAX_TOTAL_TOKENS, MAX_RUNNING_REQUESTS, chunked-prefill,
Engram budget, DSPARK draft knobs - is left exactly as upstream tuned it for TP4. If you
find yourself wanting to edit a tuning value here, that is a recipe change: it belongs
upstream, not in this file.

Usage:  python3 build-dsv41-tp4-env.py [kit_dir]
Writes: <kit_dir>/.env.tp4   and prints a verification summary.
"""
import os
import re
import sys

KIT = sys.argv[1] if len(sys.argv) > 1 else "."
EXAMPLE = os.path.join(KIT, ".env.tp4.example")
OUT = os.path.join(KIT, ".env.tp4")

# ── 1. fleet identity / topology / paths ─────────────────────────────────────
# Head is spark3. Workers are spark1, spark2, spark4. Usernames differ per node on
# our fleet, so WORKER_HOSTS carries user@host and the launcher must NOT prepend
# WORKER_USER (see cmd_build in start.sh).
OVER = {
    "HEAD_IP": "10.73.0.3",
    "WORKER_IPS": '"10.73.0.1 10.73.0.2 10.73.0.4"',
    "WORKER_HOSTS": '"spark@10.73.0.1 spark2@10.73.0.2 spark4@10.73.0.4"',
    "WORKER_USER": "spark",
    "WORKER_USER_MAP": "10.73.0.1=spark,10.73.0.2=spark2,10.73.0.3=spark3,10.73.0.4=spark4",
    "SSH_IDENTITY": "$HOME/.ssh/id_ed25519_shared",
    "WORKER_DIR": "/var/tmp/dsv41-4x-spark",
    "MODEL_DIR": "/var/tmp/models/DeepSeek-V4.1-Flash",
    "COMMON_MODEL": "/var/tmp/models/DeepSeek-V4.1-Flash",
    # ── 2. stable endpoint: clients keep using :8000/v1 across TP3<->TP4 swaps ──
    "PORT": "8000",
    # ── 3. CX7 RoCE fabric (mirrors the proven values in the TP3 profile) ──────
    "FABRIC_IFACE": "enp1s0f1np1",
    "GLOO_SOCKET_IFNAME": "enp1s0f1np1",
    "NCCL_SOCKET_IFNAME": "enp1s0f1np1",
    "IB_HCA": "rocep1s0f1",
    "NCCL_IB_HCA": "rocep1s0f1",
    "NCCL_IB_GID_INDEX": "3",
    "NCCL_IB_ADDR_RANGE": "10.73.0.0/24",
    "NCCL_NET": "IB",
    "NCCL_IB_DISABLE": "0",
    "NCCL_P2P_DISABLE": "1",
    "NCCL_SHM_DISABLE": "1",
    "NCCL_DEBUG": "WARN",
    "NCCL_BUFFSIZE": "1048576",
    "NCCL_LL128_BUFFSIZE": "262144",
    "NCCL_PROTO": "^LL128",
    "NCCL_MAX_NCHANNELS": "8",
    "NCCL_DEBUG_SUBSYS": "INIT,ENV",
    "NCCL_HOST_DIR": "$HOME/nccl-2.30.7",
    # weights served from the head over NFSv4 on the fabric
    "NFS_SHARE": "1",
    "NFS_VOLUME": "dsv41-weights-4x",
    "NFS_EXPORT_NAME": "dsv41-native-4x",
    "NFS_SERVER_IPS": "10.73.0.3",
    "NFS_SERVER_IP_1": "10.73.0.3",
    "NFS_SERVER_IP_2": "10.73.0.3",
    "NFS_CLIENTS": "10.73.0.0/24",
    # ── 4. production 4-Spark line ─────────────────────────────────────────────
    "EP_SIZE": "1",                                  # required with the line below
    "IMAGE": "dsv41-4x-spark:canary-roce",
    "BUILD_DOCKERFILE": "Dockerfile.canary-roce",
}

# Upstream ships several EXTRA_CONTAINER_ENV option sets, commented, one per stack
# level; the LAST one is the production line measured in docs/tp4.md. Activate it
# and deactivate any other so exactly one is live.
def activate_last_extra_container_env(lines):
    idx = [i for i, l in enumerate(lines) if re.match(r"^#?\s*EXTRA_CONTAINER_ENV=", l)]
    if not idx:
        sys.exit("no EXTRA_CONTAINER_ENV line found in the example")
    live = idx[-1]
    for i in idx:
        lines[i] = re.sub(r"^#\s*", "", lines[i]) if i == live else re.sub(r"^(\s*)", r"#", lines[i])
    return lines, live


def main():
    with open(EXAMPLE) as fh:
        text = fh.read()
    lines = text.splitlines()

    # 1. replace or append each override (append if the example lacks the key)
    present = set()
    for i, line in enumerate(lines):
        m = re.match(r"^([A-Z_][A-Z0-9_]*)=", line)
        if m and m.group(1) in OVER:
            lines[i] = f"{m.group(1)}={OVER[m.group(1)]}"
            present.add(m.group(1))
    missing = [k for k in OVER if k not in present]
    if missing:
        lines.append("")
        lines.append("# ── fleet overrides added by spark-bench build-dsv41-tp4-env.py ──")
        lines.extend(f"{k}={OVER[k]}" for k in missing)

    # 2. activate the production EXTRA_CONTAINER_ENV
    lines, live = activate_last_extra_container_env(lines)

    out = "\n".join(lines).rstrip() + "\n"
    with open(OUT, "w") as fh:
        fh.write(out)

    # ── verification summary (a caller reads this, not the 400-line file) ──────
    active = {}
    for line in lines:
        m = re.match(r"^([A-Z_][A-Z0-9_]*)=(.*)$", line)
        if m:
            active[m.group(1)] = m.group(2)
    extra_live = [l for l in lines if re.match(r"^EXTRA_CONTAINER_ENV=", l)]

    checks = [
        ("HEAD_IP", "10.73.0.3"),
        ("WORKER_IPS", '"10.73.0.1 10.73.0.2 10.73.0.4"'),
        ("WORKER_HOSTS", '"spark@10.73.0.1 spark2@10.73.0.2 spark4@10.73.0.4"'),
        ("PORT", "8000"),
        ("TP_SIZE", "4"),
        ("EP_SIZE", "1"),
        ("IMAGE", "dsv41-4x-spark:canary-roce"),
        ("BUILD_DOCKERFILE", "Dockerfile.canary-roce"),
    ]
    bad = []
    print(f"wrote {OUT}  ({len(lines)} lines, example={os.path.basename(EXAMPLE)})")
    print(f"activated EXTRA_CONTAINER_ENV at example line {live + 1} "
          f"({len(extra_live)} live, must be 1)")
    if len(extra_live) != 1:
        bad.append(f"expected exactly 1 live EXTRA_CONTAINER_ENV, found {len(extra_live)}")
    for k, want in checks:
        got = active.get(k, "<missing>")
        flag = "OK  " if got == want else "FAIL"
        if got != want:
            bad.append(f"{k}={got} (want {want})")
        print(f"  {flag} {k}={got}")
    line = extra_live[0].split("=", 1)[1] if extra_live else ""
    for needle in ("DSV41_MOE_B12X_NEXT=1", "DSV41_MOE_B12X_NEXT_DETERMINISTIC=1",
                   "DSV41_FAST_LOAD=1", "DSV41_INDEXER_CHUNKED=1", "DSV41_ROCE_GATHER="):
        if needle.rstrip("=") not in line:
            bad.append(f"production EXTRA_CONTAINER_ENV lacks {needle}")
    print(f"  {'OK  ' if not bad else 'FAIL'} production line contains the EP1/b12x_next knobs")
    if bad:
        print("\nBUILD FAILED:")
        for b in bad:
            print(f"  - {b}")
        sys.exit(1)
    print("RESULT: PASS — .env.tp4 ready")


if __name__ == "__main__":
    main()