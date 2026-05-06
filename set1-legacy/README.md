# set1-legacy

Migration of the original `OrbitalCommons/zodiacal/test_cases/` directory: 1000 cases, `0000.json … 0999.json`. Schema matches `zodiacal::extraction::SourcesJson` and is unchanged from the in-repo version, so the existing `zodiacal batch-solve` and `zodiacal-tools bench-bundle` harnesses read these without modification.

These cases established the **96.7% blind-solve baseline** quoted in zodiacal's README. They are preserved as a frozen reference; the modern equivalent is `set2-dr3-mag19/`, regenerated with the post-fix focalplane toolchain (see top-level README).

## Provenance — at a glance

| dimension | value |
|---|---|
| Renderer | meter-sim `sensor_shootout` (retired) |
| Star catalog | `gaia_mag16_multi.bin` (~83M Gaia DR3 stars at G ≤ 16, ~2.5 GB on disk) |
| Telescope | unknown commit; IMX455 single-sensor module |
| Sensor / image | IMX455 single, 9568 × 6380 px, 3.76 µm pitch |
| Plate scale | 0.129475 arcsec / px |
| Exposure | 10 s (single frame, no motion / `--exposure-range-ms 10000`) |
| Pointings | 1000, 10 batches × 100 with `--seed 0..9` |
| Source extractor | `zodiacal extract` (MAD-based + Otsu thresholding + aspect-ratio filter) |
| Source-list cap | `--max-sources 200` (most fields hit the cap) |
| Detection threshold | `--threshold-sigma 5.0` |
| First committed | `OrbitalCommons/zodiacal@e6d24e1` (PR #23, 2026-02-10) |
| Imported here | `OrbitalCommons/zodiacal-test-cases@03e6029` (PR #1, 2026-05-06) |

## Generation pipeline (historical)

The original generator was `scripts/generate_test_cases.{sh,py}` in zodiacal, removed in `OrbitalCommons/zodiacal#103`. The pipeline was:

1. **Render**, in batches of 100 (10 batches, seeds 0..9), with meter-sim's `sensor_shootout`:
   ```
   sensor_shootout \
       --experiments 100 \
       --exposure-range-ms 10000 \
       --seed <0..9> \
       --catalog gaia_mag16_multi.bin \
       --output-dir /tmp/zodiacal_batch_<i> \
       --output-csv /tmp/zodiacal_batch_<i>.csv
   ```
   This produced one `<exp>_IMX455_10000ms_data_raw.fits` per pointing plus a CSV row recording the truth `(ra, dec, focal_length_m, sensor, exposure_ms, ...)`. The CSV is the only place the pointing truth was recorded — the FITS files were deleted at the end of each batch to bound disk usage at ~60 GB.
2. **Compute the plate scale** from each row's `focal_length_m`, using the IMX455's 3.76 µm pixel pitch:
   `plate_scale_arcsec = pixel_pitch_um · 1e-6 / focal_length_m · 206265`
   For all 1000 rows this resolved to 0.129475 arcsec/px (single-aperture telescope, no per-batch variation).
3. **Extract** sources from each FITS into JSON:
   ```
   zodiacal extract <fits> \
       --output set1-legacy/<NNNN>.json \
       --ra=<truth_ra> \
       --dec=<truth_dec> \
       --plate-scale=<computed>
   ```
   `extract` ran source detection on the in-memory image and wrote `(image_width, image_height, ra_deg, dec_deg, plate_scale_arcsec, sources)`. The truth fields are the **renderer's commanded boresight**, not the recovered solver position.

`gaia_mag16_multi.bin` and the meter-sim binary are no longer maintained, so the FITS files cannot be regenerated bit-exact. The JSON source lists committed here are the only surviving artefact.

## Source-extraction details

`zodiacal extract` (the same code path used by `solve` for image inputs) produced each `sources` array via:

- **Background**: median + MAD-from-the-median, computed over the full frame.
- **Detection**: pixels above `median + threshold_sigma · 1.4826 · MAD` (`--threshold-sigma 5.0`).
- **Connected-component grouping** with Otsu thresholding to separate touching sources.
- **Quality filter**: aspect ratio ≤ 3:1 to reject hot-pixel rows / cosmic rays.
- **Centroid**: flux-weighted first moment over the connected component.
- **Cap**: top-N by flux, `N = 200`.

The `flux` field is the **summed raw FITS pixel value** over the connected component, in ADU (raw 16-bit detector units). Typical values run 10⁴–10⁶. This differs from `set2-dr3-mag19/`, where the renderer wrote 16-bit PNGs that `image::open().to_luma32f()` normalised to `f32 ∈ [0, 1]` before extraction; set2 fluxes are roughly `set1-flux / 65 535`.

## Known systematic: ~0.13″ Dec offset (≈ 1 pixel)

When zodiacal's pointing-residual benchmark was first run against this set with high-precision RA/Dec logging, the recovered field centres showed a **systematic offset of mean +0.131″ in Dec, with mean ΔRA·cos(δ) ≈ -0.0005″** (n=257 partial run, std ~0.02″ on each axis). At 0.129475″/px that is **almost exactly one pixel**, and almost entirely along Dec rather than along the pixel y-axis rotated by the field's PA.

After subtracting the +0.131″ median, residuals collapsed to **median 2.5 mas, p95 16 mas** — i.e. the solver itself is sub-pixel by ~1/50; the apparent error is a constant additive bias.

Tracked in `OrbitalCommons/zodiacal#67`. Suspected causes (the investigation never definitively pinned one down):

1. **WCS field-centre off-by-one** in `wcs.field_center()`. Image height is even (6380), so the geometric centre falls between rows 3189 and 3190; depending on which is treated as the reference pixel, you get exactly a 1-pixel shift on the y-axis.
2. **FITS vertical-flip pixel-centre convention.** zodiacal's `load_fits()` flipped the image vertically to match its top-left origin convention. A pixel-centre vs pixel-corner mismatch in the flip would produce a y-axis-only systematic.
3. **Renderer truth offset.** meter-sim could plausibly have recorded `dec_deg` as the pre-projection boresight while the rendered image centre is a half/full pixel away.

The fact that the offset stays purely along Dec (not rotated by the random field PA into a noisy circle) means *either* (1+2) plus all set1 fields happening to share orientation 0, *or* a Dec-specific bug. set1-legacy fields **are** all rendered at PA = 0 (no rotation in the meter-sim pipeline used here), which makes (1) and (2) indistinguishable from sky observations alone.

### Why the FITS-flip fix in `OrbitalCommons/zodiacal#68` does NOT clear it for set1-legacy

PR #68 fixed a related-but-separate FITS reader bug: the previous `Array2::from_shape_vec((shape[0], shape[1]), pixels)` reshape interpreted `shape[0]=NAXIS1` as rows, but FITS-standard places `NAXIS1` on the fastest-varying axis (cols). This silently transposed-with-wrap any non-square image written by the **focalplane / cfl-foundations** writer. The vertical flip itself was retained.

That fix doesn't apply here for two independent reasons:

- **Different writer**: meter-sim's fitsio binding wrote `NAXIS1 = rows` (non-standard). zodiacal's old reshape, taken with the meter-sim convention, *was* correct for the FITS files in this set — the transpose-with-wrap bug only bites the focalplane-written FITS used in set2 / set3.
- **Frozen artefact**: even if the reader had a bug for these files, fixing it now wouldn't change the source `(x, y)` values already serialised in `set1-legacy/*.json`. The bias is baked into the JSONs.

Net effect for users: when comparing `batch-solve` outputs against `ra_deg, dec_deg` in `set1-legacy/*.json`, **subtract a constant +0.131″ Dec bias** before reasoning about solver precision. set2-dr3-mag19/ does not have this bias (focalplane records the truth post-projection and uses standard FITS).

## Notes for harness use

- **Filename indexing is load-bearing**: zodiacal's analyzers (`scripts/analyze_failures.py`, `scripts/plot_failures.py`, `paper/make_figures.py`) positionally index by the `NNNN` stem. Don't renumber.
- **Cross-set indices are not the same field**: `set1-legacy/0042.json` and `set2-dr3-mag19/0042.json` are independent samples of the sphere — both sets started from a uniform-on-the-sphere draw but with different seeds and pipelines. Treat them as disjoint corpora.
- **All cases hit the `--max-sources 200` cap** — the source list is the brightest 200 detections, not the complete catalogue of detections.

## Filing history

| date | event | ref |
|---|---|---|
| 2026-02-07 | First FITS loader, with `(naxis1, naxis2)` reshape and vertical flip for meter-sim files. | [`OrbitalCommons/zodiacal#16`](https://github.com/OrbitalCommons/zodiacal/pull/16) |
| 2026-02-10 | 1000 test fixtures committed to `OrbitalCommons/zodiacal/test_cases/`. | [`OrbitalCommons/zodiacal#23`](https://github.com/OrbitalCommons/zodiacal/pull/23) |
| 2026-04-09 | `extract` CLI + JSON schema documented. | [`OrbitalCommons/zodiacal#22`](https://github.com/OrbitalCommons/zodiacal/pull/22) |
| 2026-05-04 | ~0.13″ Dec residual identified on this set. | [`OrbitalCommons/zodiacal#67`](https://github.com/OrbitalCommons/zodiacal/issues/67) |
| 2026-05-04 | FITS reader switched to standard `NAXIS1=cols` reshape; flip retained. Does not fix this set. | [`OrbitalCommons/zodiacal#68`](https://github.com/OrbitalCommons/zodiacal/pull/68) |
| 2026-05-06 | Migrated out of `zodiacal/test_cases/` into this repo. | [`OrbitalCommons/zodiacal#102`](https://github.com/OrbitalCommons/zodiacal/issues/102), [`zodiacal-test-cases#1`](https://github.com/OrbitalCommons/zodiacal-test-cases/pull/1) |
