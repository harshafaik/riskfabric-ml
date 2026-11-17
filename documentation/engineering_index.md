# Data Engineering & Feature ETL

This section documents the feature ETL that remains in `riskfabric-ml`. The system boundary
is: `scrip` emits the five raw Parquet tables, `riskfabric-pipelines` validates them and
builds the star schema, and this repository's Rust ETL builds the Silver and Gold feature
tables that the models consume.

## Rust Feature ETL (`src/etl`, `src/bin/riskfabric-etl.rs`)

```mermaid
flowchart LR
    classDef external fill:#2a1b1b,stroke:#AD5A5A,stroke-width:1px,rx:5px,ry:5px,color:#FBE6E6;
    classDef stage fill:#22252a,stroke:#4d535b,stroke-width:1px,rx:5px,ry:5px,color:#cfd2d9;
    classDef store fill:#1b2a3a,stroke:#304e70,stroke-width:1px,rx:5px,ry:5px,color:#cfd2d9;

    RAW["raw Parquet<br/>scrip"]:::external --> PIPE["validated Bronze<br/>riskfabric-pipelines"]:::external
    PIPE --> BRONZE[("data/bronze")]:::store
    BRONZE --> ETL["riskfabric-etl<br/>silver-all · gold-master"]:::stage
    ETL --> SILVER[("data/silver")]:::store
    ETL --> GOLD[("data/gold")]:::store
    GOLD --> ML["src/ml<br/>training · scoring"]:::stage
```

**<a id="fig-4"></a>Figure 4:** Feature ETL boundary.

## Modules

- [Feature Engineering Pipeline](components/etl_system.md)

The geospatial reference extraction and dbt marts that used to live here moved to `scrip`
and `riskfabric-pipelines`. Their historical documentation is under
[Defunct Implementations](defunct_index.md).
