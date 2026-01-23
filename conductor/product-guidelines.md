# Product Guidelines

## Tone and Style
- **Approachable and Explanatory:** Documentation and comments should provide context and examples to help both hobbyists and developers understand the project's logic and configuration.

## Design Principles
- **Simplicity:** Focus on ease of use with sensible defaults and a straightforward configuration process.
- **Resilience:** The daemon must be robust, handling intermittent network connectivity to the MQTT broker or the inverter without requiring a manual restart.
- **Observability:** Comprehensive and clear logging is essential for diagnosing connection problems or data parsing issues.

## Non-Goals
- **No GUI:** The project will remain a CLI/daemon-based tool.
- **No Cloud Dependency:** Operation should be independent of external cloud services, focusing on local communication.
- **No Data Persistence:** The project will focus on data transport (MQTT) rather than long-term storage or database management.
