# Berlin Building Type Classification — Graph Transformer

Classifying OSM building footprints in Berlin by type (residential / non-residential / extended
classes), using a shape-aware graph transformer. Full literature review, architecture
justification, and roadmap: see the project research brief (link in your notes — not checked into
this repo).

## Workflow: local prep, remote train

Everything **except training** runs locally on CPU:
- data acquisition (Overpass, Berlin Open Data LoD2, Umweltatlas)
- feature engineering, spatial graph construction
- tabular baselines (RF/XGBoost/MLP)
- model code written and smoke-tested on a tiny subset (~100–200 buildings) locally, so bugs are
  caught before spending GPU time on them

**Training** runs on the university JupyterHub GPU, connected via VS Code's Jupyter extension
(kernel-only — no shared filesystem). Processed data has to be moved there explicitly:
1. `src/prepare_data.py` (to be written) outputs a single self-contained directory under
   `data/processed/` — small enough to upload through JupyterLab's browser file upload.
2. Upload that directory once per training-ready checkpoint of the pipeline, not per experiment.
3. Training notebooks/scripts on the remote side only need `requirements-train.txt`.

## Environment setup

```
conda create -n berlin-buildings python=3.11
conda activate berlin-buildings
pip install -r requirements-local.txt
pip install torch --index-url https://download.pytorch.org/whl/cpu
```

## Structure

```
data/raw/         # untouched downloads (gitignored)
data/processed/   # feature tables, spatial graphs, model-ready tensors (gitignored)
notebooks/        # EDA, prototyping
src/              # scripts: data prep, feature engineering, model, training
docs/             # phase0-taxonomy.md and other design docs written during the project
```

## Status

- [ ] Phase 0 — problem definition (`docs/phase0-taxonomy.md`)
- [ ] Phase 1 — data acquisition
- [ ] Phase 2 — label curation & EDA
- [ ] Phase 3 — feature engineering + spatial graph
- [ ] Phase 4 — tabular baselines
- [ ] Phase 5 — polygon shape encoder
- [ ] Phase 6 — full graph transformer (remote GPU training)
- [ ] Phase 7 — evaluation & ablation
