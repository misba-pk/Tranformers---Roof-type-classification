# Phase 4 — Tabular baseline findings (Zhou et al. reproduction)

Study area: Friedrichshain-Kreuzberg, Berlin (one borough, used as a fast-iteration test bed
before scaling to all of Berlin). Reproduction target: Zhou et al., "Predicting building types
using OpenStreetMap," Scientific Reports (2022).

## Two experiments, not one

- **Path A (`clf`)** — label derived from OSM's own `building=*` tag. Fast to build, but **not**
  a reproduction of the paper's methodology: the paper uses OSM tags only to assess tag
  completeness (their Fig. 1), never as the classifier's training target.
- **Path B (`clf2`)** — label derived from Berlin's ALKIS cadastral data (`bezgfk` attribute),
  independent of OSM. This is the actual paper-faithful experiment: an authoritative ground
  truth, analogous to the paper's US county assessor data.

## Results

| | Path A (OSM label) | Path B (ALKIS label) | Paper (Fairfax/Mecklenburg/Boulder) |
|---|---|---|---|
| Accuracy | 86.8% | **87.4%** | 96.7–98.0% |
| Non-residential F1 | 0.68 | **0.80** | 0.74–0.84 |
| Non-residential recall | 0.72 | 0.85 | 0.60–0.82 |
| Residential F1 | 0.92 | 0.91 | 0.98–0.99 |
| Macro F1 | 0.80 | 0.85 | — |
| Training rows | 10,386 | 9,891 | 171,872–269,366 per county |

Path B's non-residential F1 (0.80) sits squarely inside the paper's own reported range
(0.74–0.84) — the reproduction is faithful where it matters most (the hard, imbalanced class).
Overall accuracy remains ~10 points below the paper across both experiments.

## What closed the initial gap, and what didn't

An early, less careful version of this pipeline (OSM-tag heuristic ground truth, unpruned
default tree, one-hot-per-observed-value building tags) produced 85.2%/86.2% accuracy with a
much weaker non-residential F1 (0.64/0.79). A methodology review against the paper's own text
and GitHub repo found several real deviations, fixed in order:

1. Ground truth was built from a keyword heuristic, not an explicit reviewed allowlist —
   replaced with an explicit per-category allowlist (mirrors the paper's Table 4 "Not used"
   category). This removed ~2,243 ambiguous rows (mixed-use, agricultural, ancillary
   parking/storage, ambiguous institutional-care categories) from Path B's training set.
2. `DecisionTreeClassifier` was unconstrained. The paper's actual repo code (not just its prose)
   uses `class_weight={0: 2.0, 1: 1.0}`, `min_samples_split=20`, `min_impurity_decrease=0.0001`
   — added, verified directly against `FFX_County_Extraction.ipynb`.
3. Building-tag encoding was one-hot-per-observed-value (~80–150 columns, region-specific) —
   replaced with the paper's fixed 29-value list + `miscellaneous`.
4. Road-class buckets had `trunk` in the wrong bucket and invented link-type handling the paper
   never specifies — corrected to the paper's exact tag lists.
5. Parking only pulled `amenity=parking`, missing `parking_space` — added.
6. Non-polygon OSM objects (bare nodes/lines tagged `building=*`) were contaminating area/buffer
   calculations — filtered immediately after download.
7. The ALKIS spatial join ranked all candidates by overlap area before filtering to valid
   labels, letting an excluded (mixed-use) polygon out-rank a smaller valid neighbor — reordered
   to filter first, plus a minimum 50% overlap-ratio requirement.

**Effect of fixes 1–2 was the largest**: non-residential recall rose from 0.79 → 0.85 in Path B,
directly attributable to the class-weighting the paper's repo uses but its prose doesn't fully
convey. Fixing the ground-truth allowlist *reduced* the training set by ~18% yet held or
improved every metric — evidence that label quality mattered more than label quantity here.

**Effect on the accuracy gap versus the paper was small.** Both experiments still trail the
paper's 96.7–98% by roughly 10 points, even after eliminating every methodological deviation
identified. That is itself informative: with implementation fidelity now controlled for, the
remaining gap is best explained by genuine urban-form difference rather than any remaining bug —
Friedrichshain-Kreuzberg is dense, mixed-use inner-city Berlin, while Fairfax/Mecklenburg/Boulder
are more zoned, car-oriented US suburbs where "what's nearby" more cleanly predicts building
function. Direct evidence for this: ~9.6% of this borough's ALKIS-labeled building stock
(`Wohngebäude mit Handel und Dienstleistungen` and five similar categories) is *officially,
cadastrally* both residential and non-residential in the same structure — a mixing the paper's
suburban US counties don't appear to exhibit at anywhere near this rate.

## Caveats carried forward

- Single borough, single random 80/20 split — not yet tested with spatial cross-validation
  (see the original research brief's warning about spatial-autocorrelation leakage).
- Path A remains a pipeline smoke-test, not a citable reproduction result — only Path B's
  numbers should be quoted as "reproducing Zhou et al. on Berlin data."
- The residential/non-residential allowlist (`docs/phase0-taxonomy.md` §2b) reflects judgment
  calls specific to this borough's 149 observed `bezgfk` values; re-review before scaling to all
  of Berlin, since new categories may appear.
