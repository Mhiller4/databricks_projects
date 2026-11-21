"""Healthcare datathon helpers.

Modules:
    sources  - registry of public datasets (stdlib only; also used by scripts/)
    naming   - column-name sanitizing (stdlib only)
    config   - widget/job-parameter config for notebooks
    io       - download + read-any-file + write-bronze helpers
    geo      - FIPS / ZIP / county-name standardization and joins
    clean    - generic "messy data" cleaner with an audit log
    profile  - data-quality profiling (scorecard) for any table

Keep this package importable without pyspark so local scripts and tests work.
"""
