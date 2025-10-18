# Crash Tournament

A TrueSkill-based ranking system for crash reports using comparative judging. Ranks crashes by exploitability with minimal LLM calls through comparative judging.

## Purpose

This system ranks large sets of crash reports (hundreds to thousands) by likely exploitability. Instead of evaluating each crash individually, it compares small groups of crashes (typically 4 at a time) to build a global ranking using the TrueSkill algorithm. The system performs k-way comparisons but converts them to pairwise TrueSkill updates, trading theoretical rigor for efficiency by assuming transitivity and consistent judge accuracy.

## Approach

We use TrueSkill for ranking, but with an important adaptation: while TrueSkill is designed for pairwise comparisons, we perform k-way ordinal comparisons (typically 4 crashes at a time) and convert them to sequential pairwise TrueSkill updates. A configurable Judge (typically an LLM-based agent like `cursor-agent`) ranks small groups of crashes, and these ordinal results are decomposed into k-1 pairwise comparisons that update TrueSkill ratings (mu/sigma per crash). 

**k-way judging**: Instead of evaluating crashes strictly pairwise, we present a group of k crashes to the judge and rank them all at once. To update TrueSkill, we naively convert the k-way ranking into k-1 sequential pairwise updates. This sacrifices some theoretical rigor (converting a k-way ranking into sequential pairwise updates treats correlated outcomes as independent), which can introduce noise and reduce the probabilistic fidelity of the TrueSkill updates.

The efficiency gain comes from an information-per-call tradeoff: one k-way evaluation produces multiple pairwise updates simultaneously. While each derived pairwise update carries (hopefully only slightly) less reliable information than an independent 2-way call, the total information gained per LLM call may exceed that of an individual pairwise evaluation. Standard TrueSkill treats each pairwise evaluation as the cost unit. In our setting, the expensive resource is the LLM call; k-way judging reduces the number of costly calls while still providing pairwise-equivalent updates for TrueSkill to converge. Even if convergence requires more pairwise updates (due to lower quality pairwise judmgenets to k=2), it should require fewer LLM calls.

For k=2, this reduces to standard TrueSkill with a single pairwise comparison per evaluation.

## Usage

### Quick Start

Rank crashes using the demo script:

```bash
# With cursor-agent judge
uv run python -m crash_tournament.rank_crashes_demo \
    --judge cursor_agent \
    crash1.json crash2.json crash3.json crash4.json

# With simulated judge (for testing)
uv run python -m crash_tournament.rank_crashes_demo \
    --judge sim \
    crash1.json crash2.json crash3.json

# With custom prompt
uv run python -m crash_tournament.rank_crashes_demo \
    --judge cursor_agent \
    --prompt my_prompt.md \
    crash*.json
```

### Full Tournament

Run a complete tournament with the orchestrator:

```bash
uv run python -m crash_tournament \
    --crashes-dir ./crashes \
    --output-dir ./output \
    --judge-type cursor-agent

# Use custom pattern for different file types
uv run python -m crash_tournament \
    --crashes-dir ./crashes \
    --crashes-pattern "crash.json" \
    --output-dir ./output \
    --judge-type simulated

# Use different worker counts for parallel execution
uv run python -m crash_tournament \
    --crashes-dir ./crashes \
    --output-dir ./output \
    --judge-type cursor-agent \
    --workers 4  # Parallel execution with 4 workers

uv run python -m crash_tournament \
    --crashes-dir ./crashes \
    --output-dir ./output \
    --judge-type cursor-agent \
    --workers 1  # Sequential execution (default)
```

### Options

- `--crashes-dir`: Path to crash corpus directory (required)
- `--crashes-pattern`: Pattern for finding crash files (default: `*.json`)
- `--output-dir`: Directory for JSONL/snapshots output (required)
- `--judge-type`: Judge type (`simulated`, `dummy`, `cursor-agent`, `cursor-agent-streaming`)
- `--matchup-size`: Number of crashes per matchup (default: 4, must be between 2 and 7)
- `--budget`: Total number of matchup evaluations (default: matchup_size * 250)
- `--snapshot-every`: Save snapshot every N matchups (default: 10)
- `--workers`: Number of worker threads (default: 1)

## Architecture

The system uses dependency injection to wire together swappable components:

**Note:** The system automatically loads snapshots if they exist, so no manual `--resume` flag is needed.

### Core Interfaces

`CrashFetcher` — Abstract interface for crash data sources (not limited to files)
- `list_crashes() -> Iterable[Crash]`: Returns all crashes
- `get_crash(crash_id) -> Crash`: Fetch specific crash
- Implementations:
  - `DirectoryCrashFetcher`: Scans directory for crash files, extracts crash_id from parent directory name

`Judge` — Compares a group of crashes and returns ranked order
- `evaluate_matchup(crashes: Sequence[Crash]) -> OrdinalResult`: Returns ordered crash IDs
- Implementations:
  - `CursorAgentJudge`: Wraps `cursor-agent` CLI (blocking, single JSON response)
    - Expected JSON schema: `{"ranked_ids": ["crash_1", "crash_2", ...], "rationale": "...", ...}`
    - Parser extracts `ranked_ids` for `OrdinalResult.ordered_ids`, stores full JSON in `parsed_result`
  - `CursorAgentStreamingJudge`: Streaming JSONL variant (--output-format=stream-json)
  - `SimulatedJudge`: Synthetic judge with configurable noise for testing
  - `DummyJudge`: Deterministic/random responses for testing

`Storage` — Persists observations and system snapshots
- `persist_matchup_result(res: OrdinalResult)`: Append observation
- `load_observations() -> Iterable[OrdinalResult]`: Load all observations
- `save_snapshot(state: dict)`: Save system state (idempotent)
- `load_snapshot() -> Optional[dict]`: Restore state
- Implementations:
  - `JSONLStorage`: JSONL for observations, JSON for snapshots
- Reproducibility: Each observation includes `timestamp` and `raw_output`; no deduplication (groups may be re-evaluated)

`Ranker` — Maintains TrueSkill ratings and statistics
- `update_with_ordinal(res: OrdinalResult, weight: float)`: Update ratings from comparison
- `get_score(crash_id) -> float`: Get mu (skill estimate)
- `get_uncertainty(crash_id) -> float`: Get sigma (uncertainty)
- `get_total_eval_count(crash_id) -> int`: Total evaluation count
- `get_win_percentage(crash_id) -> float`: Win rate across all matches
- `get_average_ranking(crash_id) -> float`: Average position in evaluated groups
- `snapshot() -> dict` / `load_snapshot(state: dict)`: Serialize/deserialize state
- Implementation: `TrueSkillRanker` (k-way → k-1 pairwise conversions, configurable weight parameter, default 1/(k-1))


`Selector` — Decides which crash groups to evaluate next
- `select_matchup(all_crash_ids: Sequence[str], matchup_size: int) -> Sequence[str] | None`: Generate single matchup
- Current implementation: `RandomSelector` (random matchup selection)

`Orchestrator` — Main control loop
- Wires all components via dependency injection
- Generates matchups continuously
- Manages thread pool for concurrent judge calls
- Thread safety: Ranker updates and Storage writes are serialized; only Judge.evaluate_matchup calls run in parallel
- Handles snapshotting and restart logic
- Enforces budget and stopping conditions

### Data Flow

```
┌─────────────────┐    ┌─────────────────┐    ┌─────────────────┐
│   CrashFetcher  │───▶│   Orchestrator  │───▶│    Selector     │
│                 │    │                 │    │                 │
│ • DirectoryScan │    │ • Main Loop     │    │ • RandomSelect  │
│ • Load Crashes  │    │ • Thread Pool   │    │ • Future:       │
│                 │    │ • Budget Mgmt   │    │   Uncertainty   │
└─────────────────┘    └─────────────────┘    └─────────────────┘
                                │                       │
                                ▼                       ▼
                       ┌─────────────────┐    ┌─────────────────┐
                       │     Ranker      │◀───│     Storage     │
                       │                 │    │                 │
                       │ • TrueSkill     │    │ • JSONL Obs     │
                       │ • k-way→pairwise│    │ • JSON Snapshots│
                       │ • μ/σ tracking  │    │ • Resume State  │
                       └─────────────────┘    └─────────────────┘
                                ▲                       ▲
                                │                       │
                       ┌─────────────────┐              │
                       │      Judge      │──────────────┘
                       │                 │
                       │ • cursor-agent  │
                       │ • Simulated     │
                       │ • Streaming     │
                       └─────────────────┘
```

**Flow:**
1. **Orchestrator** gets crash IDs from **CrashFetcher**
2. **Selector** generates matchups (currently random, future: uncertainty-based)
3. **Orchestrator** calls **Judge** (in thread pool) to rank each group
4. **Judge** results persisted via **Storage** and fed to **Ranker**
5. **Ranker** updates TrueSkill ratings (μ/σ) using k-way→pairwise conversion
6. Repeat until budget exhausted or convergence
7. **Storage** enables snapshot/resume functionality

## Selection Strategy

Matchups are generated continuously until budget exhausted. (Current implementation: RandomSelector)

### In-Flight Crash Tracking

The orchestrator prevents the same crash from being evaluated in multiple concurrent matchups. Before generating a new matchup, crashes currently being judged are filtered out of the available pool. This ensures:

- No crash appears in multiple simultaneous evaluations
- Each evaluation's results can update the crash's rating before it's selected again

This design trades some parallelism (workers may idle when few crashes are available) for more efficient information gathering from each evaluation.

## Orchestrator Control Flow

The orchestrator submits matchups to worker threads incrementally as workers become available, processing results as they complete. Runs until budget exhausted.

Key CLI arguments:
- `--budget`: Total evaluations (default: auto-computed)
- `--snapshot-every`: Save snapshot every N matchups (default: 10)
- `--matchup-size`: Crashes per matchup (default: 4, minimum 2)
- `--workers`: Number of worker threads (default: 1)
- `--judge-type`: Judge implementation (default: simulated)

Note: If fewer crashes are available than `k`, the system uses all available crashes (effectively reducing group size). For meaningful tournaments, ensure you have significantly more crashes than `k`.

### Key Design Decisions

- Crashes as black boxes: The tournament system treats crashes as file paths without parsing content. Judges read file content directly as needed.
- Synchronous interfaces: All components use synchronous methods. Concurrency is handled by the orchestrator's thread pool.
- TrueSkill adaptation: k-way comparisons are converted to k-1 pairwise TrueSkill updates with weight=1/(k-1) to avoid overconfidence. This trades theoretical rigor for efficiency by assuming transitivity and consistent judge accuracy across k-way comparisons.
- Idempotency: System can resume from snapshots without re-evaluating groups.
- Pluggable components: All interfaces are abstract; swap implementations without changing orchestrator logic.

## Multithreaded Architecture

The orchestrator uses `ThreadPoolExecutor` to parallelize judge evaluations while keeping state updates thread-safe.

### Threading Model

What runs in parallel:
- Judge evaluations (`judge.evaluate_matchup()`) run concurrently in worker threads
- Each worker handles one group at a time, reading crash files and invoking the judge
- With judges taking 1+ minutes per evaluation, workers do the heavy lifting

What runs sequentially:
- Result processing (storage writes, ranker updates) happens in the main thread
- Failure tracking and abort checks run serially after each evaluation completes
- Snapshots are saved periodically, never during parallel execution

How it works:
1. Main thread submits matchups incrementally to the thread pool
2. Workers execute judge calls concurrently (1+ minute each)
3. Main thread blocks waiting for next result using `as_completed()` 
4. When a worker finishes, main thread wakes up, processes that result (~milliseconds)
5. Result is persisted to storage and updates the ranker
6. Main thread blocks again waiting for next completion
7. After all evaluations complete, a snapshot is saved

Performance: With `--workers 4` and 1-minute judge calls, workers spend ~4 minutes of wall-clock time evaluating while main thread spends most time blocked waiting, briefly waking to process each result. Parallelism significantly reduces total runtime (4 groups in ~1 minute instead of ~4 minutes sequential).

Thread safety: Workers are read-only (only read crash files), while all writes (storage, ranker, counters) happen serially in the main thread. No locks needed because only one thread writes.

### Exception Handling

When a worker fails:
- Exception is captured and logged by the main thread when it retrieves that result
- Failed evaluation is skipped (not persisted, doesn't update ranker)
- Failure counters are incremented
- Abort conditions are checked (100% of first 4, or >20% after 50 calls)
- If abort triggered: remaining work is cancelled and tournament stops
- If below threshold: tournament continues with remaining evaluations

Multiple simultaneous failures:
- Main thread processes failures one-by-one as they complete
- First failure to exceed threshold triggers abort
- In-flight workers may complete but results are discarded

### Shutdown

Normal completion: All work finishes, snapshot saved with final state

Abort (threshold exceeded): Tournament stops immediately, thread pool shuts down, last snapshot reflects pre-abort state

Ctrl-C: `KeyboardInterrupt` triggers clean shutdown, snapshot reflects last completed matchups

### Configuration

Set `--workers` based on your judge type: use 1 for sequential execution (default, safest), or higher values (2-8) for parallel execution with fast judges.

## Data Models

`Crash` — Black-box crash representation
- `crash_id: str` — Unique identifier (current fetcher extracts from parent directory name)
- `file_path: str` — Path to crash file (judge reads this)
- `timestamp: float` — Creation time

`OrdinalResult` — Judge evaluation output
- `ordered_ids: List[str]` — Crash IDs ranked most→least exploitable
- `raw_output: str` — Raw judge output for audit
- `parsed_result: dict` — Structured data from judge
- `timestamp: float` — Evaluation time
- `judge_id: str` — Judge identifier

## Directory Structure

```
crash_tournament/
├── crash_tournament/
│   ├── __main__.py              # CLI entry point for full tournament
│   ├── models.py                # Data models: Crash, OrdinalResult
│   ├── interfaces.py            # Abstract base classes for all components
│   ├── orchestrator.py          # Main control loop
│   ├── rank_crashes_demo.py    # Simple demo script for quick testing
│   ├── fetchers/
│   │   └── directory_fetcher.py # Scans directory for crash files
│   ├── judges/
│   │   ├── cursor_agent_judge.py          # Wraps cursor-agent CLI
│   │   ├── cursor_agent_streaming_judge.py # Streaming JSONL variant
│   │   └── sim_judge.py                    # Simulated judge for testing
│   ├── rankers/
│   │   └── trueskill_ranker.py  # TrueSkill with k-way→pairwise conversion
│   ├── group_selectors/
│   │   └── random_selector.py # Random matchup selection
│   ├── storage/
│   │   └── jsonl_storage.py     # JSONL observations + JSON snapshots
│   └── prompts/
│       └── ordinal_judge.md     # Default prompt template
└── tests/                       # Unit and integration tests
```

## Testing

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

## Ranked Directory and Symlinks

The system creates a `ranked/` directory in the output folder containing symbolic links to crash files, ordered by exploitability ranking. This provides easy access to the most exploitable crashes without parsing JSON files.

When created:
- At tournament completion: Final ranked directory created with all crashes

Symlink format:
```
output/ranked/
├── 1_crash_001 -> /path/to/crash_001.json
├── 2_crash_045 -> /path/to/crash_045.json
├── 3_crash_123 -> /path/to/crash_123.json
└── ...
```

Symlink naming: `{rank}_{crash_id}` where rank is 1-based position in final ranking

Usage:
```bash
# View top 5 most exploitable crashes
ls -la output/ranked/ | head -6

# Open the #1 ranked crash
cat output/ranked/1_*

# Find crashes by rank range
ls output/ranked/ | grep "^[1-5]_"
```

Directory lifecycle:
- Cleared and recreated at each milestone/update
- Contains absolute symlinks to original crash files
- Preserves original file structure and naming

## Snapshot and Resume

Snapshots enable flexible resume scenarios without re-evaluating completed groups. The system automatically loads snapshots on startup and continues from where it left off.

Resume scenarios:
- **Ctrl-C interruption:** Resume from last completed matchups
- **System failure:** Resume from last snapshot
- **Budget extension:** Continue with larger budget after previous completion
- **Parameter changes:** Resume with different judge/workers while preserving rankings
  - ⚠️ Warning: Changing judge type or parameters mid-tournament destabilizes TrueSkill ratings and may produce inconsistent rankings

Idempotency: Identical final rankings whether run continuously or after restart (for deterministic judges).

## Error Handling and Limitations

Judge Error Tolerance:
The orchestrator tolerates judge failures with specific abort thresholds:
- **Early abort**: 100% of first 4 evaluations fail → judge is broken, abort immediately
- **Late abort**: >20% failure rate after 50+ evaluations → systematic issues, abort
- **Tolerance**: <20% failure rate is acceptable and tournament continues

This applies to all judge types (LLM-based, simulated, dummy, etc.).

## Dependencies

- Python 3.10+
- Package management via `uv`

```bash
uv sync  # Install all dependencies
```

## Future Research Directions (Not Yet Implemented)

### Grouping Strategy Optimization

The current system uses **random selection** for matchup generation. This provides a solid baseline, but there are several areas for potential improvement:

#### **Investigation Areas**

1. **Similar-Skill Grouping (delta_mu)**
   - **Hypothesis**: Grouping crashes with similar skill levels (μ values) may produce more informative comparisons
   - **Current Implementation**: Uses random selection for all matchups
   - **Proposed Change**: Add `delta_mu` parameter to group crashes within score threshold (|μ₁ - μ₂| ≤ delta_mu)
   - **Metrics**: Compare convergence speed and ranking quality vs random grouping
   - **Rationale for current approach**: Random grouping is simpler and provides good exploration; unclear if nearby-μ grouping provides significant benefits

2. **Uncertainty-Based Grouping**
   - **Hypothesis**: Grouping high-uncertainty crashes together may be more informative than mixing with random crashes
   - **Implementation**: Select groups of highest-σ crashes for direct uncertainty resolution
   - **Metrics**: Measure uncertainty reduction per evaluation

3. **Adaptive Grouping Strategies**
   - **Hypothesis**: Different grouping strategies may be optimal at different tournament phases
   - **Implementation**: Use random grouping early, uncertainty-based grouping late
   - **Metrics**: Track convergence curves for different strategies

4. **Balanced Grouping**
   - **Hypothesis**: Mixing high-uncertainty with medium-uncertainty crashes may provide better information gain
   - **Implementation**: Weighted selection combining uncertainty and diversity
   - **Metrics**: Information-theoretic measures of comparison value

#### **Research Methodology**

To investigate these approaches:

1. **A/B Testing**: Run tournaments with different grouping strategies on identical crash sets
2. **Convergence Analysis**: Measure ranking quality vs evaluation count
3. **Information Gain**: Quantify the informativeness of different comparison types
4. **Statistical Significance**: Use proper statistical tests to validate improvements

#### **Implementation Strategy**

- **Experimental Branch**: Implement new strategies in feature branches
- **Metrics Collection**: Add detailed logging of grouping decisions and outcomes
- **Benchmarking**: Use standardized crash sets for consistent comparison
- **Gradual Rollout**: Test on small tournaments before large-scale deployment

**Note**: Any new grouping strategies should demonstrate statistically significant improvements in convergence speed or ranking quality before being merged to master.

### Uncertainty-Based Stopping Conditions

Currently, tournaments run until budget is exhausted. An alternative approach would be to stop when uncertainty converges below a threshold.

**Potential Implementation:**
- Add `--uncertainty-threshold` CLI parameter
- Check average uncertainty in `_check_stopping_conditions()`
- Stop when `avg_uncertainty < threshold`

**Research Questions:**
- What threshold value indicates sufficient convergence?
- Should we use average uncertainty, max uncertainty, or top-k uncertainty?
- How does early stopping affect ranking quality vs evaluation cost?

**Trade-offs:**
- Pro: Saves evaluations when rankings have converged
- Con: May stop prematurely if uncertainty reduction is non-monotonic
- Con: Adds complexity to stopping logic

This feature was deliberately not implemented to keep the system simple and predictable. Budget-based stopping is easier to reason about and ensures consistent evaluation effort across runs.

