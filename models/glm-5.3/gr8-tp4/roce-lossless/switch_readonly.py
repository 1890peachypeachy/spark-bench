#!/usr/bin/env python3
"""READ-ONLY audit of the CRS804 over its REST API. Only HTTP GET is ever issued; the password never leaves this
process and is redacted from anything printed. Output: a compact summary + raw JSON saved for the record."""
import base64, json, os, subprocess, sys, urllib.request, urllib.error

HOST = sys.argv[1] if len(sys.argv) > 1 else "192.168.0.213"
BW = "/Users/agent/.hermes/bin/vaultwarden-bw"
OUT = os.path.expanduser("~/.hermes/profiles/spark/cache/scratch/switch_audit")
os.makedirs(OUT, exist_ok=True)

items = json.loads(subprocess.run([BW, "list", "items", "--raw"], capture_output=True, text=True).stdout)
cands = [i for i in items if "CRS804" in i.get("name", "")]
PW = None
user = "admin"
USED = None
for it in cands:
    PW = (it.get("login") or {}).get("password")
    user = (it.get("login") or {}).get("username") or "admin"
    USED = it["name"]
    if PW:
        break


def redact(s):
    return s.replace(PW, "***") if PW and isinstance(s, str) else s


def get(path):
    req = urllib.request.Request(f"http://{HOST}/rest/{path}")
    req.add_header("Authorization", "Basic " + base64.b64encode(f"{user}:{PW}".encode()).decode())
    try:
        with urllib.request.urlopen(req, timeout=15) as r:  # GET only
            return json.load(r)
    except urllib.error.HTTPError as e:
        return {"_error": f"HTTP {e.code}", "_body": redact(e.read()[:200].decode("utf-8", "replace"))}
    except Exception as e:
        return {"_error": redact(str(e))[:160]}


PATHS = {
    "resource": "system/resource",
    "identity": "system/identity",
    "qos_settings": "interface/ethernet/switch/qos/settings",
    "qos_profile": "interface/ethernet/switch/qos/profile",
    "qos_map_ip": "interface/ethernet/switch/qos/map/ip",
    "qos_tx_queue": "interface/ethernet/switch/qos/tx-manager/queue",
    "qos_pfc": "interface/ethernet/switch/qos/priority-flow-control",
    "qos_port": "interface/ethernet/switch/qos/port",
    "switch": "interface/ethernet/switch",
    "ethernet": "interface/ethernet",
    "lldp": "ip/neighbor/discovery-settings",
    "health": "system/health",
}
res = {k: get(p) for k, p in PATHS.items()}
json.dump(res, open(f"{OUT}/crs804_readonly.json", "w"), indent=1)
print("credential item used:", USED, "| user:", user, "| password present:", bool(PW))
for k, v in res.items():
    if isinstance(v, dict) and "_error" in v:
        print(f"{k:14} ERROR {v['_error']} {v.get('_body', '')}")
    else:
        print(f"{k:14} ok ({len(v) if isinstance(v, list) else 'obj'})")
