"""Care Finder helpers (CMU Datathon, Virtue Foundation India facilities).

Modules:
    naming   - column-name sanitizing (stdlib only)
    config   - widget/job-parameter config for notebooks
    io       - download + read-any-file + write-bronze helpers
    geo      - PIN code standardization and haversine distance
    clean    - generic "messy data" cleaner with an audit log
    profile  - data-quality profiling (scorecard) for any table
    care     - Care Finder rules: services, evidence weights, trust penalties, confidence
    model    - model template helpers (baseline / LightGBM / SHAP)

Keep this package importable without pyspark so local scripts and tests work.
"""
