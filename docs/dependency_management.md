# Dependency Management

## Decision

For Docker runtime, keep `requirements.txt` as the install source used by CI and image builds.

For local development, Poetry can be adopted incrementally (via `pyproject.toml`) without breaking current workflows.

## Why

- Keeps production and CI behavior stable.
- Enables gradual migration from ad-hoc local `venv` management to Poetry-managed dev environments.
- Avoids a disruptive all-at-once tooling switch.
