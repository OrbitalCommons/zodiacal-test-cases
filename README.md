# zodiacal-test-cases

Sky-image test-case sets for the [zodiacal](https://github.com/OrbitalCommons/zodiacal) plate-solver. Each case is a single JSON file with image dimensions, the true RA/Dec of the field centre, the plate scale, and a list of detected sources `(x, y, flux)` from running source extraction on a synthetic frame. The JSON schema matches `zodiacal::extraction::SourcesJson` and is a drop-in input for `zodiacal batch-solve` and the accuracy/residual harness.

## Sets

| set | renderer | catalog | sensor | n cases | notes |
|---|---|---|---|---|---|
| `set1-legacy/` | meter-sim `sensor_shootout` (retired) | `gaia_mag16_multi.bin` | IMX455 single | 1000 | Imported from `zodiacal/test_cases/` per [zodiacal#102](https://github.com/OrbitalCommons/zodiacal/issues/102); historical baseline (96.7% solve-rate). See `set1-legacy/README.md`. |
| `set2-dr3-mag19/` | [focalplane](https://github.com/CosmicFrontierLabs/focalplane) `motion_simulator` | Gaia DR3 mag-20 HEALPix excerpt, queried at G ≤ 19 | IMX455 single | 1000 | Generated 2026-05; see below |

## set2-dr3-mag19 — generation configuration

| dimension | value |
|---|---|
| Renderer | `focalplane motion_simulator` (commit @ time of generation) |
| Star catalog | Gaia DR3 mag-20 HEALPix-sharded excerpt (`~/.cache/starfield/gaia-excerpts/dr3-mag20-bycell`, 12 288 level-5 cells, 1.06 B rows) |
| Catalog query mag limit | `G ≤ 19` |
| Hipparcos supplement | embedded bright-star supplement, **cone-restricted** to the FOV (CosmicFrontierLabs/focalplane#82) |
| Telescope | `cosmic-frontier-jbt50cm` (0.485 m aperture, f/12.3, focal length 5.97 m) |
| Sensor | IMX455 single (9568 × 6380 px, 3.75 µm pitch) |
| Plate scale | 0.129475 arcsec / px (matches the legacy `zodiacal/test_cases/` set) |
| Exposure | 10 s |
| Trajectory | static (`--mode line` with `start = end`), 1 frame |
| Pointings | 1000, uniform on the sphere (RA uniform [0, 360°); sin(Dec) uniform [-1, 1]) |
| Pointing seed | 0 (with seed = 1 used to backfill 6 indices that hit CosmicFrontierLabs/focalplane#84) |
| Galaxies | none (`--galaxies` off) |

### Source-extraction configuration

Sources are extracted from each rendered 16-bit grayscale PNG with the `zodiacal extract` CLI:

```
zodiacal extract <png> --threshold-sigma 5.0 --max-sources 200 \
    --ra <deg> --dec <deg> --plate-scale 0.129475
```

### Caveats

- **Flux units**: `zodiacal extract` reads the PNG via `image::open().to_luma32f()`, which normalises 16-bit pixel values to `f32 ∈ [0, 1]`. The `flux` field is therefore the **summed normalised pixel value over the connected component**, not raw 16-bit ADU. For comparisons against the legacy zodiacal `test_cases/` set (which used raw FITS ADU), multiply `flux` by ~65 535 to roughly match the old units. Within set2 the values are internally consistent.
- **`max-sources` cap**: every case in set2 hits the 200-source cap, so the source list is the **brightest 200** detections per field, not all detections. Bright-star centroid accuracy is the intended use.
- **Reroll provenance**: indices `0042, 0085, 0244, 0639, 0950, 0952` were generated under the seed-1 pointing draw rather than seed-0, because the corresponding seed-0 pointings tripped the `temperature_from_bv` panic in CosmicFrontierLabs/focalplane#84. With the panic fixed (CosmicFrontierLabs/focalplane#85), a regen against seed-0 will produce a fully consistent set — that's set3.

## Schema

Each `<NNNN>.json` follows `zodiacal::extraction::SourcesJson`:

```json
{
  "image_width":  9568.0,
  "image_height": 6380.0,
  "ra_deg":       229.30620743572354,
  "dec_deg":      39.1761824846116,
  "plate_scale_arcsec": 0.129475,
  "sources": [
    { "x": 1626.37, "y": 747.87, "flux": 31.45 }
  ]
}
```

## Reproducing set2

The driver lives in the focalplane repo as [`scripts/regenerate_test_cases.py`](https://github.com/CosmicFrontierLabs/focalplane/blob/main/scripts/regenerate_test_cases.py). Build the two binaries first:

```bash
# focalplane
cargo build -p simulator --release

# zodiacal (with the FITS reader feature)
cargo build --release --features fits
```

Then:

```bash
uv run --with numpy python3 focalplane/scripts/regenerate_test_cases.py \
    --count 1000 --seed 0 \
    --output-dir <out> \
    --motion-simulator focalplane/target/release/motion_simulator \
    --zodiacal zodiacal/target/release/zodiacal \
    --excerpt-dir ~/.cache/starfield/gaia-excerpts/dr3-mag20-bycell
```

End-to-end runtime: about 3 hours on an 8-core x86 box, 16 MB of JSON output.
