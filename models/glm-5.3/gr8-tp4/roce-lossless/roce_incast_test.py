#!/usr/bin/env python3
"""2-to-1 RDMA incast on the Spark fabric with stock perftest, plus before/after snapshots of the CRS804 port counters.
usage: roce_incast_test.py <label> <tclass> [seconds]
Servers on spark2 (rail0, 10.73.0.2); clients on spark1 and spark4 at once. Lane must be DOWN. Read-only on the switch."""
import base64, json, os, re, subprocess, sys, time, urllib.request

label, tclass = sys.argv[1], int(sys.argv[2])
secs = int(sys.argv[3]) if len(sys.argv) > 3 else 12
SW = "192.168.0.213"
PORTS = {"qsfp56-dd-1-1": "spark4", "qsfp56-dd-2-1": "spark2", "qsfp56-dd-3-1": "spark1", "qsfp56-dd-4-1": "spark3"}
BW = "/Users/agent/.hermes/bin/vaultwarden-bw"
pw = [i for i in json.loads(subprocess.run([BW, "list", "items", "--raw"], capture_output=True, text=True).stdout) if "CRS804" in i.get("name", "")][0]["login"]["password"]


def sw_ports():
    r = urllib.request.Request(f"http://{SW}/rest/interface/ethernet/switch/qos/port")
    r.add_header("Authorization", "Basic " + base64.b64encode(f"admin:{pw}".encode()).decode())
    out = {}
    for p in json.load(urllib.request.urlopen(r, timeout=15)):
        if p.get("name") in PORTS:
            out[p["name"]] = {k: int(p.get(k, 0)) for k in ("tx-packet", "tx-drop-packet", "tx-queue1-byte", "tx-queue3-byte", "tx-queue6-byte", "tx-pause", "rx-pause")}
    return out


def nic(node):
    cmd = "for d in rocep1s0f1; do h=/sys/class/infiniband/$d/ports/1/hw_counters; for c in packet_seq_err local_ack_timeout_err np_cnp_sent rp_cnp_handled; do echo $c=$(cat $h/$c); done; done; ethtool -S enp1s0f1np1 | awk '/rx_discards_phy|rx_prio3_pause|tx_prio3_pause|rx_pause_ctrl_phy|tx_pause_ctrl_phy|rx_prio3_packets|tx_prio3_packets|rx_prio0_packets/{print $1\"\"$2}' | tr -d ':' | sed 's/\\([a-z_0-9]*\\)\\([0-9]*\\)$/\\1=\\2/'"
    r = subprocess.run(["ssh", "-o", "BatchMode=yes", node, cmd], capture_output=True, text=True, timeout=30)
    d = {}
    for line in r.stdout.split():
        if "=" in line:
            k, v = line.split("=", 1)
            if v.isdigit():
                d[k] = int(v)
    return d


nodes = ["spark1", "spark2", "spark4"]
sw0 = sw_ports()
n0 = {n: nic(n) for n in nodes}
common = f"-d rocep1s0f1 -x 3 -F -q 4 -s 1048576 -D {secs} --report_gbits --tclass={tclass}"
servers = [subprocess.Popen(["ssh", "-o", "BatchMode=yes", "spark2", f"timeout {secs + 25} ib_write_bw {common} -p {p}"], stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True) for p in (18515, 18516)]
time.sleep(3)
clients = [subprocess.Popen(["ssh", "-o", "BatchMode=yes", n, f"timeout {secs + 25} ib_write_bw {common} -p {p} 10.73.0.2"], stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True) for n, p in (("spark1", 18515), ("spark4", 18516))]
outs = [c.communicate(timeout=secs + 40)[0] for c in clients]
for s in servers:
    try:
        s.communicate(timeout=20)
    except Exception:
        s.kill()
sw1 = sw_ports()
n1 = {n: nic(n) for n in nodes}


def bw(o):
    m = re.search(r"\n\s*\d+\s+\d+\s+[\d.]+\s+([\d.]+)\s+[\d.]+", o)
    return float(m.group(1)) if m else None


res = {"label": label, "tclass": tclass, "seconds": secs, "client_Gbps_avg": [bw(o) for o in outs]}
res["client_total_Gbps"] = round(sum(x for x in res["client_Gbps_avg"] if x), 1)
res["switch_delta"] = {PORTS[p]: {k: sw1[p][k] - sw0[p][k] for k in sw1[p]} for p in sw1}
res["nic_delta"] = {n: {k: n1[n].get(k, 0) - n0[n].get(k, 0) for k in n1[n]} for n in nodes}
res["client_tail"] = [o.strip().splitlines()[-1][:120] if o.strip() else "" for o in outs]
os.makedirs(os.path.expanduser("~/.hermes/profiles/spark/cache/scratch/incast"), exist_ok=True)
json.dump(res, open(os.path.expanduser(f"~/.hermes/profiles/spark/cache/scratch/incast/{label}.json"), "w"), indent=1)
print(f"== {label}  tclass={tclass}  clients Gb/s={res['client_Gbps_avg']}  total={res['client_total_Gbps']}")
for h, d in res["switch_delta"].items():
    drop_pct = 100 * d["tx-drop-packet"] / max(1, d["tx-packet"] + d["tx-drop-packet"])
    print(f"   switch->{h:7} pkts +{d['tx-packet']:>10,}  dropped +{d['tx-drop-packet']:>8,} ({drop_pct:5.2f}%)  TC1 +{d['tx-queue1-byte']/1e9:6.2f} GB  TC3 +{d['tx-queue3-byte']/1e9:6.2f} GB  pause rx/tx +{d['rx-pause']}/+{d['tx-pause']}")
for n, d in res["nic_delta"].items():
    print(f"   nic {n}: " + ", ".join(f"{k}+{v}" for k, v in d.items() if v))
