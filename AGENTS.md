# AGENTS.md

## Mission Statement

This project is a ComfyUI custom nodepack that acts primarily as a backend liaison between ComfyUI and SugarSubstitute.

The project is not node-first. Nodes should remain minimal host-facing integration points unless a feature truly requires ComfyUI node behavior. The main engineering focus is typed Python backend integration, stable API contracts, model preview and metadata services, and reliable communication between ComfyUI and SugarSubstitute.

## Purpose

- This file defines repository-specific engineering guardrails for Substitute BackEnd.
- Global AGENTS instructions continue to govern shared operating rules, coding preferences, planning expectations, tools, and command environment.
- Do not use this file for feature specs or product planning.

## Core Engineering Principles

- Use strict object-oriented design where stateful services, adapters, and workflows need clear ownership and lifecycle boundaries.
- Enforce strong separation of concerns as the primary architecture objective.
- Keep modules cohesive and boundaries explicit.
- Assign one authoritative owner per concern; collaborating components must derive behavior and state from that owner rather than re-implementing the concern in parallel.
- Reassess ownership before extending an existing structure.
- If a change introduces a distinct responsibility, change cadence, or collaboration boundary, split or extract it as part of the change instead of deferring cleanup.
- Prefer clean replacement over compatibility layers in internal code.
- Structural changes must be complete: update callsites, remove dead code, and remove temporary bridges.
- Favor DRY when it reduces repeated change risk.
- Avoid abstractions that hide intent.

## Architecture Rules

- Organize code around explicit ownership boundaries.
- Host-facing code owns ComfyUI entry points, route registration, `NODE_CLASS_MAPPINGS`, web extension bootstrap when present, and PromptServer integration.
- Application code owns use-case orchestration, model scanning workflows, metadata refresh, preview generation, and SugarSubstitute communication.
- Domain code owns model identity, metadata schemas, preview selection rules, cache policy, validation, and pure business logic.
- Infrastructure code owns filesystem access, API clients, image download/processing, persistence, subprocesses, and SugarSubstitute adapters.
- Keep ComfyUI globals, PromptServer objects, frontend runtime details, and external service clients out of domain logic.
- Keep nodes thin. Do not put backend workflow behavior into node classes when a route, service, or adapter boundary is the natural owner.
- Place code by ownership and dependency direction, not convenience or proximity.
- Avoid god classes and monolithic files; split by responsibility, not convenience.

## Structural Change Rules

- For behavior-critical areas, add characterization or regression tests for existing behavior before structural changes.
- When behavior spans multiple components, trace current ownership and data flow before editing.
- Prefer correcting the ownership model over layering compensating patches across consumers.
- Prefer vertical slices that land safely over large unverified rewrites.
- Align touched modules with the ownership and dependency rules in this file.

## SugarSubstitute Integration

- Treat SugarSubstitute as an external product boundary unless this repository is explicitly asked to modify it.
- Prefer stable, explicit interfaces over importing deep private internals from SugarSubstitute.
- Isolate SugarSubstitute communication behind adapters with typed request and response models.
- Version cross-process or cross-repository contracts that may be persisted or consumed by both projects.
- Do not introduce hidden mutable global state to coordinate with SugarSubstitute.

## ComfyUI Runtime Rules

- Keep import-time behavior lightweight. Do not scan models, hit the network, or start long-running work during module import.
- Guard ComfyUI-only imports so tests can run outside a live ComfyUI process.
- Register routes and web assets through ComfyUI host-facing APIs at the boundary layer.
- Use minimal node definitions when ComfyUI requires them; do not create placeholder nodes to carry backend behavior.
- Avoid blocking ComfyUI's event loop or request handlers with long model scans, metadata refreshes, or downloads.

## Model Preview and Metadata Rules

- Treat existing model-browser tools as behavioral references only, not as architecture or style references.
- Build typed, cohesive services for model discovery, metadata lookup, preview selection, sidecar persistence, and refresh workflows.
- Identify local models using stable evidence such as SHA256, known model/version IDs, and normalized paths; do not rely on display names alone.
- Treat metadata JSON, preview images, downloaded API data, and cached display artifacts as persisted data with schema expectations and migration safety.
- Validate all model paths and keep writes inside approved ComfyUI model/cache locations.
- Do not delete or overwrite model files or sidecars without an explicit user-facing operation and tests for the destructive path.
- Network calls must use explicit timeouts, clear errors, and rate-limit/cancellation-aware orchestration.

## Python Policy

- Python is the primary implementation language.
- New Python code must be fully typed.
- New and changed functions, methods, and key internal state require type annotations.
- Prefer dataclasses, typed dictionaries, protocols, enums, or validated models over unstructured dictionaries.
- Prefer explicit domain types and type narrowing over `Any`.
- Choose the most specific accurate type for each value: domain model, protocol, typed dictionary, enum, literal, generic type variable, or typed collection.
- Use `object` for opaque values that must be accepted but not inspected.
- Use `Any` only when it accurately models an intentionally unconstrained external host/API boundary that cannot be represented more precisely.
- Localize `Any` at that boundary and narrow it before the value enters domain or application code.
- Do not introduce temporary `Any` typing or use `Any` to postpone type design.

## Docstrings and Comments

- Docstrings are mandatory for new and changed modules, classes, functions, and methods.
- Use concise imperative docstrings for simple logic.
- Use Google-style docstrings for complex logic.
- Docstrings must explain rationale, constraints, and intent; they must not restate obvious mechanics.
- Inline comments are only for non-obvious behavior, invariants, edge cases, or external constraints.

## Logging, Errors, and Observability

- Observability is mandatory.
- Use the logging system for runtime diagnostics; diagnostics must be controllable through logging configuration.
- Do not use `print` for runtime diagnostics.
- Use structured, actionable logging with context identifiers where relevant.
- Include enough context to diagnose failures quickly, such as operation, model path, model hash, model ID, metadata provider, cache path, ComfyUI request or prompt ID, and SugarSubstitute endpoint.
- Use log levels consistently (`debug`, `info`, `warning`, `error`).
- Preserve exception context and stack traces for unexpected failures.
- Bare `except:` is not allowed.
- `except Exception` must be narrow, intentional, and log context plus failure reason.
- Silent exception swallowing is not allowed.

## TypeScript and Web Policy

- Web code must use TypeScript as the source language.
- If TypeScript code is added, update this file in the same change so TypeScript guidance is direct and explicit rather than conditional.
- TypeScript type checking must use `tsc --noEmit`.
- TypeScript linting must use ESLint flat config with `typescript-eslint` strict type-aware rules.
- TypeScript formatting must use Prettier.
- TypeScript tests must use Vitest.
- Browser or DOM-facing TypeScript tests must use a Vitest browser-like environment such as `jsdom` unless a real-browser test is required.
- Keep browser/UI code thin; backend contracts should be typed and owned by the backend/application boundary.
- Import ComfyUI frontend modules via established ComfyUI absolute paths such as `/scripts/app.js` when applicable.
- Never render dynamic data with `innerHTML`, `outerHTML`, or `insertAdjacentHTML`.
- Build DOM with safe APIs such as `document.createElement`, `textContent`, `replaceChildren`, and explicit attribute assignment.
- Treat model metadata, API responses, SugarSubstitute payloads, query state, filenames, and workflow content as untrusted for DOM rendering.

## Versioning and Commit Messages

- Use semantic-release style versioning with Node `semantic-release`.
- Release automation uses the Angular commit analyzer preset and `v{version}` Git tags.
- Keep the runtime package version in `substitute_backend.__version__`.
- Keep the Comfy Registry package version in `pyproject.toml`.
- Keep the release automation package version in `package.json`.
- Keep release notes in `CHANGELOG.md`.
- Publish version bumps to the Comfy Registry through the GitHub release workflow after semantic-release creates a release.
- Only commit when explicitly asked.
- When asked to commit, use the Conventional Commits standard so release automation can infer version impact.
- Commit format: `type(scope): subject`.
- Use `feat` for user-facing features that should produce a minor bump.
- Use `fix` for bug fixes that should produce a patch bump.
- Use `docs`, `style`, `refactor`, `perf`, `test`, or `chore` for non-feature/non-fix changes.
- Mark breaking changes with `!`, such as `feat(api)!: change catalog response shape`, to produce a major bump.

## Repository Verification

- Run Python tooling from the ComfyUI virtual environment at `..\..\venv` relative to this repository root.
- Install Python development tools for this repository into that ComfyUI virtual environment with `..\..\venv\Scripts\python.exe -m pip install -e ".[dev]"` when they are missing.
- Do not create a separate repository-local virtual environment for normal verification.
- Do not run Python gates with global or system Python.
- Prefer `..\..\venv\Scripts\python.exe -m ...` command forms so the selected environment is explicit.
- Provide repository-local gates for formatting, linting, typing, and tests.
- Copyright headers must be maintained with `..\..\venv\Scripts\python.exe tools\add_license_headers.py`.
- Python formatting must use Ruff format: `..\..\venv\Scripts\python.exe -m ruff format .`
- Python linting must use Ruff check: `..\..\venv\Scripts\python.exe -m ruff check .`
- Python type checking must use mypy in strict mode with explicit package bases: `..\..\venv\Scripts\python.exe -m mypy --strict --explicit-package-bases substitute_backend tests tools`
- Python tests must use pytest: `..\..\venv\Scripts\python.exe -m pytest -q`
- Run full test suites in parallel with pytest-xdist: `..\..\venv\Scripts\python.exe -m pytest -n auto -q`
- Run the full formatting, linting, typing, and test gates before reporting completion.
- Failing tests, lint failures, formatting failures, and type-check failures are blocking.
- When TypeScript is present, define a single repository check command that runs `tsc --noEmit`, ESLint, Prettier check, and Vitest.
