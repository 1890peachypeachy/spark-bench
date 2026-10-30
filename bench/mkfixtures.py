#!/usr/bin/env python3
"""Build the FROZEN inputs for bench/qbench.py.

Everything here is deterministic (explicit seeds, stdlib only) so the same files come out on any
machine, and the built files are committed next to this script. A comparison with a changed input is
not a comparison, so never edit a built input in place: edit this generator, rebuild, and say so.

    python3 bench/mkfixtures.py [--out bench/inputs]

Inputs produced (all committed):
  math.jsonl      reasoning/math: GSM8K test split, first 30 items (fetched once; see SOURCES.md)
  if.jsonl        instruction following: 20 items, each with a programmatic checker
  json_tasks.json structured output: 6 JSON-Schema tasks (validated client-side)
  tool_tasks.json tool use: 8 single-call cases + 2 dependent multi-step chains
  coding.json     coding: 5 tasks + hidden stdlib-unittest tests (run locally, never shown to the model)
  longctx.json    long context: needle positions/sizes for the passkey suite
  summary.json    summarization: a synthetic transcript + planted / superseded / must-not-invent facts
  mmlu200.jsonl   knowledge: MMLU-200, copied from deepseek-v41-tensorfold-spark (see SOURCES.md)

GSM8K and MMLU-200 are public benchmark slices; the synthetic fixtures are generated here.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import random
from pathlib import Path

WORDS = ("river mountain lantern copper harbor meadow quartz signal orchard canvas thunder velvet "
         "compass ember glacier timber falcon prairie marble beacon willow cobalt summit ferry saddle "
         "tundra pepper violet anchor bramble cinder delta fjord granite hollow ivory jasmine kettle "
         "lagoon mosaic nectar oyster quiver ribbon saffron thistle umber vertex walnut yarrow zephyr").split()
TOPICS = ("orchard", "harbor", "lantern", "quarry", "sable", "kestrel", "marmot", "pylon", "quill", "vellum")


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


# ---------------------------------------------------------------- reasoning / math (GSM8K slice)

def fetch_gsm8k(n: int) -> list[dict]:
    """One fixed slice of the public GSM8K test split. Needs network at BUILD time only."""
    import urllib.request
    url = ("https://datasets-server.huggingface.co/rows?dataset=openai%2Fgsm8k&config=main"
           f"&split=test&offset=0&length={n}")
    with urllib.request.urlopen(url, timeout=90) as r:
        rows = json.loads(r.read())["rows"]
    out = []
    for i, r in enumerate(rows[:n]):
        row = r["row"]
        gold = row["answer"]
        final = gold.split("####")[-1].strip().replace(",", "").replace("$", "")
        out.append({"id": f"gsm8k-test-{i}", "question": row["question"], "answer": final})
    return out


# ---------------------------------------------------------------- instruction following

IF_TASKS = [
    ("if-01", "List exactly three colours, one per line, each line starting with '- ' and nothing else.",
     {"kind": "lines", "prefix": "- ", "n": 3}),
    ("if-02", "Reply with the single word: pinecone", {"kind": "exact_ci", "value": "pinecone"}),
    ("if-03", "Write one sentence of at most 12 words about a kettle.", {"kind": "max_words", "n": 12}),
    ("if-04", "Output a JSON object with exactly the keys a and b, a is the string \"x\", b is the number 2. No other text.",
     {"kind": "json_keys", "keys": ["a", "b"]}),
    ("if-05", "Answer with a number only: how many sides does a hexagon have?", {"kind": "int_only", "value": 6}),
    ("if-06", "Write a haiku about rain. Exactly three lines, no title.", {"kind": "lines", "n": 3}),
    ("if-07", "Explain gravity in exactly two sentences.", {"kind": "sentences", "n": 2}),
    ("if-08", "Do not use the letter 'e' anywhere in your reply. Describe a boat.",
     {"kind": "absent_char", "char": "e", "min_words": 5}),
    ("if-09", "Convert 'the quick brown fox' to uppercase and reply with only that.",
     {"kind": "exact", "value": "THE QUICK BROWN FOX"}),
    ("if-10", "Give three bullet points about tea, each starting with '* ', then a final line 'END'.",
     {"kind": "lines_prefix_end", "prefix": "* ", "n": 3, "end": "END"}),
    ("if-11", "Reply with the numbers 1 to 5 separated by commas, no spaces.", {"kind": "exact", "value": "1,2,3,4,5"}),
    ("if-12", "Answer yes or no only: is 91 prime?", {"kind": "one_of", "values": ["no"], "prefix_ok": ["no"]}),
    ("if-13", "Name two planets, comma separated, lowercase, nothing else.",
     {"kind": "comma_n", "n": 2, "lower": True}),
    ("if-14", "Write the word 'echo' exactly four times separated by single spaces.",
     {"kind": "exact_ci", "value": "echo echo echo echo"}),
    ("if-15", "Summarise the water cycle in at most 25 words.", {"kind": "max_words", "n": 25}),
    ("if-16", "Reply with a markdown table with exactly 2 columns and a header row plus one data row.",
     {"kind": "lines_matching", "pattern": r"^\|.*\|.*\|$", "n": 2}),
    ("if-17", "Output only the CSV header: name,age,city", {"kind": "exact", "value": "name,age,city"}),
    ("if-18", "Write a sentence that contains the word 'cobalt' and does not contain the word 'blue'.",
     {"kind": "substring", "must": ["cobalt"], "must_not": ["blue"]}),
    ("if-19", "Reply with exactly five words, all lowercase, about snow.",
     {"kind": "words_n_lower", "n": 5}),
    ("if-20", "Start your reply with 'A:' and then state the capital of Peru. Nothing else.",
     {"kind": "startswith", "prefix": "A:", "contains": "lima"}),
]


# ---------------------------------------------------------------- structured output

JSON_TASKS = [
    ("person", "Give one person as JSON: name (string), age (integer), active (boolean).",
     {"type": "object", "properties": {"name": {"type": "string"}, "age": {"type": "integer"},
                                       "active": {"type": "boolean"}},
      "required": ["name", "age", "active"], "additionalProperties": False}),
    ("order", "Give an order as JSON: id (string), items (array of objects with sku string and qty integer), "
              "total (number). Two items.",
     {"type": "object", "properties": {"id": {"type": "string"},
                                       "items": {"type": "array", "items": {"type": "object",
                                                                             "properties": {"sku": {"type": "string"},
                                                                                            "qty": {"type": "integer"}},
                                                                             "required": ["sku", "qty"],
                                                                             "additionalProperties": False}},
                                       "total": {"type": "number"}},
      "required": ["id", "items", "total"], "additionalProperties": False}),
    ("status", "Give a status object as JSON: state one of \"ok\", \"degraded\", \"down\"; code integer 0-99.",
     {"type": "object", "properties": {"state": {"type": "string", "enum": ["ok", "degraded", "down"]},
                                       "code": {"type": "integer", "minimum": 0, "maximum": 99}},
      "required": ["state", "code"], "additionalProperties": False}),
    ("city", "Give a city as JSON: name (string), population (integer > 0), tags (array of strings), "
             "coords with lat and lon numbers.",
     {"type": "object", "properties": {"name": {"type": "string"}, "population": {"type": "integer"},
                                       "tags": {"type": "array", "items": {"type": "string"}},
                                       "coords": {"type": "object", "properties": {"lat": {"type": "number"},
                                                                                    "lon": {"type": "number"}},
                                                  "required": ["lat", "lon"], "additionalProperties": False}},
      "required": ["name", "population", "tags", "coords"], "additionalProperties": False}),
    ("flags", "Give three feature flags as JSON: object whose values are booleans.",
     {"type": "object", "additionalProperties": {"type": "boolean"}}),
    ("list", "Give a JSON array of exactly three strings, each a colour name.",
     {"type": "array", "items": {"type": "string"}, "minItems": 3, "maxItems": 3}),
]

JSON_FUNCS = {
    "person": "make_person",
    "order": "make_order",
    "status": "make_status",
    "city": "make_city",
    "flags": "make_flags",
    "list": "make_colours",
}


# ---------------------------------------------------------------- tool use

TOOLS = [
    {"type": "function", "function": {"name": "get_weather", "description": "Get current weather for a city",
     "parameters": {"type": "object", "properties": {"city": {"type": "string"},
                                                     "units": {"type": "string", "enum": ["c", "f"]}},
                    "required": ["city"]}}},
    {"type": "function", "function": {"name": "create_task", "description": "Create a task in the tracker",
     "parameters": {"type": "object", "properties": {"title": {"type": "string"},
                                                     "priority": {"type": "integer", "minimum": 1, "maximum": 5},
                                                     "tags": {"type": "array", "items": {"type": "string"}},
                                                     "due": {"type": "string"}},
                    "required": ["title", "priority"]}}},
    {"type": "function", "function": {"name": "run_sql", "description": "Run a read-only SQL query",
     "parameters": {"type": "object", "properties": {"query": {"type": "string"}, "limit": {"type": "integer"}},
                    "required": ["query"]}}},
    {"type": "function", "function": {"name": "convert_currency", "description": "Convert an amount between currencies",
     "parameters": {"type": "object", "properties": {"amount": {"type": "number"}, "from": {"type": "string"},
                                                     "to": {"type": "string"}},
                    "required": ["amount", "from", "to"]}}},
]

TOOL_CASES = [
    ("tool-01", "What's the weather in Sapporo right now? Use celsius.", {"tool": "get_weather", "required": ["city"], "const": {"units": "c"}}),
    ("tool-02", "Create a task titled 'pin blender mcp source' with priority 2, tags ops and security, due 2026-09-25.",
     {"tool": "create_task", "required": ["title", "priority"]}),
    ("tool-03", "Query the messages table for the 5 most recent rows (id, created_at), newest first.",
     {"tool": "run_sql", "required": ["query"]}),
    ("tool-04", "Convert 250 EUR to JPY.", {"tool": "convert_currency", "required": ["amount", "from", "to"]}),
    ("tool-05", "Explain in about 80 words why speculative decoding helps single-stream latency. Do not call any tool.",
     {"no_tool": True}),
    ("tool-06", "Create a task titled exactly: He said \"don't\" then left, priority 5, tags [\"a\\\"b\", \"日本語\"].",
     {"tool": "create_task", "required": ["title", "priority"], "const": {"priority": 5}}),
    ("tool-07", "Write a short paragraph (about 60 words) about a stone room under a koi pond. No tools.",
     {"no_tool": True}),
    ("tool-08", "What's the weather in Reykjavik in fahrenheit?", {"tool": "get_weather", "required": ["city"], "const": {"units": "f"}}),
]

# Dependent multi-step chains: a result of one call is needed for the next.
CHAIN_SIMS = {
    "get_weather": lambda a: f"{a.get('city', '?')}: 4 degrees, sleet, wind 20 km/h",
    "create_task": lambda a: f"created task {a.get('title', '?')} priority {a.get('priority', '?')}",
    "run_sql": lambda a: "id|created_at\n9012|2026-09-24\n9007|2026-09-23\n9001|2026-09-22\n8990|2026-09-21\n8984|2026-09-20",
    "convert_currency": lambda a: f"{a.get('amount', '?')} {a.get('from', '?')} = 41800 {a.get('to', '?')}",
}

CHAINS = [
    ("chain-01",
     [{"prompt": "What's the weather in Sapporo right now? Use celsius.",
       "expect": {"tool": "get_weather", "required": ["city"], "const": {"units": "c"}}},
      # second turn needs the temperature from the tool result
      {"prompt": "Add a task titled 'sleet watch' with priority equal to the temperature you just read (rounded up to an integer, minimum 1).",
       "expect": {"tool": "create_task", "required": ["title", "priority"], "const": {"priority": 4}}}],
     {"arg": "title", "value": "sleet watch"}),
    ("chain-02",
     [{"prompt": "Query the messages table for the 5 most recent rows (id, created_at), newest first.",
       "expect": {"tool": "run_sql", "required": ["query"]}},
      {"prompt": "Convert the number of rows you just got, times 100, from EUR to JPY.",
       "expect": {"tool": "convert_currency", "required": ["amount", "from", "to"], "const": {"amount": 500, "from": "EUR", "to": "JPY"}}}],
     {"arg": "amount", "value": 500}),
]


# ---------------------------------------------------------------- coding (hidden unittest)

CODING_TASKS = [
    {
        "id": "code-01", "module": "solution", "entry": "roman_to_int",
        "prompt": ("Write a Python module `solution.py` with a function `roman_to_int(s: str) -> int` that converts "
                   "a valid uppercase Roman numeral (I,V,X,L,C,D,M; subtractive forms allowed) to an integer. "
                   "No other output. Reply with the complete file content in one ```python code block."),
        "test": """
import unittest
from solution import roman_to_int
class T(unittest.TestCase):
    def test_basic(self):
        for s, n in [("I",1),("IV",4),("IX",9),("LVIII",58),("MCMXCIV",1994),("MMXXVI",2026),("XL",40),("CDXLIV",444)]:
            self.assertEqual(roman_to_int(s), n, s)
if __name__ == "__main__": unittest.main()
""",
    },
    {
        "id": "code-02", "module": "solution", "entry": "flatten",
        "prompt": ("Write a Python module `solution.py` with `flatten(x)` that takes an arbitrarily nested list "
                   "(ints and lists) and returns a flat list of ints in order. Non-list scalars pass through. "
                   "Reply with the complete file content in one ```python code block."),
        "test": """
import unittest
from solution import flatten
class T(unittest.TestCase):
    def test_nested(self):
        self.assertEqual(flatten([1,[2,[3,[4]],5]]), [1,2,3,4,5])
        self.assertEqual(flatten([]), [])
        self.assertEqual(flatten([[],[1],[[2]]]), [1])
        self.assertEqual(flatten(7), [7])
if __name__ == "__main__": unittest.main()
""",
    },
    {
        "id": "code-03", "module": "solution", "entry": "merge_intervals",
        "prompt": ("Write a Python module `solution.py` with `merge_intervals(intervals)` that merges overlapping "
                   "closed intervals given as a list of (start, end) tuples and returns a sorted list of tuples. "
                   "Touching intervals (1,2) and (2,3) merge. Reply with the complete file content in one "
                   "```python code block."),
        "test": """
import unittest
from solution import merge_intervals
class T(unittest.TestCase):
    def test_merge(self):
        self.assertEqual(merge_intervals([(1,3),(2,6),(8,10),(15,18)]), [(1,6),(8,10),(15,18)])
        self.assertEqual(merge_intervals([(1,2),(2,3)]), [(1,3)])
        self.assertEqual(merge_intervals([]), [])
        self.assertEqual(merge_intervals([(5,6),(1,2)]), [(1,2),(5,6)])
if __name__ == "__main__": unittest.main()
""",
    },
    {
        "id": "code-04", "module": "solution", "entry": "parse_kv",
        "prompt": ("Write a Python module `solution.py` with `parse_kv(text)` that parses lines of the form "
                   "`key=value` into a dict, strips whitespace around key and value, ignores blank lines and lines "
                   "starting with '#', and keeps the LAST value for a repeated key. Reply with the complete file "
                   "content in one ```python code block."),
        "test": """
import unittest
from solution import parse_kv
class T(unittest.TestCase):
    def test_parse(self):
        self.assertEqual(parse_kv("a=1\\nb = 2 \\n# c=3\\n\\nd=a\\n"), {"a":"1","b":"2","d":"a"})
        self.assertEqual(parse_kv("x=1\\nx=2"), {"x":"2"})
        self.assertEqual(parse_kv(""), {})
if __name__ == "__main__": unittest.main()
""",
    },
    {
        "id": "code-05", "module": "solution", "entry": "top_k",
        "prompt": ("Write a Python module `solution.py` with `top_k(items, k)` returning the k highest integers "
                   "from a list, in descending order, as a list; k<=0 returns [] and k larger than the list returns "
                   "everything sorted. Reply with the complete file content in one ```python code block."),
        "test": """
import unittest
from solution import top_k
class T(unittest.TestCase):
    def test_topk(self):
        self.assertEqual(top_k([5,1,9,3,7], 2), [9,7])
        self.assertEqual(top_k([5,1], 0), [])
        self.assertEqual(top_k([2,2,1], 5), [2,2,1])
        self.assertEqual(top_k([], 3), [])
if __name__ == "__main__": unittest.main()
""",
    },
]


# ---------------------------------------------------------------- summarization fixture

def build_summary(rng: random.Random, n_facts: int = 20, n_stale: int = 5) -> dict:
    """A synthetic project log with planted facts, superseded facts and one buried detail."""
    facts, stale = [], []
    for i in range(n_facts):
        topic = TOPICS[i % len(TOPICS)]
        key = f"SYNTH_{topic.upper()}_{i:02d}"
        val = f"{rng.randint(1000, 9999)}-{rng.choice(WORDS)}"
        facts.append({"key": key, "value": val})
        if i < n_stale:  # superseded later in the transcript
            old = f"{rng.randint(1000, 9999)}-{rng.choice(WORDS)}"
            stale.append({"key": key, "old": old, "value": val})
    blocks = []
    for para in range(120):
        lines = []
        for _ in range(4):
            lines.append(" ".join(rng.choice(WORDS) for _ in range(rng.randint(6, 14))) + ".")
        blocks.append(" ".join(lines))
    # place facts evenly, superseded versions early and current versions late
    step = max(1, len(blocks) // n_facts)
    for i, f in enumerate(facts):
        pos = min(len(blocks) - 1, i * step)
        line = f"Log entry: {f['key']} = {f['value']}"
        if i < n_stale:
            old = next(s["old"] for s in stale if s["key"] == f["key"])
            blocks[pos] = blocks[pos] + f"\nLog entry: {f['key']} = {old}\n" + line
        else:
            blocks[pos] = blocks[pos] + "\n" + line
    blocks.append("Note from ops: the standby generator is the one painted green, by the west gate.")
    transcript = "\n\n".join(f"[{i:03d}] {b}" for i, b in enumerate(blocks))
    return {"transcript": transcript, "facts": facts, "stale": stale,
            "extra_fact": {"key": "generator", "value": "the one painted green, by the west gate"},
            "prompt": ("You are compacting a long project log. Write a compact summary (at most 350 words) for a "
                       "reader who will never see the original. Preserve every `SYNTH_*` setting with its CURRENT "
                       "exact value. Do not invent numbers, names or dates that are not in the log.")}


# ---------------------------------------------------------------- long context (passkey)

def build_longctx(rng: random.Random, sizes: list[int]) -> dict:
    """Deterministic filler + a passkey at a fixed depth fraction for each size (tokens sized at run time)."""
    items = []
    for size in sizes:
        key = f"{rng.randint(100000, 999999)}"
        items.append({"size": size, "depth": 1 / 3, "passkey": key,
                      "seed": rng.randint(1, 10 ** 6)})
    return {"items": items,
            "question": "What is the passkey? Reply with the passkey only."}


# ---------------------------------------------------------------- main

def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="bench/inputs")
    ap.add_argument("--mmlu-src",
                    default="~/git/deepseek-v41-tensorfold-spark/bench/data/mmlu200.jsonl")
    a = ap.parse_args()
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    rng = random.Random(20261015)

    def dump(name: str, obj) -> None:
        p = out / name
        if name.endswith(".jsonl"):
            p.write_text("".join(json.dumps(o, ensure_ascii=False) + "\n" for o in obj))
        else:
            p.write_text(json.dumps(obj, ensure_ascii=False, indent=1) + "\n")
        print(f"{name:20} {p.stat().st_size:>8} B  sha256 {sha(p)[:16]}")

    math_items = fetch_gsm8k(30)
    dump("math.jsonl", math_items)
    dump("if.jsonl", [{"id": i, "prompt": p, "check": c} for i, p, c in IF_TASKS])
    dump("json_tasks.json", {"tasks": [{"name": n, "prompt": p, "schema": s} for n, p, s in JSON_TASKS],
                             "func_names": JSON_FUNCS})
    dump("tool_tasks.json", {"tools": TOOLS,
                             "cases": [{"id": i, "prompt": p, "expect": e} for i, p, e in TOOL_CASES],
                             "chains": [{"id": i, "turns": t, "final_check": f} for i, t, f in CHAINS]})
    dump("coding.json", {"tasks": CODING_TASKS})
    dump("summary.json", build_summary(rng))
    dump("longctx.json", build_longctx(rng, [32768, 131072, 299000]))
    src = Path(a.mmlu_src)
    if src.exists():
        (out / "mmlu200.jsonl").write_bytes(src.read_bytes())
        print(f"{'mmlu200.jsonl':20} {src.stat().st_size:>8} B  sha256 {sha(out / 'mmlu200.jsonl')[:16]}  (copied)")
    else:
        print(f"mmlu200.jsonl: source missing at {src} — copy it by hand (see SOURCES.md)")


if __name__ == "__main__":
    main()
