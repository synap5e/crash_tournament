"""
CLI entry point for crash tournament system.

Parses arguments, validates config, and wires components.
"""

import argparse
import shutil
import sys
from pathlib import Path
from argparse import Namespace
from typing import TypedDict

from .orchestrator import Orchestrator, RunConfig
from .fetchers.directory_fetcher import DirectoryCrashFetcher
from .storage.jsonl_storage import JSONLStorage
from .rankers.trueskill_ranker import TrueSkillRanker
from .group_selectors.random_selector import RandomSelector
from .judges.sim_judge import SimulatedJudge
from .judges.dummy_judge import DummyJudge
from .judges.cursor_agent_judge import CursorAgentJudge
from .judges.cursor_agent_streaming_judge import CursorAgentStreamingJudge
from .logging_config import setup_logging, get_logger
from .interfaces import Judge, CrashFetcher


class CLIArgs(TypedDict):
    """Typed representation of parsed CLI arguments."""
    crashes_dir: str
    crashes_pattern: str
    output_dir: str
    matchup_size: int
    snapshot_every: int
    budget: int | None
    workers: int
    judge_type: str
    agent_timeout: float
    noise: float
    debug: bool
    log_level: str


def parse_args() -> Namespace:
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(
        description="Crash Tournament - Adaptive Comparative Judging System"
    )
    
    # Required arguments
    _ = parser.add_argument(
        "--crashes-dir",
        required=True,
        help="Path to crash corpus directory"
    )
    _ = parser.add_argument(
        "--crashes-pattern",
        default="*.json",
        help="Pattern for finding crash files (default: *.json)"
    )
    _ = parser.add_argument(
        "--output-dir", 
        required=True,
        help="Directory for JSONL/snapshots output"
    )
    
    # Optional arguments
    _ = parser.add_argument(
        "--matchup-size",
        type=int,
        default=4,
        help="Number of crashes per matchup (default: 4)"
    )
    _ = parser.add_argument(
        "--snapshot-every",
        type=int,
        default=10,
        help="Save snapshot every N matchups (default: 10)"
    )
    _ = parser.add_argument(
        "--budget",
        type=int,
        help="Total judge calls allowed (default: matchup_size * 250 if not specified)"
    )
    _ = parser.add_argument(
        "--workers",
        type=int,
        default=1,
        help="Number of worker threads for parallel evaluation (default: 1)"
    )
    
    # Judge selection
    _ = parser.add_argument(
        "--judge-type",
        choices=["simulated", "dummy", "cursor-agent", "cursor-agent-streaming"],
        default="simulated",
        help="Type of judge to use (default: simulated)"
    )
    _ = parser.add_argument(
        "--agent-timeout",
        type=float,
        default=300.0,
        help="Timeout for cursor-agent in seconds (default: 300)"
    )
    _ = parser.add_argument(
        "--noise",
        type=float,
        default=0.1,
        help="Noise level for simulated judge (0-1, default: 0.1)"
    )
    _ = parser.add_argument(
        "--debug",
        action="store_true",
        help="Enable debug logging"
    )
    _ = parser.add_argument(
        "--log-level",
        choices=["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"],
        default="INFO",
        help="Set logging level (default: INFO)"
    )
    
    return parser.parse_args()


def args_to_typed(ns: Namespace) -> CLIArgs:
    """Convert argparse Namespace to typed CLIArgs."""
    return CLIArgs(
        crashes_dir=ns.crashes_dir,
        crashes_pattern=ns.crashes_pattern,
        output_dir=ns.output_dir,
        matchup_size=ns.matchup_size,
        snapshot_every=ns.snapshot_every,
        budget=ns.budget,
        workers=ns.workers,
        judge_type=ns.judge_type,
        agent_timeout=ns.agent_timeout,
        noise=ns.noise,
        debug=ns.debug,
        log_level=ns.log_level,
    )


def validate_config(args: CLIArgs) -> None:
    """Validate configuration parameters."""
    logger = get_logger("validate_config")
    
    # Check matchup_size range (2-7 for reasonable tournament sizes)
    if not (2 <= args["matchup_size"] <= 7):
        logger.error(f"matchup_size must be between 2 and 7, got {args['matchup_size']}")
        print(f"Error: matchup_size must be between 2 and 7, got {args['matchup_size']}")
        sys.exit(1)
    
    # Ensure output directory exists
    output_dir = Path(args["output_dir"])
    output_dir.mkdir(parents=True, exist_ok=True)
    logger.info(f"Output directory: {output_dir}")
    
    # Check crashes directory exists
    crashes_dir = Path(args["crashes_dir"])
    if not crashes_dir.exists():
        logger.error(f"Crashes directory does not exist: {crashes_dir}")
        print(f"Error: crashes directory does not exist: {crashes_dir}")
        sys.exit(1)
    
    logger.info(f"Crashes directory: {crashes_dir}")
    
    # Compute budget if not provided
    if args["budget"] is None:
        # Reasonable default based on matchup size
        args["budget"] = args["matchup_size"] * 250
        logger.info(f"Computed budget: {args['budget']}")
        print(f"Computed budget: {args['budget']}")


def wire_components(args: CLIArgs) -> tuple[
    DirectoryCrashFetcher,
    Judge,
    JSONLStorage,
    TrueSkillRanker,
    RandomSelector,
    RunConfig
]:
    """Wire dependency injection components."""
    logger = get_logger("wire_components")
    
    # Create fetcher
    logger.info("Creating crash fetcher")
    fetcher = DirectoryCrashFetcher(Path(args["crashes_dir"]), pattern=args["crashes_pattern"])
    
    # Create storage
    logger.info("Creating storage")
    output_dir = Path(args["output_dir"])
    observations_path = output_dir / "observations.jsonl"
    snapshot_path = output_dir / "latest_snapshot.json"
    storage = JSONLStorage(observations_path, snapshot_path)
    
    # Create ranker
    logger.info("Creating TrueSkill ranker")
    ranker = TrueSkillRanker()
    
    # Create selector
    logger.info("Creating uncertainty selector")
    selector = RandomSelector(ranker)
    
    # Create judge based on type
    logger.info(f"Creating {args['judge_type']} judge")
    if args["judge_type"] == "simulated":
        # For simulated judge, we need ground truth scores
        # For now, create a simple ground truth based on crash IDs
        crashes = list(fetcher.list_crashes())
        ground_truth = {}
        for i, crash in enumerate(crashes):
            # Simple ground truth: higher ID number = higher exploitability
            ground_truth[crash.crash_id] = float(i) / len(crashes)
        judge = SimulatedJudge(ground_truth, noise=args["noise"])
        logger.info(f"Simulated judge created with {len(ground_truth)} crashes, noise={args['noise']}")
    elif args["judge_type"] == "dummy":
        judge = DummyJudge(mode="deterministic")
        logger.info("Dummy judge created")
    elif args["judge_type"] == "cursor-agent":
        judge = CursorAgentJudge(timeout=args["agent_timeout"])
        logger.info(f"Cursor agent judge created with timeout: {args['agent_timeout']}")
    elif args["judge_type"] == "cursor-agent-streaming":
        judge = CursorAgentStreamingJudge(timeout=args["agent_timeout"])
        logger.info(f"Cursor agent streaming judge created with timeout: {args['agent_timeout']}")
    else:
        logger.error(f"Unknown judge type: {args['judge_type']}")
        raise ValueError(f"Unknown judge type: {args['judge_type']}")
    
    # Build configuration
    logger.info("Creating run configuration")
    # Budget is guaranteed to be set by validate_config
    budget_value = args["budget"]
    assert budget_value is not None, "Budget must be set by validate_config"
    config = RunConfig(
        matchup_size=args["matchup_size"],
        budget=budget_value,
        max_workers=args["workers"],
        snapshot_every=args["snapshot_every"],
    )
    
    logger.info(f"Configuration: matchup_size={config.matchup_size}, budget={config.budget}")
    
    return fetcher, judge, storage, ranker, selector, config


def create_ranked_directory(
    rankings: dict[str, float],
    fetcher: CrashFetcher,
    output_dir: Path
) -> None:
    """
    Create a ranked directory with symlinks to crashes in rank order.
    
    Args:
        rankings: Dict of crash_id -> score (ordered by score descending)
        fetcher: CrashFetcher instance to get crash file paths
        output_dir: Output directory path
    """
    logger = get_logger("create_ranked_directory")
    
    # Create/clear ranked directory
    ranked_dir = output_dir / "ranked"
    if ranked_dir.exists():
        # Clear all existing symlinks
        shutil.rmtree(ranked_dir)
        logger.info(f"Cleared existing ranked directory: {ranked_dir}")
    
    ranked_dir.mkdir(exist_ok=True)
    logger.info(f"Created ranked directory: {ranked_dir}")
    
    # Create symlinks for each ranked crash
    for rank, (crash_id, _) in enumerate(rankings.items(), 1):
        # Get the crash object to find the file path
        crash = fetcher.get_crash(crash_id)
        
        # Create symlink name: rank_crash_id
        symlink_name = f"{rank}_{crash_id}"
        symlink_path = ranked_dir / symlink_name
        
        # Get the absolute path to the crash file
        crash_file_path = Path(crash.file_path).resolve()
        
        # Create symlink (no need to check if exists since we cleared the directory)
        symlink_path.symlink_to(crash_file_path)
        logger.debug(f"Created symlink: {symlink_name} -> {crash_file_path}")
    
    logger.info(f"Created {len(rankings)} ranked symlinks in {ranked_dir}")
    print(f"Created ranked directory with {len(rankings)} symlinks: {ranked_dir}")


def main() -> None:
    """Main CLI entry point."""
    try:
        # Parse and validate arguments
        raw_args = parse_args()
        args = args_to_typed(raw_args)
        
        # Setup logging
        setup_logging(level=args["log_level"], debug=args["debug"])
        logger = get_logger("main")
        
        logger.info("Starting Crash Tournament - Adaptive Comparative Judging System")
        validate_config(args)
        
        print("Crash Tournament - Adaptive Comparative Judging System")
        print("=" * 60)
        print(f"Crashes directory: {args['crashes_dir']}")
        print(f"Output directory: {args['output_dir']}")
        print(f"Matchup size: {args['matchup_size']}")
        print(f"Progress every: {args['snapshot_every']} (snapshots saved on every update)")
        print(f"Budget: {args['budget']}")
        print(f"Workers: {args['workers']}")
        print(f"Judge type: {args['judge_type']}")
        if args['judge_type'] == "cursor-agent":
            print("Using cursor-agent judge")
            print(f"Agent timeout: {args['agent_timeout']}")
        elif args['judge_type'] == "simulated":
            print(f"Noise level: {args['noise']}")
        print("=" * 60)
        
        # Wire components
        logger.info("Wiring components")
        fetcher, judge, storage, ranker, selector, config = wire_components(args)
        
        # Create orchestrator
        logger.info("Creating orchestrator")
        orchestrator = Orchestrator(
            fetcher=fetcher,
            judge=judge,
            storage=storage,
            ranker=ranker,
            selector=selector,
            config=config,
            output_dir=str(Path(args["output_dir"])),
        )
        
        # Run tournament
        logger.info("Starting tournament")
        print("Starting tournament...")
        rankings = orchestrator.run()
        
        # Print final rankings
        logger.info("Tournament completed successfully")
        print("\nFinal Rankings:")
        print("-" * 40)
        
        # Use prettytable for nice formatting (consistent with milestone updates)
        from prettytable import PrettyTable
        table = PrettyTable()
        table.field_names = ["Rank", "Crash ID", "Score", "Uncertainty", "Evals", "Win%", "Avg Rank"]
        table.align["Rank"] = "r"
        table.align["Score"] = "r"
        table.align["Uncertainty"] = "r"
        table.align["Evals"] = "r"
        table.align["Win%"] = "r"
        table.align["Avg Rank"] = "r"
        
        for i, (crash_id, score) in enumerate(rankings.items(), 1):
            uncertainty = orchestrator.ranker.get_uncertainty(crash_id)
            total_evals = orchestrator.ranker.get_total_eval_count(crash_id)
            win_pct = orchestrator.ranker.get_win_percentage(crash_id)
            avg_rank = orchestrator.ranker.get_average_ranking(crash_id)
            table.add_row([
                i, 
                crash_id, 
                f"{score:.3f}",
                f"{uncertainty:.3f}",
                total_evals,
                f"{win_pct:.1f}%",
                f"{avg_rank:.1f}"
            ])
        
        print(table)
        
        # Create ranked directory with symlinks
        create_ranked_directory(rankings, orchestrator.fetcher, Path(args["output_dir"]))
        
        print("\nTournament completed successfully!")
        
    except RuntimeError as e:
        if "Tournament already completed" in str(e):
            logger = get_logger("main")
            logger.error("Tournament already completed")
            print(f"\n{e}")
            sys.exit(1)
        else:
            raise
    except KeyboardInterrupt:
        logger = get_logger("main")
        logger.warning("Tournament interrupted by user")
        print("\nTournament interrupted by user")
        sys.exit(1)


if __name__ == "__main__":
    main()
