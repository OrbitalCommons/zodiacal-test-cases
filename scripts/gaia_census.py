#!/usr/bin/env python3
"""Count Gaia DR3 stars inside each test case's field of view.

For every `<case>.json` in a set, this counts Gaia stars from a starfield
"bycell" excerpt (HEALPix level-5 nested `shard_NNNNN.csv.gz` files) that fall
inside the image. Cases carry centre, plate scale and image size but not the
rotation, so two counts bracket the truth:

  * `in`  — inside the inscribed circle (radius = min(w, h) / 2): lower bound
  * `out` — inside the circumscribed circle (radius = half the diagonal):
            upper bound

Counts are reported at G <= 16, 18, 19 and 20, plus the number of stars (in
the circumscribed circle, G <= 20) with a full 5/6-parameter astrometric
solution (pmra present). Output is one CSV row per case.

Example:
    scripts/gaia_census.py --cases hubble-f606w \
        --excerpt ~/.cache/starfield/gaia-excerpts/dr3-mag20-bycell \
        --out hubble-f606w/_gaia_census.csv --procs 32
"""

import argparse
import csv
import gzip
import json
import math
import multiprocessing as mp
from collections import defaultdict
from pathlib import Path

import numpy as np
from astropy import units as u
from astropy.coordinates import Latitude, Longitude
from astropy_healpix import HEALPix

LEVEL = 5
MAGS = (16.0, 18.0, 19.0, 20.0)
# Column indices in the starfield Gaia DR3 excerpt CSV.
C_RA, C_DEC, C_PMRA, C_G = 5, 7, 14, 22


def load_cases(cases_dir: Path):
    cases = []
    for p in sorted(cases_dir.glob("*.json")):
        d = json.loads(p.read_text())
        s = d["plate_scale_arcsec"] / 3600.0
        w, h = d["image_width"] * s, d["image_height"] * s
        cases.append({
            "case": p.name, "ra": d["ra_deg"], "dec": d["dec_deg"],
            "r_in": min(w, h) / 2.0, "r_out": math.hypot(w, h) / 2.0,
            "inst": d.get("hst", {}).get("instrument_name", ""),
            "n_src": len(d.get("sources", [])),
        })
    return cases


def cells_for(hp: HEALPix, c) -> list:
    # Pad by one cell-size worth of margin is unnecessary: cone_search returns
    # every pixel overlapping the disc.
    return list(hp.cone_search_lonlat(Longitude(c["ra"] * u.deg), Latitude(c["dec"] * u.deg),
                                      radius=c["r_out"] * u.deg))


def unit(ra_deg, dec_deg):
    ra, dec = np.radians(ra_deg), np.radians(dec_deg)
    cd = np.cos(dec)
    return np.stack([cd * np.cos(ra), cd * np.sin(ra), np.sin(dec)], axis=-1)


def count_cell(job):
    path, members = job
    ras, decs, gs, haspm = [], [], [], []
    try:
        with gzip.open(path, "rt") as f:
            next(f)
            for line in f:
                p = line.split(",")
                g = p[C_G]
                if not g:
                    continue
                ras.append(float(p[C_RA]))
                decs.append(float(p[C_DEC]))
                gs.append(float(g))
                haspm.append(p[C_PMRA] != "")
    except FileNotFoundError:
        return [(m["case"], [0] * (2 * len(MAGS) + 1)) for m in members]
    if not ras:
        return [(m["case"], [0] * (2 * len(MAGS) + 1)) for m in members]
    xyz = unit(np.array(ras), np.array(decs))
    g = np.array(gs)
    pm = np.array(haspm)
    out = []
    for m in members:
        c = unit(m["ra"], m["dec"])
        cosd = xyz @ c
        sep = np.degrees(np.arccos(np.clip(cosd, -1.0, 1.0)))
        inside_in = sep <= m["r_in"]
        inside_out = sep <= m["r_out"]
        row = [int(np.sum(inside_in & (g <= mg))) for mg in MAGS]
        row += [int(np.sum(inside_out & (g <= mg))) for mg in MAGS]
        row.append(int(np.sum(inside_out & (g <= 20.0) & pm)))
        out.append((m["case"], row))
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--cases", type=Path, required=True)
    ap.add_argument("--excerpt", type=Path, required=True)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--procs", type=int, default=16)
    args = ap.parse_args()

    hp = HEALPix(nside=2 ** LEVEL, order="nested")
    cases = load_cases(args.cases)
    by_cell = defaultdict(list)
    for c in cases:
        for cell in cells_for(hp, c):
            by_cell[int(cell)].append(c)
    print(f"{len(cases)} cases touch {len(by_cell)} level-{LEVEL} cells", flush=True)

    totals = {c["case"]: [0] * (2 * len(MAGS) + 1) for c in cases}
    jobs = [(args.excerpt / f"shard_{cell:05d}.csv.gz", members) for cell, members in by_cell.items()]
    # Big cells first so the pool doesn't end on a straggler.
    jobs.sort(key=lambda j: -(j[0].stat().st_size if j[0].exists() else 0))
    with mp.Pool(args.procs) as pool:
        for i, res in enumerate(pool.imap_unordered(count_cell, jobs, chunksize=1), 1):
            for name, row in res:
                t = totals[name]
                for k, v in enumerate(row):
                    t[k] += v
            if i % 500 == 0:
                print(f"  {i}/{len(jobs)} cells", flush=True)

    hdr = ["case", "instrument", "n_sources", "r_in_arcsec", "r_out_arcsec"]
    hdr += [f"in_g{int(m)}" for m in MAGS] + [f"out_g{int(m)}" for m in MAGS] + ["out_g20_with_pm"]
    with open(args.out, "w", newline="") as f:
        wr = csv.writer(f)
        wr.writerow(hdr)
        for c in cases:
            wr.writerow([c["case"], c["inst"], c["n_src"], round(c["r_in"] * 3600, 2),
                         round(c["r_out"] * 3600, 2)] + totals[c["case"]])
    print(f"wrote {args.out}", flush=True)


if __name__ == "__main__":
    main()
