#!/usr/bin/env python3
"""Read-only snapshot of the CRS804 per-port QoS counters. usage: sw_snap.py <label>  (or: sw_snap.py diff <labelA> <labelB>)"""
import base64, json, os, subprocess, sys, urllib.request

D = os.path.expanduser("~/.hermes/profiles/spark/cache/scratch/sw_snaps")
os.makedirs(D, exist_ok=True)
PORTS = {"qsfp56-dd-1-1": "spark4", "qsfp56-dd-2-1": "spark2", "qsfp56-dd-3-1": "spark1", "qsfp56-dd-4-1": "spark3"}
KEYS = ("tx-packet", "tx-drop-packet", "tx-bytes", "tx-queue1-byte", "tx-queue3-byte", "tx-queue6-byte", "tx-drop-queue1-packet", "tx-drop-queue3-packet", "tx-pause", "rx-pause")


def snap():
    BW = "/Users/agent/.hermes/bin/vaultwarden-victor-bw"
    pw = [i for i in json.loads(subprocess.run([BW, "list", "items", "--raw"], capture_output=True, text=True).stdout) if "CRS804" in i.get("name", "")][0]["login"]["password"]
    r = urllib.request.Request("http://192.168.0.213/rest/interface/ethernet/switch/qos/port")
    r.add_header("Authorization", "Basic " + base64.b64encode(f"admin:{pw}".encode()).decode())
    return {PORTS[p["name"]]: {k: int(p.get(k, 0)) for k in KEYS} for p in json.load(urllib.request.urlopen(r, timeout=15)) if p.get("name") in PORTS}


if sys.argv[1] == "diff":
    a, b = (json.load(open(f"{D}/{x}.json")) for x in sys.argv[2:4])
    print(f"{'node':7} {'+pkts':>12} {'+dropped':>10} {'drop%':>6} {'+TC1 GB':>9} {'+TC3 GB':>9} {'+drop TC1':>10} {'+drop TC3':>10} {'+pause tx':>10} {'+pause rx':>10}")
    for n in sorted(a):
        d = {k: b[n][k] - a[n][k] for k in a[n]}
        pct = 100 * d["tx-drop-packet"] / max(1, d["tx-packet"] + d["tx-drop-packet"])
        print(f"{n:7} {d['tx-packet']:>12,} {d['tx-drop-packet']:>10,} {pct:>5.2f}% {d['tx-queue1-byte']/1e9:>9.2f} {d['tx-queue3-byte']/1e9:>9.2f} {d['tx-drop-queue1-packet']:>10,} {d['tx-drop-queue3-packet']:>10,} {d['tx-pause']:>10,} {d['rx-pause']:>10,}")
else:
    json.dump(snap(), open(f"{D}/{sys.argv[1]}.json", "w"))
    print("snapshot", sys.argv[1], "saved")
