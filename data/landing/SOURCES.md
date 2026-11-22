# Outside data files

These files are copied into the landing volume (`/Volumes/<catalog>/hc_bronze/landing/`) by
`notebooks/bronze/02_ingest_external_files.py` the first time the pipeline runs, so a new workspace needs no
manual upload. The challenge data itself (Virtue Foundation facilities, India Post PIN directory, NFHS-5) is
not here: it comes from the Delta Share (see the README).

| File | What it is | Publisher | Licence / terms |
|---|---|---|---|
| `hospital_directory.csv` | ~30k hospitals with address, PIN and coordinates | National Health Portal, Government of India (via data.gov.in) | Government Open Data License – India (attribution) |
| `2011_Census_india.xlsx` | District population, Census 2011 | Office of the Registrar General & Census Commissioner, India | Public government data |
| `india_districts_2011.geojson`, `india_districts_2001.geojson` | District boundaries with Census codes | DataMeet, https://github.com/datameet/maps | CC BY (attribution to DataMeet) |
| `count_procedure_per_state.csv`, `count_specialty_per_state.csv` | PM-JAY (Ayushman Bharat) top procedures and specialties per state, 2025 | National Health Authority, PM-JAY | Public figures [confirm download source] |
| `Healthcare professionals for every 10,000 people (2023) - Data For India.csv` | Health workers per 10,000 people by state | Data For India, https://www.dataforindia.com | Attribution to Data For India |
| `Medical_Facilities_Michigan_Study.tsv`, `36151-0006-Codebook.pdf` | IHDS-II 2011–12 medical facility survey (DS6) and its codebook | Desai, Vanneman and NCAER, India Human Development Survey-II, ICPSR 36151, https://www.icpsr.umich.edu/web/ICPSR/studies/36151 | ICPSR terms of use. Included here only so judges can reproduce the pipeline; download your own copy from ICPSR for any other use. |
