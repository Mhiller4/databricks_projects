# Quick Start

## Prerequisites

- Databricks CLI configured for your workspace
- Unity Catalog enabled in the target workspace
- Permission to create schemas, volumes, and jobs

## 1) Prepare placeholders

Update these placeholders before first deploy:

- Workspace hosts in `databricks.yml`
- Group names in target permissions
- Catalog names by environment

## 2) Validate bundle

```bash
databricks bundle validate
```

## 3) Deploy to personal_dev

```bash
databricks bundle deploy --target personal_dev
```

## 4) Run an example job

```bash
databricks bundle run template_medallion_raw_job --target personal_dev
```

## 5) Run full orchestrator

```bash
databricks bundle run template_orchestrator_full --target personal_dev
```

## Notes

- This project is intentionally scaffolded with examples and placeholders.
- Replace notebook paths and parameters incrementally as your project matures.
- You can also do all of these steps in the UI of Databricks
