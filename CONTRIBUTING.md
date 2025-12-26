# Contributing

## Project Structure

```
er-fog-tracker/
├── web/                    # Frontend (vanilla JS + D3.js)
├── server/                 # Backend (Python FastAPI)
├── mod/                    # In-game mod (Rust DLL)
├── analysis/               # CLI analysis scripts
└── docs/                   # Architecture documentation
```

## Development Setup

### Server (Python)

```bash
cd server
python3 -m venv venv
source venv/bin/activate
pip install -e ".[dev]"
cp .env.example .env
alembic upgrade head
uvicorn fogtracker.main:app --reload --port 8001
```

### Mod (Rust)

```bash
cd mod
cargo build --release
```

## Code Quality

### Pre-commit Hooks

Pre-commit hooks are configured for linting and formatting:

```bash
# Install hooks (first time)
pre-commit install

# Run manually on all files
pre-commit run --all-files
```

**Configured hooks:**
- `ruff` - Python linting
- `ruff-format` - Python formatting
- `eslint` / `prettier` - JavaScript
- `rustfmt` - Rust

## Testing

### Server Tests

The server uses pytest for testing. Tests are organized as follows:

```
server/tests/
├── conftest.py              # Shared fixtures
├── fixtures/                # Test data
│   ├── *.json               # Zone pair fixtures
│   └── spoiler_logs/        # Spoiler log fixtures
├── unit/                    # Unit tests (fast, no external deps)
│   ├── test_zone_matching.py
│   └── test_spoiler_parser.py
└── integration/             # Integration tests (require running server)
    └── test_server_integration.py
```

### Running Tests

```bash
cd server
source venv/bin/activate

# Run all unit tests
pytest

# Run with verbose output
pytest -v

# Run specific test file
pytest tests/unit/test_zone_matching.py

# Run specific test class
pytest tests/unit/test_zone_matching.py::TestNamesMatch

# Run specific test
pytest tests/unit/test_zone_matching.py::TestNamesMatch::test_exact_match

# Run with coverage
pytest --cov=fogtracker --cov-report=term-missing tests/unit

# Run integration tests (requires server on localhost:8001)
pytest --run-integration
```

### Writing Tests

**Unit tests** should:
- Test pure functions without external dependencies
- Use fixtures from `conftest.py`
- Be fast (< 1s per test)

**Example:**

```python
from fogtracker.zone_matching import names_match

class TestNamesMatch:
    def test_exact_match(self):
        assert names_match("Limgrave", "Limgrave")

    def test_normalized_match(self):
        assert names_match("Limgrave (detail)", "Limgrave")
```

**Available fixtures:**
- `zone_pairs_small` - Real zone pairs (~100 links)
- `zone_pairs_large` - Real zone pairs (~150 links)
- `simple_zone_pairs` - Hand-crafted minimal data
- `spoiler_log_1078869800` - Real spoiler log text
- `spoiler_log_1851144969` - Real spoiler log text

### CI/CD

Tests run automatically on push/PR via GitHub Actions when `server/` files are modified.

## Database Migrations

```bash
cd server

# Create a new migration
alembic revision -m "description"

# Apply migrations
alembic upgrade head

# Rollback one migration
alembic downgrade -1
```

## Documentation

- `docs/ARCHITECTURE.md` - System overview
- `docs/PROTOCOL.md` - REST API and WebSocket protocol
- `docs/MOD_INTERNALS.md` - Mod memory reading
- `docs/GRAPH_MODEL.md` - Zone links and discovery logic

## Commit Messages

Follow conventional commits:

```
feat: add new feature
fix: fix a bug
test: add or update tests
docs: update documentation
refactor: code refactoring
chore: maintenance tasks
```

## Pull Requests

1. Create a feature branch
2. Make changes with tests
3. Ensure `pre-commit run --all-files` passes
4. Ensure `pytest` passes
5. Submit PR with clear description
