# Databricks Asset Bundle Starter Template

This template is a professional, placeholder-first reference for teams that are strong in data engineering and new to Databricks bundle conventions.

## What this template demonstrates

- A clean, commented `databricks.yml` with `personal_dev`, `dev`, `test`, and `prod` targets.
- Medallion architecture example notebooks (`drop_zone`, `raw`, `enriched`, `curated`).
- A non-medallion example notebook path (reverse ETL style).
- One resource file per job, including schedule examples and dependency patterns.
- A full orchestrator job that links layer jobs together.
- A Databricks tooling crash-course notebook (widgets, `%sql`, dbutils patterns, runtime tips).
- A scaffolded Databricks App folder for future expansion.

## Template philosophy

- v1 is intentionally placeholder-heavy.
- Comments explain why a section exists and how it links to other sections.
- Runtime logic is minimal by design.

## Suggested onboarding flow

1. Read `databricks.yml`.
2. Review `resources/00_schemas_and_volumes.yml`.
3. Follow layer jobs in `resources/10_*` through `resources/13_*`.
4. Review orchestration in `resources/30_orchestrator_full.yml`.
5. Run the crash-course notebook in `notebooks/tooling_demo/databricks_crash_course.py`.

## Typical commands

```bash
databricks bundle validate
databricks bundle deploy --target personal_dev
databricks bundle run template_orchestrator_full --target personal_dev
```

## Next steps for a real project

1. Replace placeholders for workspace hosts, groups, and catalog names.
2. Rename schemas and jobs to your domain language.
3. Replace notebook placeholders with domain logic.
4. Add tests and validation tasks per pipeline stage.
