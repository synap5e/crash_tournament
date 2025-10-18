# Crash Tournament

## Purpose

This system ranks large sets of crash reports (hundreds to thousands) by likely exploitability. Instead of evaluating each crash individually, it compares small groups of crashes (typically 4 at a time) to build a global ranking using the TrueSkill algorithm.

## Approach

We use TrueSkill for ranking with a key adaptation: while TrueSkill is designed for pairwise comparisons, we perform k-way ordinal comparisons (typically 4 crashes at a time) and convert them to sequential pairwise TrueSkill updates. A configurable Judge (typically an LLM-based agent like `cursor-agent`) ranks small groups of crashes, and these ordinal results are decomposed into k-1 pairwise comparisons that update TrueSkill ratings (mu/sigma per crash).

**Efficiency tradeoff**: One k-way evaluation produces multiple pairwise updates simultaneously. While each derived pairwise update carries (hopefully only slightly) less reliable information than an independent 2-way call, the total information gained per LLM call may exceed that of an individual pairwise evaluation (3 noisier pairwise comparisons vs 1 lower-noise 2-way comparison). Standard TrueSkill treats each pairwise evaluation as the cost unit. In our setting, the expensive resource is the LLM call; k-way judging reduces the number of costly calls while still providing pairwise-equivalent updates for TrueSkill to converge. Even if convergence requires more pairwise updates (due to lower quality pairwise judgments), it should require fewer LLM calls.

This trades some theoretical rigor (treating correlated k-way outcomes as independent pairwise updates) for efficiency by assuming transitivity and consistent judge accuracy.

For k=2, this reduces to standard TrueSkill with a single pairwise comparison per evaluation.

## Usage

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

### Testing judges

Compare crashes using the demo script:

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

## Architecture

The system uses dependency injection to wire together swappable components:


See [Architecture Documentation](docs/architecture.md) for detailed interface specifications.

### Data Flow

**Flow:**
1. [Orchestrator](docs/architecture.md#orchestrator) gets crash IDs from [CrashFetcher](docs/architecture.md#crashfetcher)
2. [Selector](docs/architecture.md#selector) generates matchups (currently random, future: uncertainty-based)
3. [Orchestrator](docs/architecture.md#orchestrator) calls [Judge](docs/architecture.md#judge) (in thread pool) to rank each group
4. [Judge](docs/architecture.md#judge) results persisted via [Storage](docs/architecture.md#storage) and fed to [Ranker](docs/architecture.md#ranker)
5. [Ranker](docs/architecture.md#ranker) updates TrueSkill ratings (μ/σ) using k-way→pairwise conversion
6. Repeat until budget exhausted or convergence
7. [Storage](docs/architecture.md#storage) enables snapshot/resume functionality

## Selection Strategy

Matchups are generated continuously until budget exhausted.

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

See [Architecture Documentation](docs/architecture.md#data-models) for detailed data model specifications.

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

See [Testing Documentation](docs/testing.md) for test commands and coverage details.

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

## Documentation

- [Architecture](docs/architecture.md) - Core interfaces and component specifications
- [Testing](docs/testing.md) - Test commands and coverage details  
- [Future Research](docs/future-research.md) - Research directions and optimization opportunities


