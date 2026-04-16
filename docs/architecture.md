# Architecture

```mermaid
flowchart LR
    subgraph Runtime["GoodWe2MQTT Container"]
        App["src/goodwe2mqtt.py\nGoodwe_MQTT per inverter"]
        Config[".env (G2M_* variables)"]
        Logs["logs volume"]
    end

    Inv1["GoodWe Inverter #1"] -->|UDP via goodwe lib| App
    InvN["GoodWe Inverter #N"] -->|UDP via goodwe lib| App
    App -->|publish runtime/status| MQTT["MQTT Broker"]
    MQTT -->|control/set topics| App
    App --> Logs
    Config --> App
```

## Repository Layout (Implementation Start)

- `src/`: application implementation modules.
- `goodwe2mqtt.py`, `logger.py`: compatibility entrypoints.
- `docs/`: operator and developer documentation.
