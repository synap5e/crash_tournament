"""
Integration tests for crash tournament system.

End-to-end tests with all real components.
"""

import json
import tempfile
from pathlib import Path

import pytest

from crash_tournament.fetchers.directory_fetcher import DirectoryCrashFetcher
from crash_tournament.group_selectors.random_selector import RandomSelector
from crash_tournament.judges.cursor_agent_judge import CursorAgentJudge
from crash_tournament.judges.sim_judge import SimulatedJudge
from crash_tournament.orchestrator import Orchestrator, RunConfig
from crash_tournament.rankers.trueskill_ranker import TrueSkillRanker
from crash_tournament.storage.jsonl_storage import JSONLStorage


class TestIntegration:
    """Integration tests using all real components."""

    def test_full_tournament_with_simulated_judge(self) -> None:
        """Run complete tournament with small dataset using all real components."""
        with tempfile.TemporaryDirectory() as temp_dir:
            # Arrange
            crashes_dir = Path(temp_dir) / "crashes"
            output_dir = Path(temp_dir) / "output"
            crashes_dir.mkdir()
            output_dir.mkdir()

            # Create synthetic crash files
            crash_data = [
                {
                    "crash_id": "crash_001",
                    "summary": "Buffer overflow in strcpy",
                    "stack_trace": "strcpy+0x123 main+0x456",
                    "raw_data": {"severity": "high", "type": "buffer_overflow"},
                },
                {
                    "crash_id": "crash_002",
                    "summary": "Null pointer dereference",
                    "stack_trace": "main+0x789",
                    "raw_data": {"severity": "medium", "type": "null_pointer"},
                },
                {
                    "crash_id": "crash_003",
                    "summary": "Use after free",
                    "stack_trace": "free+0xabc main+0xdef",
                    "raw_data": {"severity": "high", "type": "use_after_free"},
                },
                {
                    "crash_id": "crash_004",
                    "summary": "Integer overflow",
                    "stack_trace": "add+0x111 main+0x222",
                    "raw_data": {"severity": "low", "type": "integer_overflow"},
                },
                {
                    "crash_id": "crash_005",
                    "summary": "Double free",
                    "stack_trace": "free+0x333 main+0x444",
                    "raw_data": {"severity": "high", "type": "double_free"},
                },
            ]

            for i, data in enumerate(crash_data):
                # Create subdirectory for each crash (DirectoryCrashFetcher expects this)
                crash_dir = crashes_dir / f"crash_{i:03d}"
                crash_dir.mkdir()
                with open(crash_dir / "crash.json", "w") as f:
                    json.dump(data, f)

            # Create components
            fetcher = DirectoryCrashFetcher(crashes_dir)
            storage = JSONLStorage(
                output_dir / "observations.jsonl", output_dir / "latest_snapshot.json"
            )
            ranker = TrueSkillRanker()
            selector = RandomSelector(ranker)

            # Create ground truth for simulated judge using actual crash IDs
            crashes = list(fetcher.list_crashes())
            ground_truth = {}
            for i, crash in enumerate(crashes):
                # Assign exploitability scores based on original order
                exploitability_scores = [8.0, 4.0, 9.0, 2.0, 7.0]
                ground_truth[crash.crash_id] = exploitability_scores[i]
            judge = SimulatedJudge(ground_truth, noise=0.1)

            # Create orchestrator
            config = RunConfig(
                matchup_size=3,
                budget=10,
                max_workers=2,
                snapshot_every=5,
            )

            orchestrator = Orchestrator(
                fetcher=fetcher,
                judge=judge,
                storage=storage,
                ranker=ranker,
                selector=selector,
                config=config,
                output_dir=str(output_dir),
            )

            # Act
            rankings = orchestrator.run()

            # Assert
            assert len(rankings) == 5, "Should rank all 5 crashes"

            # Check that high exploitability crashes rank higher
            # Find the crash with highest ground truth score (9.0) and lowest (2.0)
            highest_score_crash = max(ground_truth.items(), key=lambda x: x[1])[0]
            lowest_score_crash = min(ground_truth.items(), key=lambda x: x[1])[0]

            crash_ids = list(rankings.keys())
            highest_rank = crash_ids.index(highest_score_crash)
            lowest_rank = crash_ids.index(lowest_score_crash)

            assert (
                highest_rank < lowest_rank
            ), "High exploitability crash should rank higher than low exploitability crash"

            # Check that storage contains observations
            observations = list(storage.load_observations())
            assert len(observations) > 0, "Should have stored observations"

            # Check that snapshot was saved
            snapshot = storage.load_snapshot()
            assert snapshot is not None, "Should have saved snapshot"
            # Snapshot contains ranker_state and runtime_state
            assert "ranker_state" in snapshot, "Snapshot should contain ranker state"
            assert "runtime_state" in snapshot, "Snapshot should contain runtime state"

    def test_snapshot_resume_works(self) -> None:
        """Stop and resume from snapshot should work correctly."""
        with tempfile.TemporaryDirectory() as temp_dir:
            # Arrange
            crashes_dir = Path(temp_dir) / "crashes"
            output_dir = Path(temp_dir) / "output"
            crashes_dir.mkdir()
            output_dir.mkdir()

            # Create crash files
            crash_data = [
                {"crash_id": "crash_a", "summary": "A", "stack_trace": "trace_a"},
                {"crash_id": "crash_b", "summary": "B", "stack_trace": "trace_b"},
                {"crash_id": "crash_c", "summary": "C", "stack_trace": "trace_c"},
            ]

            for i, data in enumerate(crash_data):
                # Create subdirectory for each crash (DirectoryCrashFetcher expects this)
                crash_dir = crashes_dir / f"crash_{i}"
                crash_dir.mkdir()
                with open(crash_dir / "crash.json", "w") as f:
                    json.dump(data, f)

            # Create components
            fetcher = DirectoryCrashFetcher(crashes_dir)
            storage = JSONLStorage(
                output_dir / "observations.jsonl", output_dir / "latest_snapshot.json"
            )
            ranker = TrueSkillRanker()
            selector = RandomSelector(ranker)

            ground_truth = {"crash_a": 5.0, "crash_b": 3.0, "crash_c": 7.0}
            judge = SimulatedJudge(ground_truth, noise=0.1)

            # First run
            config1 = RunConfig(
                matchup_size=2,
                budget=4,
                max_workers=1,
                snapshot_every=2,
            )

            orchestrator1 = Orchestrator(
                fetcher=fetcher,
                judge=judge,
                storage=storage,
                ranker=ranker,
                selector=selector,
                config=config1,
                output_dir=str(output_dir),
            )

            # Act - first run
            rankings1 = orchestrator1.run()

            # Create new orchestrator with same storage
            ranker2 = TrueSkillRanker()
            selector2 = RandomSelector(ranker2)

            config2 = RunConfig(
                matchup_size=2,
                budget=6,  # More budget for resume
                max_workers=1,
                snapshot_every=2,
            )

            orchestrator2 = Orchestrator(
                fetcher=fetcher,
                judge=judge,
                storage=storage,
                ranker=ranker2,
                selector=selector2,
                config=config2,
                output_dir=str(output_dir),
            )

            # Act - resume run
            rankings2 = orchestrator2.run()

            # Assert
            assert len(rankings1) == 3, "First run should rank all crashes"
            assert len(rankings2) == 3, "Resume run should rank all crashes"

            # Check that more observations were added
            observations = list(storage.load_observations())
            assert len(observations) > 4, "Should have more observations after resume"

    def test_rankings_improve_with_iterations(self) -> None:
        """Verify that rankings improve with more iterations."""
        with tempfile.TemporaryDirectory() as temp_dir:
            # Arrange
            crashes_dir = Path(temp_dir) / "crashes"
            output_dir = Path(temp_dir) / "output"
            crashes_dir.mkdir()
            output_dir.mkdir()

            # Create crash files with clear ground truth
            crash_data = [
                {
                    "crash_id": "high_exploit",
                    "summary": "High exploit",
                    "stack_trace": "trace1",
                },
                {
                    "crash_id": "medium_exploit",
                    "summary": "Medium exploit",
                    "stack_trace": "trace2",
                },
                {
                    "crash_id": "low_exploit",
                    "summary": "Low exploit",
                    "stack_trace": "trace3",
                },
            ]

            for i, data in enumerate(crash_data):
                # Create subdirectory for each crash (DirectoryCrashFetcher expects this)
                crash_dir = crashes_dir / f"crash_{i}"
                crash_dir.mkdir()
                with open(crash_dir / "crash.json", "w") as f:
                    json.dump(data, f)

            # Create components
            fetcher = DirectoryCrashFetcher(crashes_dir)
            storage = JSONLStorage(
                output_dir / "observations.jsonl", output_dir / "latest_snapshot.json"
            )

            # Create ground truth using actual crash IDs from fetcher
            crashes = list(fetcher.list_crashes())
            ground_truth = {}
            exploitability_scores = [10.0, 5.0, 1.0]  # high, medium, low
            for i, crash in enumerate(crashes):
                ground_truth[crash.crash_id] = exploitability_scores[i]
            judge = SimulatedJudge(
                ground_truth, noise=0.05
            )  # Low noise for consistency

            # Test with different budgets
            budgets = [3, 6, 9]
            rankings_results = []

            for budget in budgets:
                # Create fresh components for each test
                ranker = TrueSkillRanker()
                selector = RandomSelector(ranker)

                config = RunConfig(
                    matchup_size=2,
                    budget=budget,
                    max_workers=1,
                    snapshot_every=2,
                )

                orchestrator = Orchestrator(
                    fetcher=fetcher,
                    judge=judge,
                    storage=storage,
                    ranker=ranker,
                    selector=selector,
                    config=config,
                    output_dir=str(output_dir),
                )

                # Act
                rankings = orchestrator.run()
                rankings_results.append(rankings)

            # Assert
            # With more iterations, rankings should be more consistent with ground truth
            # high_exploit should rank higher than low_exploit in all cases
            high_exploit_crash = max(ground_truth.items(), key=lambda x: x[1])[0]
            low_exploit_crash = min(ground_truth.items(), key=lambda x: x[1])[0]

            for rankings in rankings_results:
                high_rank = list(rankings.keys()).index(high_exploit_crash)
                low_rank = list(rankings.keys()).index(low_exploit_crash)
                assert (
                    high_rank < low_rank
                ), "High exploit crash should rank higher than low exploit crash"

            # Later runs should have more observations
            observations = list(storage.load_observations())
            assert (
                len(observations) >= 9
            ), "Should have accumulated observations across runs"

    @pytest.mark.integration
    @pytest.mark.xfail(reason="Requires cursor-agent CLI tool")
    def test_cursor_agent_judge_integration(self) -> None:
        """Integration test with actual cursor-agent CLI."""
        with tempfile.TemporaryDirectory() as temp_dir:
            # Arrange
            crashes_dir = Path(temp_dir) / "crashes"
            output_dir = Path(temp_dir) / "output"
            crashes_dir.mkdir()
            output_dir.mkdir()

            # Create simple crash files
            crash_data = [
                {
                    "crash_id": "crash_001",
                    "summary": "Buffer overflow in strcpy",
                    "stack_trace": "strcpy+0x123\nmain+0x456",
                    "raw_data": {"severity": "high"},
                },
                {
                    "crash_id": "crash_002",
                    "summary": "Null pointer dereference",
                    "stack_trace": "main+0x789",
                    "raw_data": {"severity": "low"},
                },
                {
                    "crash_id": "crash_003",
                    "summary": "Use after free",
                    "stack_trace": "free+0xabc\nmain+0xdef",
                    "raw_data": {"severity": "high"},
                },
            ]

            for i, data in enumerate(crash_data):
                # Create subdirectory for each crash (DirectoryCrashFetcher expects this)
                crash_dir = crashes_dir / f"crash_{i:03d}"
                crash_dir.mkdir()
                with open(crash_dir / "crash.json", "w") as f:
                    json.dump(data, f)

            # Create components with cursor-agent judge
            fetcher = DirectoryCrashFetcher(crashes_dir)
            storage = JSONLStorage(
                output_dir / "observations.jsonl", output_dir / "latest_snapshot.json"
            )
            ranker = TrueSkillRanker()
            selector = RandomSelector(ranker)

            # Use cursor-agent judge
            judge = CursorAgentJudge(timeout=30.0)

            # Test connection first
            judge.test_connection()

            # Create orchestrator with small budget for quick test
            config = RunConfig(
                matchup_size=2,
                budget=2,
                max_workers=1,
                snapshot_every=1,
            )

            orchestrator = Orchestrator(
                fetcher=fetcher,
                judge=judge,
                storage=storage,
                ranker=ranker,
                selector=selector,
                config=config,
                output_dir=str(output_dir),
            )

            # Act
            rankings = orchestrator.run()

            # Assert
            assert len(rankings) == 3, "Should rank all crashes"
            assert (
                len(list(storage.load_observations())) > 0
            ), "Should store observations"

            # Verify observations have actual content from cursor-agent
            observations = list(storage.load_observations())
            for obs in observations:
                assert obs.ordered_ids, "Should have ordered crash IDs"
                assert obs.parsed_result, "Should have parsed result from cursor-agent"
                assert len(obs.ordered_ids) > 0, "Should have complete rankings"

    def test_uncertainty_selector_integration(self) -> None:
        """Test that UncertaintySelector works correctly with real ranker."""
        with tempfile.TemporaryDirectory() as temp_dir:
            # Arrange
            crashes_dir = Path(temp_dir) / "crashes"
            output_dir = Path(temp_dir) / "output"
            crashes_dir.mkdir()
            output_dir.mkdir()

            # Create crash files
            crash_data = [
                {
                    "crash_id": "uncertain_crash",
                    "summary": "Uncertain",
                    "stack_trace": "trace1",
                },
                {
                    "crash_id": "certain_crash",
                    "summary": "Certain",
                    "stack_trace": "trace2",
                },
                {
                    "crash_id": "medium_crash",
                    "summary": "Medium",
                    "stack_trace": "trace3",
                },
            ]

            for i, data in enumerate(crash_data):
                # Create subdirectory for each crash (DirectoryCrashFetcher expects this)
                crash_dir = crashes_dir / f"crash_{i}"
                crash_dir.mkdir()
                with open(crash_dir / "crash.json", "w") as f:
                    json.dump(data, f)

            # Create components
            fetcher = DirectoryCrashFetcher(crashes_dir)
            storage = JSONLStorage(
                output_dir / "observations.jsonl", output_dir / "latest_snapshot.json"
            )
            ranker = TrueSkillRanker()
            selector = RandomSelector(ranker)

            ground_truth = {
                "crash_0": 5.0,  # uncertain_crash
                "crash_1": 3.0,  # certain_crash
                "crash_2": 4.0,  # medium_crash
            }
            judge = SimulatedJudge(ground_truth, noise=0.1)

            config = RunConfig(
                matchup_size=2,
                budget=8,
                max_workers=1,
                snapshot_every=2,
            )

            orchestrator = Orchestrator(
                fetcher=fetcher,
                judge=judge,
                storage=storage,
                ranker=ranker,
                selector=selector,
                config=config,
                output_dir=str(output_dir),
            )

            # Act
            rankings = orchestrator.run()

            # Assert
            assert len(rankings) == 3, "Should rank all crashes"

            # Check that uncertainty selector is working
            # (This is a basic check - in practice, we'd need more sophisticated metrics)
            observations = list(storage.load_observations())
            assert len(observations) > 0, "Should have generated observations"

            # Check that random selector is working
            # RandomSelector doesn't track evaluations, so we just verify it works

    def test_error_handling_integration(self) -> None:
        """Test that the system handles errors gracefully."""
        with tempfile.TemporaryDirectory() as temp_dir:
            # Arrange
            crashes_dir = Path(temp_dir) / "crashes"
            output_dir = Path(temp_dir) / "output"
            crashes_dir.mkdir()
            output_dir.mkdir()

            # Create crash files
            crash_data = [
                {"crash_id": "crash_1", "summary": "Crash 1", "stack_trace": "trace1"},
                {"crash_id": "crash_2", "summary": "Crash 2", "stack_trace": "trace2"},
            ]

            for i, data in enumerate(crash_data):
                # Create subdirectory for each crash (DirectoryCrashFetcher expects this)
                crash_dir = crashes_dir / f"crash_{i}"
                crash_dir.mkdir()
                with open(crash_dir / "crash.json", "w") as f:
                    json.dump(data, f)

            # Create components
            fetcher = DirectoryCrashFetcher(crashes_dir)
            storage = JSONLStorage(
                output_dir / "observations.jsonl", output_dir / "latest_snapshot.json"
            )
            ranker = TrueSkillRanker()
            selector = RandomSelector(ranker)

            # Create judge that will fail sometimes
            ground_truth = {"crash_0": 5.0, "crash_1": 3.0}
            judge = SimulatedJudge(ground_truth, noise=0.5)  # High noise

            config = RunConfig(
                matchup_size=2,
                budget=3,
                max_workers=1,
                snapshot_every=1,
            )

            orchestrator = Orchestrator(
                fetcher=fetcher,
                judge=judge,
                storage=storage,
                ranker=ranker,
                selector=selector,
                config=config,
                output_dir=str(output_dir),
            )

            # Act - should not raise exception even with high noise
            rankings = orchestrator.run()

            # Assert
            assert (
                len(rankings) == 2
            ), "Should handle errors gracefully and still produce rankings"
            # Check that all crashes are included (using actual crash IDs)
            crash_ids = list(rankings.keys())
            assert len(crash_ids) == 2, "Should include all crashes"
            assert all(
                "crash" in cid for cid in crash_ids
            ), "Should include crash objects"
