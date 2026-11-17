# Codebase Components

This section documents the modules that remain in `riskfabric-ml`: the Rust feature ETL,
the ML training/calibration/scoring stack, and the local infrastructure. Simulation and
world-building components moved to `scrip`; their historical documentation is under
[Defunct Implementations](../defunct_index.md).

## Component Dependency Map

```mermaid
%%{init: {
  'themeVariables': {
    'fontFamily': '"JetBrains Mono", monospace'
  }
}}%%
flowchart TD
    classDef external fill:#2a1b1b,stroke:#AD5A5A,stroke-width:1px,rx:5px,ry:5px,color:#FBE6E6;
    classDef component fill:#22252a,stroke:#4d535b,stroke-width:1px,rx:5px,ry:5px,color:#cfd2d9;

    subgraph EXT["Upstream"]
        SCRIP["scrip"]:::external
        PIPE["riskfabric-pipelines"]:::external
    end

    subgraph DE["Data Engineering"]
        ETL["etl_system"]:::component
    end

    subgraph ML["ML & Serving"]
        MT["ml_training"]:::component
        MC["ml_calibration"]:::component
        MEX["ml_explainability"]:::component
        MRB["ml_robustness"]:::component
        RS["redis_seeder"]:::component
        RTS["realtime_scorer"]:::component
        MON["monitor"]:::component
    end

    subgraph INFRA["Infrastructure"]
        INF["infrastructure"]:::component
        CA["case_admin"]:::component
    end

    SCRIP --> PIPE --> ETL --> MT
    MT --> MC --> RTS
    MC --> MEX & MRB
    RS --> RTS
    MON --> RTS
    INF --> RTS & MON & CA

    style EXT fill:#26231b,stroke:#474130,stroke-width:1px,stroke-dasharray: 3 3,color:#cfd2d9;
    style DE fill:#231e2d,stroke:#3f3354,stroke-width:1px,stroke-dasharray: 3 3,color:#cfd2d9;
    style ML fill:#28201b,stroke:#4c392c,stroke-width:1px,stroke-dasharray: 3 3,color:#cfd2d9;
    style INFRA fill:#1c2423,stroke:#2e403d,stroke-width:1px,stroke-dasharray: 3 3,color:#cfd2d9;

    linkStyle default stroke-width:1px,stroke:#5c687a
```

**<a id="fig-17"></a>Figure 17:** Component dependency map for the remaining ML/serving surface.

## Modules

- [Feature Engineering Pipeline](etl_system.md)
- [Training Pipeline](ml_training.md)
- [Model Calibration](ml_calibration.md)
- [Real-Time Scoring Service](realtime_scorer.md)
- [Model Explainability (SHAP)](ml_explainability.md)
- [Model Robustness & Drift](ml_robustness.md)
- [Infrastructure & Local Stack](infrastructure.md)
- [Django Case Management UI](case_admin.md)
- [Redis Feature Seeder](redis_seeder.md)
- [MLflow Experiment Tracking & Model Registry](ml_tooling_mlflow.md)
- [Optuna Hyperparameter Tuning](ml_tooling_optuna.md)
- [Evidently Model Monitoring](ml_tooling_evidently.md)

Legacy data-generation components are documented under
[Defunct Implementations](../defunct_index.md).
