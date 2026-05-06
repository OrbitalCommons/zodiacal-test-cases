# set1-legacy

Migration of the original `zodiacal/test_cases/` directory (1000 cases, `0000.json … 0999.json`). Schema matches `zodiacal::extraction::SourcesJson` and is unchanged from the in-repo version, so the existing `zodiacal batch-solve` harness reads these without modification.

## Provenance

These cases were generated with **meter-sim**'s `sensor_shootout` rendering against the `gaia_mag16_multi.bin` starfield catalog, with sources extracted via `zodiacal extract`. That toolchain has since been retired in favor of focalplane's `motion_simulator` (see `set2-dr3-mag19/`). This set is preserved as the historical fixture against which the 96.7% solve-rate baseline was established.

| dimension | value |
|---|---|
| Renderer | meter-sim `sensor_shootout` (retired) |
| Star catalog | `gaia_mag16_multi.bin` (~82M stars, G ≤ ~16) |
| Sensor | IMX455 single (9568 × 6380 px) |
| Plate scale | 0.129475 arcsec / px |
| Pointings | 1000 |
| Source extractor | `zodiacal extract` reading raw FITS |

## Caveats

- **Flux units**: the legacy generator read FITS files directly, so `flux` is the summed raw-ADU value over the connected component (values ~10⁴–10⁶), not the normalised `[0, 1]` sum used by set2-dr3-mag19. To compare flux distributions across sets, divide set1 fluxes by ~65 535.
- **Filename indexing is load-bearing**: zodiacal harness code positionally indexes by the `NNNN` stem (e.g. `0042.json`). Don't renumber.
- **Six pointings (`0042, 0085, 0244, 0639, 0950, 0952`) are unrelated to the same indices in set2** — set2 has its own reroll provenance (CosmicFrontierLabs/focalplane#84). Treat the two sets as independent samples of the sphere.

## Filing history

Imported from `OrbitalCommons/zodiacal@ceac666` per `OrbitalCommons/zodiacal#102`.
