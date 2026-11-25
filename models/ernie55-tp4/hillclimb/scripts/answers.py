"""Correctness spot-check of the greedy equivalence captures: arithmetic, planets, French, finish reasons."""
import glob, json

for f in sorted(glob.glob("logs/*.equiv.json")):
    d = json.load(open(f))
    n = f.split("/")[-1].replace(".equiv.json", "")
    a2, a3, a4 = (d[i]["content"].replace("\n", " ") for i in (2, 3, 4))
    ok3 = "7,006,652" in a3 or "7006652" in a3 or "7 006 652" in a3
    planets = all(p in a2 for p in ("Mercury", "Venus", "Earth", "Mars", "Jupiter", "Saturn", "Uranus", "Neptune"))
    print("%-16s arithmetic_ok=%-5s planets_ok=%-5s finish=%s" % (n, ok3, planets, [x["finish"] for x in d]))
    print("%-16s french: %r" % ("", a4[:110]))
