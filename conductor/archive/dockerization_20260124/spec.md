# Specification: Dockerization

## Overview
This track focuses on containerizing the application to simplify deployment and distribution. It includes creating a production-ready Dockerfile, a Docker Compose setup for easy orchestration, and a CI/CD pipeline for automated image builds and multi-architecture support.

## Functional Requirements

### 1. Docker Containerization
-   **Base Image:** Use a lightweight, secure base image (e.g., `python:3.11-slim`).
-   **Multi-Arch Support:** The build process must support `linux/amd64` and `linux/arm64` (targeting Raspberry Pi users).
-   **Configuration:** 
    -   Support loading configuration from the existing `goodwe2mqtt.yaml` file mounted as a volume.
    -   Implement support for Environment Variables to override or set configuration values (e.g., `G2M_MQTT_HOST`, `G2M_INVERTER_IP`).

### 2. Orchestration (Docker Compose)
-   Create a `docker-compose.yml` file that:
    -   Defines the `goodwe2mqtt` service.
    -   Optionally includes an MQTT broker (e.g., Eclipse Mosquitto) for a self-contained testing/deployment stack.
    -   Configures volume mappings for configuration and logs.
    -   Sets appropriate network modes (e.g., `host` or `bridge`).

### 3. Automated Builds (CI/CD)
-   **Registry:** Push images to GitHub Container Registry (GHCR).
-   **Trigger:** Automatically build and push on new tags (releases) and push to `main` (as `edge` tag).
-   **Versioning:** Tag images with Semantic Versioning (matching git tags) and `latest`.

## Non-Functional Requirements
-   **Documentation:** 
    -   Add a "Docker" section to the `README.md` or a dedicated `docs/docker.md`.
    -   Include instructions for `docker run` and `docker-compose up`.
    -   Document all supported environment variables.
-   **Security:** Run the application as a non-root user inside the container.

## Acceptance Criteria
-   [ ] A `Dockerfile` exists and successfully builds the application.
-   [ ] A `docker-compose.yml` file exists and starts the stack.
-   [ ] The application runs correctly inside Docker on both x86 and ARM architectures.
-   [ ] Configuration can be set via Environment Variables.
-   [ ] CI pipeline (GitHub Actions) successfully builds and pushes multi-arch images to GHCR.
