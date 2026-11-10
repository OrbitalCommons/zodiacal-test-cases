#!/usr/bin/env python3
"""Re-run source extraction for the hubble-f606w test cases.

For every `<case>.json` in the input set this downloads the archived
drizzled FITS straight from MAST (`hst.image_url`), runs `zodiacal extract`
with the same parameters the original set used, and writes a new case JSON
that keeps every original field except `sources`/`image_width`/
`image_height`, plus an `extraction` provenance block. The FITS is deleted
as soon as the case is written, so disk use stays at roughly
`--workers` × one file.

Resumable: cases whose output JSON already exists are skipped, so re-running
the same command only retries what is missing. Permanent failures are
appended to `<out>/_failures.jsonl` and retried on the next run.

Example:
    scripts/reextract_hst.py --zodiacal ~/scratch/hst-reextract/zodiacal-a006186 \
        --out ~/scratch/hst-reextract/hubble-f606w --tmp ~/scratch/hst-reextract/tmp
"""

import argparse
import concurrent.futures as cf
import datetime as dt
import hashlib
import json
import os
import random
import shutil
import subprocess
import sys
import threading
import time
from pathlib import Path

import requests

RETRY_WAITS = [5, 30, 120, 600]  # seconds between attempts on transient errors
CHUNK = 4 << 20


class Permanent(Exception):
    """An error retrying will not fix (404, not a FITS file, extractor crash)."""


def download(url: str, dest: Path, session: requests.Session) -> int:
    part = dest.with_suffix(dest.suffix + ".part")
    with session.get(url, stream=True, timeout=(30, 300)) as r:
        if r.status_code in (403, 404, 410):
            raise Permanent(f"HTTP {r.status_code}")
        r.raise_for_status()
        n = 0
        with open(part, "wb") as f:
            for chunk in r.iter_content(CHUNK):
                f.write(chunk)
                n += len(chunk)
    with open(part, "rb") as f:
        if not f.read(9) == b"SIMPLE  =":
            part.unlink(missing_ok=True)
            raise Permanent("download is not a FITS file")
    part.rename(dest)
    return n


def header_wcs(fits: Path) -> tuple[float, float, float]:
    """(crval1, crval2, plate scale arcsec/px) from the first 2-D image HDU.

    MAST regenerates some products (e.g. WFC3 HAP skycells), so the pointing
    recorded when the set was first built can be stale; always re-read it.
    """
    from astropy.io import fits as afits
    import math

    with afits.open(fits, memmap=True) as hdul:
        for hdu in hdul:
            h = hdu.header
            if h.get("NAXIS", 0) >= 2 and "CRVAL1" in h:
                if "CD1_1" in h:
                    det = h["CD1_1"] * h.get("CD2_2", 0.0) - h.get("CD1_2", 0.0) * h.get("CD2_1", 0.0)
                else:
                    det = h.get("CDELT1", 0.0) * h.get("CDELT2", 0.0)
                return float(h["CRVAL1"]), float(h["CRVAL2"]), math.sqrt(abs(det)) * 3600.0
    raise Permanent("no 2-D image HDU with a WCS")


def extract(zodiacal: str, fits: Path, wcs: tuple, out_json: Path, args) -> dict:
    ra, dec, scale = wcs
    cmd = [
        zodiacal, "extract", str(fits), "-o", str(out_json),
        "--threshold-sigma", str(args.threshold_sigma),
        "--max-sources", str(args.max_sources),
        "--ra", repr(ra), "--dec", repr(dec), "--plate-scale", repr(scale),
    ]
    p = subprocess.run(cmd, capture_output=True, text=True, timeout=1800)
    if p.returncode != 0:
        raise Permanent(f"extract exit {p.returncode}: {p.stderr.strip()[-300:]}")
    with open(out_json) as f:
        return json.load(f)


def process(path: Path, args, extract_gate: threading.Semaphore, local: threading.local) -> str:
    out = args.out / path.name
    if out.exists():
        return "skip"
    case = json.loads(path.read_text())
    url = case.get("hst", {}).get("image_url")
    if not url:
        raise Permanent("no hst.image_url")
    if not hasattr(local, "session"):
        local.session = requests.Session()
    stem = hashlib.sha1(path.name.encode()).hexdigest()[:12]
    fits = args.tmp / f"{stem}.fits"
    tmp_json = args.tmp / f"{stem}.json"
    try:
        for attempt, wait in enumerate([0] + RETRY_WAITS):
            if wait:
                time.sleep(wait + random.uniform(0, wait / 4))
            try:
                nbytes = download(url, fits, local.session)
                break
            except Permanent:
                raise
            except (requests.RequestException, OSError) as e:
                if attempt == len(RETRY_WAITS):
                    raise
                print(f"[retry {attempt + 1}] {path.name}: {type(e).__name__}: {e}", flush=True)
        with extract_gate:
            wcs = header_wcs(fits)
            ext = extract(args.zodiacal, fits, wcs, tmp_json, args)
        new = dict(case)
        for k in ("ra_deg", "dec_deg", "plate_scale_arcsec", "image_width", "image_height", "sources"):
            new[k] = ext[k]
        new["extraction"] = {
            "tool": f"zodiacal extract ({Path(args.zodiacal).name})",
            "threshold_sigma": args.threshold_sigma,
            "max_sources": args.max_sources,
            "fits_bytes": nbytes,
            "date": dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        }
        changed = {k: case[k] for k in ("ra_deg", "dec_deg", "plate_scale_arcsec", "image_width", "image_height")
                   if abs(float(case[k]) - float(new[k])) > 1e-9}
        if changed:
            # The archived product differs from the one the set was first built from.
            new["extraction"]["product_changed_from"] = changed
        staged = out.with_suffix(".json.tmp")
        payload = json.dumps(new, separators=(",", ":"))
        with open(staged, "w") as f:
            f.write(payload)
            f.flush()
            os.fsync(f.fileno())
        # Read back before publishing: a full disk once left zero-byte
        # outputs that the resume logic then treated as done.
        if staged.read_text() != payload:
            staged.unlink(missing_ok=True)
            raise OSError("staged output did not read back intact")
        staged.rename(out)
        return f"ok {len(ext['sources'])}"
    finally:
        fits.unlink(missing_ok=True)
        fits.with_suffix(".fits.part").unlink(missing_ok=True)
        tmp_json.unlink(missing_ok=True)


def progress(done: int, total: int, label: str):
    if os.environ.get("PORTAL_SESSION_ID") and shutil.which("agent-portal"):
        subprocess.run(["agent-portal", "progress", f"{done}/{total}", "--id", "hst",
                        "--label", label], capture_output=True)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    here = Path(__file__).resolve().parent.parent
    ap.add_argument("--cases", type=Path, default=here / "hubble-f606w")
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--tmp", type=Path, required=True)
    ap.add_argument("--zodiacal", required=True, help="path to a zodiacal binary built with cli,fits,image-processing")
    ap.add_argument("--workers", type=int, default=32, help="concurrent downloads (MAST soft limit is 50)")
    ap.add_argument("--extract-workers", type=int, default=12, help="concurrent extractor processes")
    ap.add_argument("--threshold-sigma", type=float, default=5.0)
    ap.add_argument("--max-sources", type=int, default=200)
    ap.add_argument("--limit", type=int, default=0, help="process at most N pending cases (0 = all)")
    args = ap.parse_args()

    args.out.mkdir(parents=True, exist_ok=True)
    args.tmp.mkdir(parents=True, exist_ok=True)
    for stale in args.tmp.iterdir():
        stale.unlink()

    cases = sorted(args.cases.glob("*.json"))
    total = len(cases)
    pending = [p for p in cases if not (args.out / p.name).exists()]
    # Shuffle deterministically so progress and throughput are representative
    # of the whole set instead of one instrument at a time.
    random.Random(0).shuffle(pending)
    if args.limit:
        pending = pending[: args.limit]
    done0 = total - len([p for p in cases if not (args.out / p.name).exists()])
    print(f"{total} cases, {done0} already done, {len(pending)} to process", flush=True)

    gate = threading.Semaphore(args.extract_workers)
    local = threading.local()
    fail_log = open(args.out / "_failures.jsonl", "a")
    counts = {"ok": 0, "zero": 0, "fail": 0}
    t0 = last = time.time()
    with cf.ThreadPoolExecutor(args.workers) as pool:
        futs = {pool.submit(process, p, args, gate, local): p for p in pending}
        for i, fut in enumerate(cf.as_completed(futs), 1):
            p = futs[fut]
            try:
                r = fut.result()
                if r.startswith("ok"):
                    counts["ok"] += 1
                    counts["zero"] += r == "ok 0"
            except Exception as e:  # noqa: BLE001 - log every failure and keep going
                counts["fail"] += 1
                fail_log.write(json.dumps({"case": p.name, "error": f"{type(e).__name__}: {e}",
                                           "at": time.strftime("%Y-%m-%dT%H:%M:%S")}) + "\n")
                fail_log.flush()
                print(f"FAIL {p.name}: {type(e).__name__}: {e}", flush=True)
            now = time.time()
            if now - last > 60 or i == len(pending):
                last = now
                rate = i / (now - t0)
                eta = (len(pending) - i) / rate if rate else 0
                done = done0 + counts["ok"]
                msg = (f"{done}/{total} done ({counts['zero']} zero-source, {counts['fail']} failed); "
                       f"{rate * 60:.1f}/min, ETA {dt.timedelta(seconds=int(eta))}")
                print(msg, flush=True)
                progress(done, total, f"HST re-extract {done}/{total} · ETA "
                         f"{(dt.datetime.now() + dt.timedelta(seconds=eta)).strftime('%a %H:%M')}")
    print(f"finished: {counts}", flush=True)
    # Exit 0 once every pending case has been attempted, even if some failed:
    # failures are recorded in _failures.jsonl and retried on the next run.
    # A non-zero exit is reserved for crashes so a supervisor's
    # Restart=on-failure doesn't loop forever on a permanently missing file.
    return 0


if __name__ == "__main__":
    sys.exit(main())
