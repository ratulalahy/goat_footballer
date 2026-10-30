#!/usr/bin/env python3
"""Polite fetcher for raw English-Wikipedia wikitext.

Uses the exact curl invocation agreed for this project:
    curl -A "FootballGreatestResearch/1.0 (data-journalism research)" \
         "https://en.wikipedia.org/wiki/<Title>?action=raw"

* Reuses /home/user/football-greatest/research/raw/<Title>.wikitext if it already
  exists (another agent writes there too) and looks like wikitext.
* Waits >= 2 s between requests; on HTTP 429 backs off 10 s, 30 s, 60 s (then
  keeps retrying every 60 s up to MAX_429_RETRIES).
* Writes atomically (tmp file + rename) so a concurrent reader never sees a
  partial file.
* Appends one JSON line per page to raw/../scripts/fetch_log.jsonl with the
  fetch time (UTC), HTTP status, byte size and whether the file was reused.

Usage:  python3 fetch_wikitext.py Title_1 Title_2 ...
"""
import json
import os
import subprocess
import sys
import time
import urllib.parse
from datetime import datetime, timezone

RAW_DIR = "/home/user/football-greatest/research/raw"
LOG = "/home/user/football-greatest/research/scripts/fetch_log.jsonl"
UA = "FootballGreatestResearch/1.0 (data-journalism research)"
MIN_GAP = 2.5
BACKOFF = [10, 30, 60]
MAX_429_RETRIES = 8

_last_request = 0.0


def candidate_paths(title):
    t = title.replace(" ", "_")
    variants = {t, t.replace("_", " "), urllib.parse.quote(t, safe=""), urllib.parse.quote(t, safe="_()'")}
    return [os.path.join(RAW_DIR, v + ".wikitext") for v in variants]


def looks_like_wikitext(path):
    try:
        with open(path, "r", encoding="utf-8") as fh:
            head = fh.read(400)
    except (OSError, UnicodeDecodeError):
        return False
    if not head.strip():
        return False
    low = head.lower()
    return not (low.startswith("<!doctype html") or "<html" in low[:200])


def log(entry):
    with open(LOG, "a", encoding="utf-8") as fh:
        fh.write(json.dumps(entry, ensure_ascii=False) + "\n")


def fetch(title):
    global _last_request
    title = title.replace(" ", "_")
    for p in candidate_paths(title):
        if os.path.exists(p) and looks_like_wikitext(p):
            mtime = datetime.fromtimestamp(os.path.getmtime(p), timezone.utc).isoformat(timespec="seconds")
            log({"title": title, "status": "reused", "path": p, "file_mtime_utc": mtime,
                 "bytes": os.path.getsize(p)})
            print(f"REUSED {title} -> {p}", flush=True)
            return p
    dest = os.path.join(RAW_DIR, title + ".wikitext")
    url = "https://en.wikipedia.org/wiki/" + urllib.parse.quote(title, safe="_()',!:-.") + "?action=raw"
    tries_429 = 0
    while True:
        wait = MIN_GAP - (time.time() - _last_request)
        if wait > 0:
            time.sleep(wait)
        tmp = dest + f".tmp.{os.getpid()}"
        _last_request = time.time()
        fetched_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
        hdr = tmp + ".hdr"
        res = subprocess.run(["curl", "-sS", "-A", UA, "-D", hdr, "-o", tmp, "-w", "%{http_code}", url],
                             capture_output=True, text=True)
        code = res.stdout.strip()
        last_modified = None
        try:
            with open(hdr, encoding="latin-1") as fh:
                for line in fh:
                    if line.lower().startswith("last-modified:"):
                        last_modified = line.split(":", 1)[1].strip()
            os.remove(hdr)
        except OSError:
            pass
        if code == "200" and looks_like_wikitext(tmp):
            # another agent may have written it meanwhile -> keep theirs
            if os.path.exists(dest) and looks_like_wikitext(dest):
                os.remove(tmp)
                print(f"RACE-REUSED {title}", flush=True)
                log({"title": title, "status": "reused-after-race", "path": dest})
                return dest
            os.replace(tmp, dest)
            size = os.path.getsize(dest)
            # same sidecar format as the other agent's <Title>.meta.json files
            meta = {"title": title, "url": url, "fetched_at": fetched_at.replace("+00:00", "Z"),
                    "http_status": 200, "last_modified": last_modified, "bytes": size}
            with open(os.path.join(RAW_DIR, title + ".meta.json"), "w", encoding="utf-8") as fh:
                json.dump(meta, fh, indent=1, ensure_ascii=False)
            log({"title": title, "status": 200, "url": url, "fetched_at_utc": fetched_at,
                 "path": dest, "bytes": size})
            print(f"FETCHED {title} ({size} bytes) at {fetched_at}", flush=True)
            return dest
        if os.path.exists(tmp):
            os.remove(tmp)
        if code == "429":
            # check whether the other agent saved it while we were throttled
            for p in candidate_paths(title):
                if os.path.exists(p) and looks_like_wikitext(p):
                    print(f"REUSED-DURING-BACKOFF {title}", flush=True)
                    log({"title": title, "status": "reused-during-backoff", "path": p})
                    return p
            delay = BACKOFF[min(tries_429, len(BACKOFF) - 1)]
            tries_429 += 1
            print(f"429 on {title}; backing off {delay}s (attempt {tries_429})", flush=True)
            if tries_429 > MAX_429_RETRIES:
                log({"title": title, "status": "gave-up-429", "url": url})
                return None
            time.sleep(delay)
            continue
        print(f"ERROR {title}: HTTP {code} {res.stderr.strip()}", flush=True)
        log({"title": title, "status": f"error-{code}", "url": url, "stderr": res.stderr.strip()})
        return None


if __name__ == "__main__":
    os.makedirs(RAW_DIR, exist_ok=True)
    for t in sys.argv[1:]:
        fetch(t)
    print("DONE", flush=True)
