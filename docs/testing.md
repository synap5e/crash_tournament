# Testing

```bash
# Run all tests
uv run python -m pytest tests/ -v

# Run specific test suites
uv run python -m pytest tests/test_trueskill_ranker.py -v
uv run python -m pytest tests/test_random_selector.py -v
uv run python -m pytest tests/test_integration.py -v
```

Test coverage:
- ✓ Unit tests: TrueSkill ranker, random selector, JSONL storage
- ✓ Integration tests: End-to-end tournament, snapshot resume
