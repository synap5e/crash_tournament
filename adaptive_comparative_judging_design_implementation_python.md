# crash_tournament — Implementation plan (TrueSkill + adaptive n-way, developer guide)

This document is the **developer-facing implementation plan** for the system you specified. It commits to **TrueSkill** with naive k-way → pairwise conversion, supports configurable n (1 < n < 8; default 4), uses **uncertainty-based sampling**, and provides swap‑in interfaces for judges (including a CLI agent wrapper), crash fetchers, storage (JSONL + optional SQLite), and rankers. Implement in Python 3.10+ using `dataclasses`. Keep interfaces synchronous to avoid polluting the codebase with asyncio; allow parallelism in the orchestrator through worker pools.

---

## Quick decision log (user choices)
- **Ranker**: TrueSkill with naive k-way conversion (treat k-way ordering as k-1 sequential wins).  
- **k (group size)**: configurable; default `k=4`, allow `2 <= k <= 7`.  
- **Sampling**: uncertainty-based active selection (seed random groups, then focus on high-sigma).  
- **Storage**: JSONL primary; optional SQLite via a `Storage` implementation. Keep DB coupling behind interface.  
- **Judge**: pluggable interface; target implementation for v1 wraps a CLI agent (cursor-agent or similar).  
- **Runtime**: Python 3.10+ (3.12 OK). Use `dataclasses`. Keep Judge interfaces synchronous; orchestrator will run parallel calls with a thread/process pool.

---

## Goals for v1
1. Stable, debuggable baseline: 1000 crashes, default 4‑way ordinal comparisons, TrueSkill updates.  
2. Minimal LLM calls: seed + uncertainty loop with selective repeats.  
3. Modular code so adding Plackett–Luce, graded judgments, or alternate judges is a matter of implementing interfaces and wiring DI.

---

## Architecture overview (textual)

Components (all injected into Orchestrator):
- `CrashFetcher` — enumerates / fetches Crash objects.
- `Judge` — given a list of Crash, returns an `OrdinalResult` (ordered IDs + raw output). Implementations: `CLIJudge`, `LLMJudgeOpenAI`, `SimulatedJudge`.
- `Storage` — persists results, snapshots, and logs. Implementations: `JSONLStorage`, `SQLiteStorage`.
- `Ranker` — manages TrueSkill state and exposes mu/sigma per crash. Implementation: `TrueSkillRanker`.
- `Selector` — generates groups to evaluate (sampling strategy). Implementation: `UncertaintySelector`.
- `Orchestrator` — main loop, worker pool, DI wiring, snapshotting, stopping.

Diagram (flow):
```
CrashFetcher -> Orchestrator -> Selector -> Judge -> Storage
                     |                          |
                     v                          v
                  Ranker <------------------- persisted observations
```

---

## Directory structure
```
crash_tournament/
├─ crash_tournament/__init__.py
├─ crash_tournament/models.py           # dataclasses: Crash, OrdinalResult, GradedResult
├─ crash_tournament/interfaces.py       # ABCs: CrashFetcher, Judge, Storage, Ranker, Selector
├─ crash_tournament/storage/
│  ├─ jsonl_storage.py
│  └─ sqlite_storage.py
├─ crash_tournament/judges/
│  ├─ cli_judge.py        # wraps cursor-agent or cli tool
│  ├─ openai_judge.py     # optional
│  └─ sim_judge.py        # synthetic judge for tests
├─ crash_tournament/rankers/
│  └─ trueskill_ranker.py
├─ crash_tournament/selectors/
│  └─ uncertainty_selector.py
├─ crash_tournament/orchestrator.py
├─ crash_tournament/prompt_templates.py
├─ crash_tournament/utils.py
└─ tests/
   ├─ test_ranker.py
   ├─ test_orchestrator.py
   └─ test_selector.py
```

---

## Interfaces (skeleton)
Keep these in `crash_tournament/interfaces.py`. They should be synchronous.

```python
from abc import ABC, abstractmethod
from typing import Iterable, Sequence, Optional
from .models import Crash, OrdinalResult, GradedResult

class CrashFetcher(ABC):
    @abstractmethod
    def list_crashes(self) -> Iterable[Crash]:
        pass

    @abstractmethod
    def get_crash(self, crash_id: str) -> Crash:
        pass

class Judge(ABC):
    @abstractmethod
    def evaluate_group(self, crashes: Sequence[Crash], *, grading: bool=False) -> OrdinalResult:
        """Synchronous. May block. Caller can run in a threadpool."""
        pass

class Storage(ABC):
    @abstractmethod
    def persist_ordinal(self, res: OrdinalResult) -> None:
        pass

    @abstractmethod
    def load_observations(self) -> Iterable[OrdinalResult]:
        pass

    @abstractmethod
    def save_snapshot(self, state: dict) -> None:
        pass

    @abstractmethod
    def load_snapshot(self) -> Optional[dict]:
        pass

class Ranker(ABC):
    @abstractmethod
    def update_with_ordinal(self, res: OrdinalResult, weight: float=1.0) -> None:
        pass

    @abstractmethod
    def get_score(self, crash_id: str) -> float:
        pass

    @abstractmethod
    def get_uncertainty(self, crash_id: str) -> float:
        pass

    @abstractmethod
    def snapshot(self) -> dict:
        pass

    @abstractmethod
    def load_snapshot(self, state: dict) -> None:
        pass

class Selector(ABC):
    @abstractmethod
    def next_groups(self, k: int, budget: int) -> Sequence[Sequence[str]]:
        """Return list of groups (lists of crash IDs) to evaluate next."""
        pass
```

---

## TrueSkillRanker (implementation notes)
File: `crash_tournament/rankers/trueskill_ranker.py`
- Use the `trueskill` package. Keep a `Rating(mu, sigma)` per crash.
- When processing an `OrdinalResult` for group ordered `[a,b,c,d]`, convert to `k-1` sequential pairwise wins: `a>b`, `b>c`, `c>d` and call trueskill.rate_1vs1 or `rate` with groups.
- **Weighting:** each ordinal observation should be scaled by `1/(k-1)` to avoid overconfidence from k-way to pairwise expansion. Implement `weight` parameter in update.
- Expose `get_score` → return `mu`; `get_uncertainty` → return `sigma`.
- `snapshot()` returns serializable dict of mu/sigma keyed by crash id.

Edge cases:
- If a crash is unseen, initialise to default trueskill `Rating()`.

---

## Judge — CLI agent wrapper
File: `crash_tournament/judges/cli_judge.py`
- Implement `Judge.evaluate_group(...)` by:
  1. Building a temporary prompt file (JSON) containing the crash ids + 1–2 line summaries.
  2. Invoking the `cursor-agent` or desired CLI agent with `subprocess.run`, passing prompt and requesting machine-parsable JSON output.
  3. Parse JSON output into `OrdinalResult`.
- Guarantee: `evaluate_group` returns a deterministic structure or raises an error. Caller handles retries.

Prompt template must instruct the agent to only use provided text and to return exact JSON: `{ "ordered": ["C012","C501","C742","C233"], "rationale_top": "..." }`

Failure modes:
- Agent returns non-JSON: implement robust retry with exponential backoff and a small sanitizer that extracts the first JSON block.

Security / sandboxing:
- Limit agent runtime and file I/O. Run the agent inside a controlled environment (container) where possible.

---

## Storage
Implement `JSONLStorage` first: a JSONL file for observations and a separate JSON for snapshots.
- Keep filenames configurable.
- API: append-only for observations; idempotent writes for snapshot.

`SQLiteStorage` implements same interface using a single table for observations and a kv table for snapshots.

Always write a checksum and timestamp for each persisted item.

---

## Selector: UncertaintySelector
File: `crash_tournament/selectors/uncertainty_selector.py`
Algorithm (per loop):
1. Get mu/sigma for all crashes from `Ranker`. Compute an uncertainty score: `u = sigma` or `u = sigma * f(rank_gap)`.
2. Select top `K_uncertain` candidates (configurable, default 5*k groups worth).
3. For each group to generate: sample 1 highest-uncertainty item, then fill remaining `k-1` items by sampling items whose mu is near selected item's mu (within delta), to make comparisons informative.
4. Ensure group uniqueness / limited overlap.

Config knobs: `K_uncertain`, `delta_mu`, `groups_per_round`, `max_evals_per_crash`.

---

## Orchestrator (detailed)
File: `crash_tournament/orchestrator.py`
Responsibilities:
- DI wiring of components.
- Initial seeding: create `N_seed` random groups (cover each crash 2–3 times if budget allows).
- Worker pool: use `concurrent.futures.ThreadPoolExecutor(max_workers=N)` to run `Judge.evaluate_group` concurrently. Judge is synchronous so this isolates async complexity.
- On each completed future: persist result, update ranker (with weight = 1/(k-1)).
- After group batch completes: compute new snapshot and decide next groups via `Selector`.
- Stopping conditions: budget exhausted, top-k uncertainties below threshold, or max rounds.

Important: keep orchestrator idempotent: on restart, load snapshot and observations and continue.

---

## Prompt templates
Store in `crash_tournament/prompt_templates.py`. Provide strict JSON output requirement and a short context format (ID + summary + 1-line stack trace). Example for 4-way (always request `ordered` array only):
```
You will rank the following {k} crash reports by likely exploitability.
Return JSON only: {"ordered": ["id1","id2",...], "rationale_top": "..."}
Do not include any other text.

Context:
- id: {id} summary: {summary}
... (repeat)
```

---

## Testing strategy
1. **Unit tests** for Ranker: synthetic pairwise inputs, check mu/sigma update direction.
2. **Integration tests** with `SimulatedJudge` (parameterised noise p). Verify sample-efficiency (how many calls to reach Kendall tau threshold) and that top-k precision improves with iterations.
3. **Contract tests** for Judge implementations: given a crafted prompt, agent must return valid JSON or orchestrator treats as failure.
4. **End-to-end**: small run with 100 synthetic crashes.

---

## Milestones & rough timeline (devs familiar with Python)
- **Day 0.5**: Project skeleton, interfaces, dataclasses, basic JSONL storage. (4–8 hours)
- **Day 1**: Implement `TrueSkillRanker` + unit tests. (8 hours)
- **Day 1.5**: Implement `SimulatedJudge` that samples k-way orderings from latent scores with noise parameter `p`. (4 hours)
- **Day 2**: Implement `UncertaintySelector` and orchestrator loop with ThreadPoolExecutor; hook SimulatedJudge end-to-end for pilot run with 100 crashes. (8–12 hours)
- **Day 3**: Implement `CLIJudge` wrapper; integration testing with cursor-agent mock. (8 hours)
- **Day 4**: Add JSONL persistence, snapshotting, restart logic, add SQLite backend. (8 hours)
- **Day 5**: Run 1000-crash pilot, collect metrics, tune selector knobs; write documentation. (8–16 hours)

Parallel tasks: prompt tuning, security review for CLI agent invocation, CI tests.

---

## Operational knobs & recommended defaults
- `k`: default 4. Allow override per run.
- `seed_groups`: 200 random groups (coverage ~each crash in ~0.8 groups initially). Adjust by budget.
- `groups_per_round`: 50 groups per round (concurrency adjustable).
- `max_rounds`: until budget exhausted (budget expressed in total LLM calls).
- `weight_scale`: use `1/(k-1)` when updating TrueSkill from k-way ordering.
- `repeats_threshold`: if top-N items have sigma > X, re-evaluate with additional groups.

---

## Notes on concurrency and interface cleanliness
- Keep `Judge.evaluate_group` synchronous. Internally it may launch subprocesses or use blocking network I/O.
- Orchestrator uses a thread pool to parallelise judge calls. This keeps asyncio out of the core interfaces.
- If later you want true async judges, implement an async adapter that provides a sync façade by executing `asyncio.run(...)` inside a thread; but only do this after profiling.

---

## Next steps for you (immediate)
1. Approve the directory layout and milestone timeline.  
2. Decide the CLI agent CLI contract (how to call cursor-agent: arguments, input format, timeouts). I will include the exact subprocess command in the implementation plan.  
3. Confirm default knobs (seed_groups, groups_per_round, budget). If you don't, I'll pick conservative defaults from the plan.

---

End of concrete plan. Implementations should reference this doc and follow interfaces to maintain swap‑in capability.

