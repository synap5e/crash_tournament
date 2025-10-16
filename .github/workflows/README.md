# GitHub Actions Workflows

This directory contains GitHub Actions workflows for the crash-tournament project.

## Workflows

### `test.yml`
- **Purpose**: Run tests across multiple Python versions
- **Triggers**: Push to main/develop branches, pull requests to main/develop
- **Python versions**: 3.10, 3.11, 3.12
- **Steps**:
  1. Checkout code
  2. Set up Python
  3. Install uv package manager
  4. Install project dependencies (including dev dependencies)
  5. Run pytest with verbose output

### `ci.yml`
- **Purpose**: Full CI pipeline including tests and linting
- **Triggers**: Push to main/develop branches, pull requests to main/develop
- **Python versions**: 3.10, 3.11, 3.12
- **Steps**:
  1. Checkout code
  2. Set up Python
  3. Install uv package manager
  4. Install project dependencies (including dev dependencies)
  5. Run tests
  6. Run code formatting checks (black, isort)
  7. Run type checking (mypy)

## Dependencies

The project uses `uv` for dependency management. The workflows install:
- Core dependencies from `pyproject.toml`
- Development dependencies from `pyproject.toml` optional dependencies

## Test Configuration

Tests are run using pytest with the following configuration:
- Verbose output (`-v`)
- Short traceback format (`--tb=short`)
- All test files in the `tests/` directory

## Local Development

To run the same commands locally:

```bash
# Install dependencies
uv sync --extra dev

# Run tests
uv run pytest tests/ -v --tb=short

# Run linting
uv run black --check .
uv run isort --check-only .
uv run mypy crash_tournament/
```
