#!/usr/bin/env python3
"""Parallel range-request downloader for starved-WAN conditions.

Use when the bulk path is in a starvation regime: sustained single flows land
0 bytes while small flows (SSH/API) stay fine. Confirm with a control probe
from a second host BEFORE using this — if other hosts pull fine, the problem
is the node/path, not the regime.

How it works: fetches every manifest entry as 2MiB HTTP range chunks across N
threads, retries each chunk independently with backoff, assembles chunks into
a temp file, sha256-verifies against the manifest (when present), and only
then renames into place. Existing complete+verified files are skipped, so it
resumes cleanly over already-banked shards.

Manifest format (JSON list):
  [{"name": "model-00001-of-00021.safetensors", "size": 3022795064,
    "sha256": "<LFS oid, or null for small files>"}, ...]

Build the manifest from the tree API of the RECIPE-PINNED REVISION — it carries LFS
oids AND honors the pin (paths-info is main-only). The tree endpoint paginates at
50 entries; follow the Link header cursor or you silently manifest half the repo.
VERIFY the manifest (file count, total GB) against the model card before shipping it:

  python3 - <<'EOF'
  import json, urllib.request
  repo, rev = "<REPO>", "<pin sha>"
  def tree_all(r):
      items, cursor = [], None
      while True:
          url = f"https://huggingface.co/api/models/{repo}/tree/{r}?recursive=true&expand=true" + (f"&cursor={cursor}" if cursor else "")
          resp = urllib.request.urlopen(url, timeout=60)
          items += json.loads(resp.read())
          link = resp.headers.get("Link", ""); cursor = None
          if 'rel="next"' in link:
              cursor = link.split("cursor=")[1].split("&")[0].split(">")[0]
          if not cursor: break
      return items
  entries = [{"name": t["path"], "size": t.get("size", 0), "sha256": (t.get("lfs") or {}).get("oid")}
             for t in tree_all(rev) if t.get("type") != "directory"]
  print(f"files: {len(entries)}, total: {sum(e['size'] for e in entries)/1e9:.1f} GB")
  json.dump(entries, open("manifest.json", "w"), indent=1)
  EOF

Usage:
  chunkdl.py --repo org/model --dest /path/to/model --manifest manifest.json \
             [--workers 64] [--chunk-mib 2] [--revision <pin>]
"""
import argparse, hashlib, json, os, random, sys, time, urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed

args = None


def log(msg):
    line = f"{time.strftime('%H:%M:%S')} {msg}"
    print(line, flush=True)
    with open(os.path.join(os.path.dirname(os.path.abspath(args.manifest)), "chunkdl.log"), "a") as f:
        f.write(line + "\n")


def fetch_range(url, start, end, attempt_timeout=75):
    req = urllib.request.Request(url, headers={
        "Range": f"bytes={start}-{end}",
        "Accept": "application/octet-stream",
        "User-Agent": "chunkdl/1.0",
    })
    with urllib.request.urlopen(req, timeout=attempt_timeout) as r:
        return r.read()


def download_chunk(url, start, end, path, max_retry):
    expect = end - start + 1
    for attempt in range(max_retry):
        try:
            data = fetch_range(url, start, end)
            if len(data) == expect:
                with open(path, "wb") as f:
                    f.write(data)
                return True
        except Exception:
            pass
        time.sleep(min(60, 2 ** attempt) + random.random() * 2)
    return False


def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(8 * 1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def process_file(entry, dest, chunk, workers, max_retry, rounds, revision="main"):
    name, size, sha = entry["name"], entry["size"], entry.get("sha256")
    final = os.path.join(dest, name)
    url = f"https://huggingface.co/{args.repo}/resolve/{revision}/{name}"
    tmpdir = os.path.join(dest, ".chunktmp", name + ".d")
    os.makedirs(tmpdir, exist_ok=True)
    # manifest entries may live in subdirectories (assets/, tokenizer/, ...) — create them
    # up front or the final assemble step dies with FileNotFoundError on the first subdir file
    os.makedirs(os.path.dirname(final) or ".", exist_ok=True)

    if os.path.exists(final) and os.path.getsize(final) == size:
        if sha:
            if sha256_file(final) == sha:
                return f"verified   {name}"
            log(f"SHA MISMATCH on existing {name} — redownloading")
            os.remove(final)
        else:
            return f"exists     {name} (size match, no sha)"

    nchunks = (size + chunk - 1) // chunk
    t0 = time.time()
    for _ in range(rounds):
        missing = [(i, i * chunk, min(size, (i + 1) * chunk) - 1)
                   for i in range(nchunks)
                   if not (os.path.exists(os.path.join(tmpdir, f"c{i:06d}"))
                           and os.path.getsize(os.path.join(tmpdir, f"c{i:06d}")) ==
                           min(size, (i + 1) * chunk) - i * chunk)]
        if not missing:
            break
        log(f"{name}: {len(missing)}/{nchunks} chunks to fetch")
        with ThreadPoolExecutor(max_workers=workers) as ex:
            futs = {ex.submit(download_chunk, url, s, e,
                              os.path.join(tmpdir, f"c{i:06d}"), max_retry): i
                    for i, s, e in missing}
            for fut in as_completed(futs):
                fut.result()

    still_missing = [i for i in range(nchunks)
                     if not os.path.exists(os.path.join(tmpdir, f"c{i:06d}"))
                     or os.path.getsize(os.path.join(tmpdir, f"c{i:06d}")) == 0]
    if still_missing:
        return f"FAILED     {name} ({len(still_missing)} chunks missing after {rounds} rounds)"

    tmpfinal = final + ".assembling"
    with open(tmpfinal, "wb") as out:
        for i in range(nchunks):
            with open(os.path.join(tmpdir, f"c{i:06d}"), "rb") as cf:
                while True:
                    block = cf.read(8 * 1024 * 1024)
                    if not block:
                        break
                    out.write(block)
    if os.path.getsize(tmpfinal) != size:
        os.remove(tmpfinal)
        return f"FAILED     {name} (assembled size mismatch)"
    if sha and sha256_file(tmpfinal) != sha:
        os.remove(tmpfinal)
        return f"FAILED     {name} (sha256 mismatch after download)"
    os.rename(tmpfinal, final)
    for i in range(nchunks):
        try:
            os.remove(os.path.join(tmpdir, f"c{i:06d}"))
        except OSError:
            pass
    try:
        os.rmdir(tmpdir)
    except OSError:
        pass
    dt = time.time() - t0
    return f"downloaded {name} ({size / 1024 ** 3:.2f} GiB in {dt:.0f}s, {size / dt / 1024 / 1024:.1f} MB/s)"


def main():
    global args
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo", required=True, help="HF repo id, e.g. org/model")
    ap.add_argument("--dest", required=True, help="local model directory")
    ap.add_argument("--manifest", required=True, help="manifest JSON (see docstring)")
    ap.add_argument("--workers", type=int, default=64)
    ap.add_argument("--chunk-mib", type=int, default=2)
    ap.add_argument("--rounds", type=int, default=4, help="full chunk-collection passes per file")
    ap.add_argument("--max-chunk-retry", type=int, default=8)
    ap.add_argument("--revision", default="main",
                    help="HF revision to fetch from; set to the recipe's pinned commit when the "
                         "manifest was built from a pinned tree so URL and hashes agree")
    args = ap.parse_args()

    entries = json.load(open(args.manifest))
    os.makedirs(args.dest, exist_ok=True)
    for entry in entries:
        parent = os.path.dirname(os.path.join(args.dest, entry["name"]))
        if parent:
            os.makedirs(parent, exist_ok=True)
    # stale .incomplete blobs would fool any downstream completeness gate
    import glob
    for junk in glob.glob(os.path.join(args.dest, ".cache", "huggingface", "download", "*.incomplete")):
        try:
            os.remove(junk)
        except OSError:
            pass
    log(f"=== chunkdl start: {len(entries)} files, {sum(e['size'] for e in entries) / 1024 ** 3:.1f} GiB ===")
    failures = []
    for entry in entries:
        result = process_file(entry, args.dest, args.chunk_mib * 1024 * 1024,
                              args.workers, args.max_chunk_retry, args.rounds, args.revision)
        log(result)
        if result.startswith("FAILED"):
            failures.append(entry["name"])
    if failures:
        log(f"=== chunkdl DONE WITH FAILURES: {failures} ===")
        sys.exit(1)
    log("=== chunkdl ALL FILES VERIFIED OK ===")


if __name__ == "__main__":
    main()
