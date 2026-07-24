# set3-dr3-mag19-galaxies-10k

Ten thousand source-extraction cases rendered from uniformly distributed
celestial pointings with Gaia DR3 stars and NASA-Sloan Atlas galaxies.
Each JSON file uses `zodiacal::extraction::SourcesJson` and contains the
brightest 200 detections from one synthetic frame.

## Generation configuration

| dimension | value |
|---|---|
| Renderer | `focalplane motion_simulator` at `baee07c6e9e2ac30e637d21ee7db104313b52fff` |
| Generator | `scripts/regenerate_test_cases.py` at `30eb4dc0df7e0fb7ebe0f34a17fd79c535e88e71` |
| Extractor | `zodiacal extract` at `757b3119ed93c22209d1cf5398b5801bd96ecaac` |
| Telescope | `cosmic-frontier-jbt50cm` |
| Focal plane | one `imx455` sensor, 9568 × 6380 pixels |
| Plate scale | 0.12953994846986508 arcsec / pixel, derived from renderer metadata |
| Stars | Gaia DR3 HEALPix excerpt, queried at `G ≤ 19` |
| Galaxies | NSA v0.1.2 FITS catalog with renderer morphology rails |
| Exposure | 10 seconds |
| Trajectory | static line, one frame |
| Pointings | uniform on the sphere |
| Pointing seed | 0 |
| Render seed | `pointing seed + case index` |
| Extraction threshold | 5 sigma |
| Maximum sources | 200 |

RA is uniform on `[0, 360)` and `sin(Dec)` is uniform on `[-1, 1]`.
The paired draws use Python's seeded `random.Random` generator, so resumed
and chunked generation preserves the same coordinate at each index.

## Reproduction

Build `motion_simulator` from focalplane commit `baee07c` and the zodiacal
CLI from commit `757b311`, then run:

```bash
python3 focalplane/scripts/regenerate_test_cases.py \
    --count 10000 \
    --seed 0 \
    --output-dir set3-dr3-mag19-galaxies-10k \
    --motion-simulator focalplane/target/release/motion_simulator \
    --zodiacal zodiacal/target/release/zodiacal \
    --excerpt-dir ~/.cache/starfield/gaia-excerpts/dr3-mag20-bycell \
    --galaxy-catalog ~/.cache/starfield/nsa/nsa_v0_1_2.fits \
    --workers 8 \
    --rayon-threads 1
```

Rendered PNGs and metadata are temporary and are deleted after successful
extraction and JSON validation.

## Validation

- 10,000 contiguous JSON files, `0000.json` through `9999.json`
- every file parses with the exact legacy `SourcesJson` fields
- all pointings, plate scales, source coordinates, and fluxes are finite
- every source coordinate falls inside its 9568 × 6380 image
- all cases contain 200 sources, for 2,000,000 sources total

Generation and final validation completed in July 2026 for
[focalplane#83](https://github.com/CosmicFrontierLabs/focalplane/issues/83).
