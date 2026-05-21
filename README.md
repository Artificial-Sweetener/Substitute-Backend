# Substitute BackEnd

[![License: AGPL-3.0-or-later](https://img.shields.io/badge/License-AGPL--3.0--or--later-blue.svg)](LICENSE) [![semantic-release](https://img.shields.io/badge/semantic--release-angular-e10079?logo=semantic-release)](https://github.com/semantic-release/semantic-release) [![Python](https://img.shields.io/badge/python-3.12%2B-blue.svg)](https://www.python.org/downloads/)

**Substitute BackEnd** is the ComfyUI backend companion for **SugarSubstitute**.

It provides the typed Python services, ComfyUI routes, metadata workflows, preview handling, telemetry hooks, and runtime adapters that SugarSubstitute uses to understand and coordinate a local ComfyUI environment.

This project is intentionally not node-first. Its visible ComfyUI node surface stays minimal; the important work happens behind the scenes as backend integration.

## What It Does

Substitute BackEnd connects SugarSubstitute to ComfyUI features that are difficult or fragile to manage from frontend code alone:

- model catalog and metadata discovery
- model fingerprinting and preview selection
- CivitAI model download orchestration
- download progress telemetry
- model loading telemetry
- SugarCubes catalog access, workflow compilation, and output events
- environment and package inventory
- maintenance planning and controlled ComfyUI restart coordination
- TAESD/VAE approximation preview asset management

The extension registers HTTP routes and runtime hooks inside ComfyUI, then exposes stable backend contracts for SugarSubstitute and compatible tooling.

## Why It Exists

SugarSubstitute needs reliable access to ComfyUI state without turning frontend code into a pile of filesystem probes, runtime monkey patches, and host-specific assumptions.

Substitute BackEnd keeps that work in one place:

- ComfyUI integration stays at the host boundary.
- Application services own workflows and orchestration.
- Domain code owns schemas, validation, and business rules.
- Infrastructure adapters own filesystem access, HTTP calls, persistence, subprocesses, ComfyUI hooks, and SugarSubstitute communication.

The result is a backend layer that can evolve independently while keeping API contracts explicit and testable.

## Installation

Install through ComfyUI Manager when available.

For manual installation, clone the repository into `ComfyUI/custom_nodes/` and install the Python package into the ComfyUI virtual environment:

```powershell
cd E:\ComfyUI\custom_nodes
git clone https://github.com/Artificial-Sweetener/Substitute-BackEnd.git
cd Substitute-BackEnd
..\..\venv\Scripts\python.exe -m pip install -e .
```

Restart ComfyUI after installation.

## Runtime Surface

Substitute BackEnd registers routes under `/substitute/v1/...`.

The route surface includes:

- `/substitute/v1/capabilities`
- `/substitute/v1/models`
- `/substitute/v1/models/by-hash/{sha256}`
- `/substitute/v1/models/fingerprints/...`
- `/substitute/v1/models/downloads/...`
- `/substitute/v1/previews/{previewId}`
- `/substitute/v1/preview-assets/taesd/...`
- `/substitute/v1/cube-library/...`
- `/substitute/v1/environment/...`

These routes are intended for SugarSubstitute and compatible backend-aware tooling. They are stable integration contracts, not a casual manual API.

## Major Features

### Model Metadata

The model metadata feature discovers local models from approved ComfyUI model roots, tracks stable fingerprint evidence, reads sidecar metadata, resolves local previews, and serves model catalog data through typed route responses.

### Model Downloads

The CivitAI download workflow streams model bytes into approved ComfyUI model locations, tracks download jobs, validates final files, seeds fingerprint evidence, and exposes cancellation and status endpoints.

### Preview Assets

The preview asset service checks and installs TAESD/VAE approximation assets used by backend preview workflows. Downloads use explicit allowlists and controlled filesystem targets.

### Cube Library

The Cube Library feature bridges ComfyUI to SugarCubes. It exposes catalog status, library packs, cube versions, icon assets, prewarming, workflow compilation, and change events while keeping SugarCubes access behind an adapter boundary.

### Cube Outputs

Cube output services observe SugarCubes runtime output events and publish structured ComfyUI websocket messages for images, videos, and temporary output metadata.

### Environment Management

Environment management reports package and component inventory, builds maintenance plans, validates requested operations, applies queued maintenance work, and coordinates ComfyUI restarts through explicit job state.

### Telemetry

Download and model-loading telemetry hooks publish progress events through ComfyUI's PromptServer so SugarSubstitute can display long-running runtime activity without blocking the UI.

## Development

Run repository gates from the ComfyUI virtual environment:

```powershell
..\..\venv\Scripts\python.exe -m pip install -e ".[dev]"
..\..\venv\Scripts\python.exe tools\add_license_headers.py
..\..\venv\Scripts\python.exe -m ruff format .
..\..\venv\Scripts\python.exe -m ruff check .
..\..\venv\Scripts\python.exe -m mypy --strict --explicit-package-bases substitute_backend tests tools
..\..\venv\Scripts\python.exe -m pytest -n auto -q
```

Do not use a separate repository-local virtual environment for normal verification. This project is meant to be tested against the same ComfyUI environment it extends.

## Architecture

The codebase is organized by ownership boundary:

- `host`: ComfyUI entry points, route registration, PromptServer integration, and extension bootstrap
- `features/*/api`: HTTP route handlers and host-facing request parsing
- `features/*/application`: orchestration and use-case services
- `features/*/domain`: typed schemas, events, statuses, validation, and pure rules
- `features/*/infrastructure`: filesystem, persistence, HTTP, subprocess, ComfyUI, and SugarSubstitute adapters
- `infrastructure`: shared logging, diagnostics, and cache path utilities

Backend behavior should live in services and adapters, not in ComfyUI node classes.

## Diagnostics

Normal operation is intentionally quiet. Runtime diagnostics use Python logging and feature-specific gates instead of unconditional success-path logging.

Cube Library diagnostics can be enabled with `SUBSTITUTE_BACKEND_DIAGNOSTICS` and, for request-bound route traces, the `X-Substitute-Cube-Trace` header. Diagnostic logs are emitted at `DEBUG`.

## License

Substitute BackEnd is licensed under the GNU Affero General Public License v3.0 or later. See [LICENSE](LICENSE) for the full license text.
