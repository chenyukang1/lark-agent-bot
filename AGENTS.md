# Repository Guidelines

## Project Structure & Module Organization

- `main.py` starts the application through `app/bootstrap.py`.
- `app/agents/` contains DevOps agents, subagents, and DDL analysis.
- `app/tools/` provides Git, Jenkins, and build-log utilities.
- `app/lark/` contains Feishu clients, event handlers, cards, and user resolution.
- `app/webhook/` exposes FastAPI endpoints for Jenkins callbacks.
- `app/config.py` manages application and codebase configuration.
- `tests/` contains automated tests organized by subsystem; `docs/` contains documentation assets.

Keep external service integrations separate from agent orchestration and webhook handling.

## Build, Test, and Development Commands

Use Python 3.14+ and `uv`.

- `uv sync`: install dependencies from the project configuration and lockfile.
- `./bootstrap.sh`: install dependencies, create missing local configuration files from examples, and start the application once configured.
- `uv run main.py`: run the bot and background webhook server.
- `uv run python -m unittest discover -v`: run the complete test suite.
- `uv run python -m unittest tests.webhook.test_app -v`: run targeted webhook tests.
- `docker compose up --build`: build and start the containerized service.

## Coding Style & Naming Conventions

Use four-space indentation, `snake_case` for functions and modules, and `PascalCase` for classes. Follow surrounding import and formatting conventions. Add type annotations to public interfaces and use Pydantic models for validated payloads.

Keep blocking Git, Jenkins, and Feishu operations off asynchronous event loops. No formatter or linter is currently configured; avoid unrelated formatting changes.

## Testing Guidelines

Tests use standard-library `unittest`, including `IsolatedAsyncioTestCase`, `unittest.mock`, and FastAPI `TestClient`. Name files `test_*.py` and methods `test_*`.

Mock external services rather than contacting live Jenkins, Feishu, or model APIs. Cover routing, validation, failure handling, and duplicate callbacks when changing these behaviors. No coverage threshold is configured. Report existing failures separately from regressions.

## Commit & Pull Request Guidelines

Recent commits use prefixes such as `feat:` and `fix:` followed by concise descriptions. Keep commits focused.

PRs should explain the problem, resulting behavior, configuration changes, and validation performed. Link relevant issues; include screenshots when changing visible cards.

## Security & Configuration

Use `.env.example`, `codebase_configs.example.json`, and `user_mapping.example.json` as templates. Never commit credentials, local mappings, or runtime logs. Avoid logging tokens or secrets.
