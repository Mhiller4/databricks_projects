# Template Map

## Core files

- `databricks.yml`: bundle metadata, variables, include rules, and targets.
- `resources/*.yml`: one resource definition per file.

## Notebook examples

- `notebooks/medallion_example/drop_zone/*`: landing and validation patterns.
- `notebooks/medallion_example/raw/*`: ingestion pattern placeholder.
- `notebooks/medallion_example/enriched/*`: merge/enrichment placeholder.
- `notebooks/medallion_example/curated/*`: reporting/output placeholder.
- `notebooks/non_medallion_example/*`: alternate architecture example.
- `notebooks/tooling_demo/*`: Databricks feature crash-course.

## App scaffold

- `apps/starter_app`: placeholder for Databricks App implementation.
