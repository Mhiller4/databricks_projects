"""Registry of public, no-credential datasets we can join to whatever the organizers give us.

Every source lands in the bronze volume at:  <landing>/public/<key>/<filename>
and becomes the bronze table:               <catalog>.<bronze_schema>.<key>

Most of these join on 5-digit county FIPS. The ZCTA crosswalk turns ZIP codes into FIPS,
and the county-name lookup (built in silver) turns "state + county name" into FIPS.

URLs checked 2026-11-20. If one breaks, open its homepage and grab the new CSV link.
Stdlib only: scripts/fetch_public_sources.py imports this without pyspark.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class PublicSource:
    key: str  # bronze table name and landing subfolder
    title: str
    url: str
    filename: str
    publisher: str
    grain: str  # one row per ...
    join_key: str
    why_it_matters: str
    homepage: str
    delimiter: str = ","
    caveats: str = ""


PUBLIC_SOURCES: list[PublicSource] = [
    PublicSource(
        key="svi_county_2022",
        title="Social Vulnerability Index (SVI) 2022, county",
        url="https://svi.cdc.gov/Documents/Data/2022/csv/states_counties/SVI_2022_US_county.csv",
        filename="SVI_2022_US_county.csv",
        publisher="CDC / ATSDR",
        grain="county",
        join_key="FIPS (5-digit)",
        why_it_matters="Poverty, uninsured, disability, language, housing and transport: "
        "the social drivers behind most health outcomes. Also our county spine and population.",
        homepage="https://www.atsdr.cdc.gov/place-health/php/svi/svi-data-documentation-download.html",
        caveats="Missing values are coded -999. ACS 2018-2022 estimates. "
        "Connecticut uses the new planning-region FIPS (09110-09190).",
    ),
    PublicSource(
        key="places_county",
        title="PLACES: Local Data for Better Health, county estimates",
        url="https://data.cdc.gov/api/views/swc5-untb/rows.csv?accessType=DOWNLOAD",
        filename="PLACES_county.csv",
        publisher="CDC",
        grain="county x measure x year (long format)",
        join_key="LocationID (5-digit FIPS)",
        why_it_matters="Model-based prevalence of ~40 measures: diabetes, obesity, depression, "
        "smoking, checkups, lack of insurance, and more.",
        homepage="https://data.cdc.gov/d/swc5-untb",
        caveats="Small-area model estimates (BRFSS-based), not direct counts. "
        "Measures can come from different survey years.",
    ),
    PublicSource(
        key="overdose_county_vsrr",
        title="VSRR Provisional County-Level Drug Overdose Death Counts",
        url="https://data.cdc.gov/api/views/gb4e-yj24/rows.csv?accessType=DOWNLOAD",
        filename="VSRR_county_overdose.csv",
        publisher="CDC / NCHS",
        grain="county x month (12-month-ending counts)",
        join_key="FIPS (unpadded integer - pad to 5)",
        why_it_matters="Outcome measure in lives lost; monthly, recent, every county.",
        homepage="https://data.cdc.gov/d/gb4e-yj24",
        caveats="Counts of 1-9 are suppressed (blank + footnote), which hits small rural counties "
        "hardest. Provisional and revised over time. Each row is a rolling 12-month count.",
    ),
    PublicSource(
        key="hpsa_primary_care",
        title="HRSA Health Professional Shortage Areas: Primary Care",
        url="https://data.hrsa.gov/DataDownload/DD_Files/BCD_HPSA_FCT_DET_PC.csv",
        filename="BCD_HPSA_FCT_DET_PC.csv",
        publisher="HRSA",
        grain="HPSA designation component",
        join_key="State and County FIPS Code",
        why_it_matters="Where clinicians are federally recognized as too scarce: a direct "
        "policy lever (loan repayment, NHSC placement, Medicare bonus).",
        homepage="https://data.hrsa.gov/data/download",
        caveats="Includes withdrawn designations; filter on status. One HPSA can span rows.",
    ),
    PublicSource(
        key="hpsa_mental_health",
        title="HRSA Health Professional Shortage Areas: Mental Health",
        url="https://data.hrsa.gov/DataDownload/DD_Files/BCD_HPSA_FCT_DET_MH.csv",
        filename="BCD_HPSA_FCT_DET_MH.csv",
        publisher="HRSA",
        grain="HPSA designation component",
        join_key="State and County FIPS Code",
        why_it_matters="Mental-health and substance-use workforce gaps.",
        homepage="https://data.hrsa.gov/data/download",
        caveats="Same structure as the primary-care file.",
    ),
    PublicSource(
        key="cms_hospital_general_info",
        title="CMS Hospital General Information (Care Compare)",
        url="https://data.cms.gov/provider-data/api/1/datastore/query/xubh-q36u/0/download?format=csv",
        filename="Hospital_General_Information.csv",
        publisher="CMS",
        grain="hospital",
        join_key="State + County/Parish name (no FIPS!) or ZIP",
        why_it_matters="Hospital supply, emergency services, birthing-friendly status, star "
        "ratings, and mortality/readmission measures worse than national.",
        homepage="https://data.cms.gov/provider-data/dataset/xubh-q36u",
        caveats="No FIPS column: we match on state + county name, falling back to ZIP. "
        "'Not Available' strings throughout.",
    ),
    PublicSource(
        key="usda_rucc_2023",
        title="USDA ERS Rural-Urban Continuum Codes 2023",
        url="https://ers.usda.gov/sites/default/files/_laserfiche/DataFiles/53251/Ruralurbancontinuumcodes2023.csv",
        filename="Ruralurbancontinuumcodes2023.csv",
        publisher="USDA ERS",
        grain="county x attribute (long format)",
        join_key="FIPS (5-digit)",
        why_it_matters="Rural vs urban (1 = big metro ... 9 = remote rural). Most healthcare "
        "access stories are rural stories.",
        homepage="https://www.ers.usda.gov/data-products/rural-urban-continuum-codes",
        caveats="Long format (Attribute/Value); pivot it.",
    ),
    PublicSource(
        key="zcta_county_xwalk_2020",
        title="Census 2020 ZCTA-to-County relationship file",
        url="https://www2.census.gov/geo/docs/maps-data/data/rel2020/zcta520/tab20_zcta520_county20_natl.txt",
        filename="tab20_zcta520_county20_natl.txt",
        publisher="US Census Bureau",
        grain="ZCTA x county overlap",
        join_key="ZCTA5 -> county GEOID",
        why_it_matters="Turns ZIP codes in patient/facility data into counties so everything joins.",
        homepage="https://www.census.gov/geographies/reference-files/time-series/geo/relationship-files.html",
        delimiter="|",
        caveats="ZCTAs approximate USPS ZIPs. A ZCTA can span counties; we keep the county with "
        "the largest land-area share and expose that share.",
    ),
]

SOURCES_BY_KEY = {s.key: s for s in PUBLIC_SOURCES}


def select_sources(selection: str | None) -> list[PublicSource]:
    """'all' / '' -> every source; otherwise a comma-separated list of keys."""
    if not selection or selection.strip().lower() == "all":
        return list(PUBLIC_SOURCES)
    keys = [k.strip() for k in selection.split(",") if k.strip()]
    unknown = [k for k in keys if k not in SOURCES_BY_KEY]
    if unknown:
        raise ValueError(f"Unknown source keys {unknown}. Valid: {sorted(SOURCES_BY_KEY)}")
    return [SOURCES_BY_KEY[k] for k in keys]
