# Specification: Project Initialization and Baseline Verification

## Overview
This track establishes a stable baseline for the GoodWe2MQTT project by verifying existing functionality, setting up a testing environment, and ensuring that core components (Inverter communication and MQTT publishing) are working as expected.

## Requirements
- Verify that `goodwe2mqtt.py` can successfully connect to an inverter (using mock or real device).
- Verify that `goodwe2mqtt.py` can successfully publish data to an MQTT broker.
- Implement a basic suite of unit tests for `logger.py` and core utility functions.
- Ensure the configuration file `goodwe2mqtt.yaml` is correctly parsed.

## Success Criteria
- Test suite passes with at least 80% coverage on core logic.
- Documentation for running the daemon and tests is up to date.