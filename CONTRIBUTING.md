# Contributing

Contributions are welcome.

## Setup

```bash
git clone https://github.com/andrekost/singleflight-agents.git
cd singleflight-agents
python -m pip install -e .[dev]
```

## Running tests

```bash
python -m pytest tests/ -v
```

All tests must pass before submitting a PR.

## Running the demo

```bash
python -m singleflight_agents demo
python -m singleflight_agents verify
```

## Pull requests

- One feature or fix per PR.
- Tests must pass.
- Keep the zero-dependency constraint: no new runtime dependencies in `dependencies = []`.
- Add tests for new functionality.
- Update CHANGELOG.md under an `[Unreleased]` section.

## Code style

- Type hints on all public functions.
- `from __future__ import annotations` at the top of every module.
- `dataclass(slots=True)` for data classes.
- No runtime dependencies. Optional extras (OpenAI, LangGraph) go in `[project.optional-dependencies]`.

## Reporting bugs

Open an issue with:
- What you expected to happen.
- What actually happened.
- Minimal reproduction steps.
- Python version and OS.
