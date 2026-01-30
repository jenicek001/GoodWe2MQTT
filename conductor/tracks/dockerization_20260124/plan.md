# Implementation Plan: Dockerization

## Phase 1: Containerization & Configuration Support [checkpoint: 9843ec1]
Enable the application to run inside a container and support modern configuration methods (Environment Variables).

- [x] Task: Environment Variable Configuration [c089d40]
    - [x] Write failing tests for environment variable overrides in the configuration loader
    - [x] Implement support for mapping Environment Variables (e.g., `G2M_MQTT_HOST`) to configuration values
- [x] Task: Create Production Dockerfile [c089d40]
    - [x] Create a multi-stage `Dockerfile` using `python:3.11-slim`
    - [x] Implement non-root user execution and security hardening
    - [x] Verify local build for `linux/amd64`
- [x] Task: Conductor - User Manual Verification 'Containerization & Configuration Support' (Protocol in workflow.md) [9843ec1]

## Phase 2: Orchestration & Documentation
Provide a standard way to run the stack and clear instructions for users.

- [x] Task: Docker Compose Setup [866549b]
    - [x] Create `docker-compose.yml` with `goodwe2mqtt` and optional `mosquitto` broker
    - [x] Configure volume mounts for `goodwe2mqtt.yaml` and logs
- [x] Task: Docker Documentation [2f6e285]
    - [x] Create `docs/docker.md` (or update README) with detailed instructions
    - [x] Document all supported Environment Variables and volume mount points
- [x] Task: Conductor - User Manual Verification 'Orchestration & Documentation' (Protocol in workflow.md) [d709a91]

## Phase 3: Automated Multi-Arch CI Pipeline [checkpoint: d709a91]
Automate the build and distribution process for multiple hardware architectures.

- [x] Task: Configure GitHub Actions for Docker [fd16570]
    - [x] Create/Update `.github/workflows/docker.yml` for building images
    - [x] Implement `docker/setup-qemu-action` and `docker/setup-buildx-action` for multi-arch support
    - [x] Configure authentication and push to GHCR on tags and main branch
- [x] Task: Conductor - User Manual Verification 'Automated Multi-Arch CI Pipeline' (Protocol in workflow.md)
