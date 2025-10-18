# Architecture

The system uses dependency injection to wire together swappable components:

## Core Interfaces

### CrashFetcher

Abstract interface for crash data sources (not limited to files)
- `list_crashes() -> Iterable[Crash]`: Returns all crashes
- `get_crash(crash_id) -> Crash`: Fetch specific crash
- Implementations:
  - `DirectoryCrashFetcher`: Scans directory for crash files, extracts crash_id from parent directory name

### Judge

Compares a group of crashes and returns ranked order
- `evaluate_matchup(crashes: Sequence[Crash]) -> OrdinalResult`: Returns ordered crash IDs
- Implementations:
  - `CursorAgentJudge`: Wraps `cursor-agent` CLI (blocking, single JSON response)
    - Expected JSON schema: `{"ranked_ids": ["crash_1", "crash_2", ...], "rationale": "...", ...}`
    - Parser extracts `ranked_ids` for `OrdinalResult.ordered_ids`, stores full JSON in `parsed_result`
  - `CursorAgentStreamingJudge`: Streaming JSONL variant (--output-format=stream-json)
  - `SimulatedJudge`: Synthetic judge with configurable noise for testing
  - `DummyJudge`: Deterministic/random responses for testing

### Storage

Persists observations and system snapshots
- `persist_matchup_result(res: OrdinalResult)`: Append observation
- `load_observations() -> Iterable[OrdinalResult]`: Load all observations
- `save_snapshot(state: dict)`: Save system state (idempotent)
- `load_snapshot() -> Optional[dict]`: Restore state
- Implementations:
  - `JSONLStorage`: JSONL for observations, JSON for snapshots
- Reproducibility: Each observation includes `timestamp` and `raw_output`; no deduplication (groups may be re-evaluated)

### Ranker

Maintains TrueSkill ratings and statistics
- `update_with_ordinal(res: OrdinalResult, weight: float)`: Update ratings from comparison
- `get_score(crash_id) -> float`: Get mu (skill estimate)
- `get_uncertainty(crash_id) -> float`: Get sigma (uncertainty)
- `get_total_eval_count(crash_id) -> int`: Total evaluation count
- `get_win_percentage(crash_id) -> float`: Win rate across all matches
- `get_average_ranking(crash_id) -> float`: Average position in evaluated groups
- `snapshot() -> dict` / `load_snapshot(state: dict)`: Serialize/deserialize state
- Implementation: `TrueSkillRanker` (k-way → k-1 pairwise conversions, configurable weight parameter, default 1/(k-1))

### Selector

Decides which crash groups to evaluate next
- `select_matchup(all_crash_ids: Sequence[str], matchup_size: int) -> Sequence[str] | None`: Generate single matchup
- Current implementation: `RandomSelector` (random matchup selection)

### Orchestrator

Main control loop
- Wires all components via dependency injection
- Generates matchups continuously
- Manages thread pool for concurrent judge calls
- Thread safety: Ranker updates and Storage writes are serialized; only Judge.evaluate_matchup calls run in parallel
- Handles snapshotting and restart logic
- Enforces budget and stopping conditions

## Data Models

### Crash

Black-box crash representation
- `crash_id: str` — Unique identifier (current fetcher extracts from parent directory name)
- `file_path: str` — Path to crash file (judge reads this)
- `timestamp: float` — Creation time

### OrdinalResult

Judge evaluation output
- `ordered_ids: List[str]` — Crash IDs ranked most→least exploitable
- `raw_output: str` — Raw judge output for audit
- `parsed_result: dict` — Structured data from judge
- `timestamp: float` — Evaluation time
- `judge_id: str` — Judge identifier
