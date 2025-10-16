"""
CLI entry point for crash tournament system.

Parses arguments, validates config, and wires components.
"""

import argparse
import os
import sys
from pathlib import Path

from .interfaces import CrashFetcher, Judge, Storage, Ranker, Selector
from .orchestrator import Orchestrator, RunConfig
from .fetchers.directory_fetcher import DirectoryCrashFetcher
from .storage.jsonl_storage import JSONLStorage
from .rankers.trueskill_ranker import TrueSkillRanker
from .group_selectors.uncertainty_selector import UncertaintySelector
from .judges.sim_judge import SimulatedJudge
from .judges.dummy_judge import DummyJudge
from .judges.cursor_agent_judge import CursorAgentJudge
from .judges.cursor_agent_streaming_judge import CursorAgentStreamingJudge
from .logging_config import setup_logging, get_logger


def parse_args():
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(
        description="Crash Tournament - Adaptive Comparative Judging System"
    )
    
    # Required arguments
    parser.add_argument(
        "--crashes-dir",
        required=True,
        help="Path to crash corpus directory"
    )
    parser.add_argument(
        "--crashes-pattern",
        default="*.json",
        help="Pattern for finding crash files (default: *.json)"
    )
    parser.add_argument(
        "--output-dir", 
        required=True,
        help="Directory for JSONL/snapshots output"
    )
    
    # Optional arguments
    parser.add_argument(
        "--k",
        type=int,
        default=4,
        help="Group size for comparisons (default: 4)"
    )
    parser.add_argument(
        "--seed-groups",
        type=int,
        default=200,
        help="Number of seed groups (default: 200)"
    )
    parser.add_argument(
        "--groups-per-round",
        type=int,
        default=50,
        help="Groups per uncertainty round (default: 50)"
    )
    parser.add_argument(
        "--budget",
        type=int,
        help="Total judge calls allowed (required or computed from rounds)"
    )
    parser.add_argument(
        "--workers",
        type=int,
        default=1,
        help="Number of worker threads for parallel evaluation (default: 1)"
    )
    parser.add_argument(
        "--resume",
        action="store_true",
        help="Load snapshot and continue from previous run"
    )
    
    # Judge selection
    parser.add_argument(
        "--judge-type",
        choices=["simulated", "dummy", "cursor-agent", "cursor-agent-streaming"],
        default="simulated",
        help="Type of judge to use (default: simulated)"
    )
    parser.add_argument(
        "--agent-timeout",
        type=float,
        default=300.0,
        help="Timeout for cursor-agent in seconds (default: 300)"
    )
    parser.add_argument(
        "--noise",
        type=float,
        default=0.1,
        help="Noise level for simulated judge (0-1, default: 0.1)"
    )
    parser.add_argument(
        "--debug",
        action="store_true",
        help="Enable debug logging"
    )
    parser.add_argument(
        "--log-level",
        choices=["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"],
        default="INFO",
        help="Set logging level (default: INFO)"
    )
    
    return parser.parse_args()


def validate_config(args):
    """Validate configuration parameters."""
    logger = get_logger("validate_config")
    
    # Check k range per doc line 9
    if not (2 <= args.k <= 7):
        logger.error(f"k must be between 2 and 7, got {args.k}")
        print(f"Error: k must be between 2 and 7, got {args.k}")
        sys.exit(1)
    
    # Ensure output directory exists
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    logger.info(f"Output directory: {output_dir}")
    
    # Check crashes directory exists
    crashes_dir = Path(args.crashes_dir)
    if not crashes_dir.exists():
        logger.error(f"Crashes directory does not exist: {crashes_dir}")
        print(f"Error: crashes directory does not exist: {crashes_dir}")
        sys.exit(1)
    
    logger.info(f"Crashes directory: {crashes_dir}")
    
    # Compute budget if not provided
    if args.budget is None:
        # Estimate based on seed groups + some uncertainty rounds
        args.budget = args.seed_groups + (args.groups_per_round * 10)
        logger.info(f"Computed budget: {args.budget}")
        print(f"Computed budget: {args.budget}")


def wire_components(args):
    """Wire dependency injection components."""
    logger = get_logger("wire_components")
    
    # Create fetcher
    logger.info("Creating crash fetcher")
    fetcher = DirectoryCrashFetcher(Path(args.crashes_dir), pattern=args.crashes_pattern)
    
    # Create storage
    logger.info("Creating storage")
    output_dir = Path(args.output_dir)
    observations_path = output_dir / "observations.jsonl"
    snapshot_path = output_dir / "snapshot.json"
    storage = JSONLStorage(observations_path, snapshot_path)
    
    # Create ranker
    logger.info("Creating TrueSkill ranker")
    ranker = TrueSkillRanker()
    
    # Create selector
    logger.info("Creating uncertainty selector")
    selector = UncertaintySelector(ranker)
    
    # Create judge based on type
    logger.info(f"Creating {args.judge_type} judge")
    if args.judge_type == "simulated":
        # For simulated judge, we need ground truth scores
        # For now, create a simple ground truth based on crash IDs
        crashes = list(fetcher.list_crashes())
        ground_truth = {}
        for i, crash in enumerate(crashes):
            # Simple ground truth: higher ID number = higher exploitability
            ground_truth[crash.crash_id] = float(i) / len(crashes)
        judge = SimulatedJudge(ground_truth, noise=args.noise)
        logger.info(f"Simulated judge created with {len(ground_truth)} crashes, noise={args.noise}")
    elif args.judge_type == "dummy":
        judge = DummyJudge(mode="deterministic")
        logger.info("Dummy judge created")
    elif args.judge_type == "cursor-agent":
        judge = CursorAgentJudge(timeout=args.agent_timeout)
        logger.info(f"Cursor agent judge created with timeout: {args.agent_timeout}")
    elif args.judge_type == "cursor-agent-streaming":
        judge = CursorAgentStreamingJudge(timeout=args.agent_timeout)
        logger.info(f"Cursor agent streaming judge created with timeout: {args.agent_timeout}")
    else:
        logger.error(f"Unknown judge type: {args.judge_type}")
        raise ValueError(f"Unknown judge type: {args.judge_type}")
    
    # Build configuration
    logger.info("Creating run configuration")
    config = RunConfig(
        k=args.k,
        seed_groups=args.seed_groups,
        groups_per_round=args.groups_per_round,
        budget=args.budget,
        max_workers=args.workers,
    )
    
    logger.info(f"Configuration: k={config.k}, seed_groups={config.seed_groups}, budget={config.budget}")
    
    return fetcher, judge, storage, ranker, selector, config


def create_ranked_directory(rankings, fetcher, output_dir):
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
        import shutil
        shutil.rmtree(ranked_dir)
        logger.info(f"Cleared existing ranked directory: {ranked_dir}")
    
    ranked_dir.mkdir(exist_ok=True)
    logger.info(f"Created ranked directory: {ranked_dir}")
    
    # Create symlinks for each ranked crash
    for rank, (crash_id, score) in enumerate(rankings.items(), 1):
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


def main():
    """Main CLI entry point."""
    try:
        # Parse and validate arguments
        args = parse_args()
        
        # Setup logging
        setup_logging(level=args.log_level, debug=args.debug)
        logger = get_logger("main")
        
        logger.info("Starting Crash Tournament - Adaptive Comparative Judging System")
        validate_config(args)
        
        print("Crash Tournament - Adaptive Comparative Judging System")
        print("=" * 60)
        print(f"Crashes directory: {args.crashes_dir}")
        print(f"Output directory: {args.output_dir}")
        print(f"Group size (k): {args.k}")
        print(f"Seed groups: {args.seed_groups}")
        print(f"Groups per round: {args.groups_per_round}")
        print(f"Budget: {args.budget}")
        print(f"Workers: {args.workers}")
        print(f"Resume: {args.resume}")
        print(f"Judge type: {args.judge_type}")
        if args.judge_type == "cursor-agent":
            print(f"Using cursor-agent judge")
            print(f"Agent timeout: {args.agent_timeout}")
        elif args.judge_type == "simulated":
            print(f"Noise level: {args.noise}")
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
            output_dir=Path(args.output_dir),
        )
        
        # Run tournament
        logger.info("Starting tournament")
        print("Starting tournament...")
        rankings = orchestrator.run()
        
        # Print final rankings
        logger.info("Tournament completed successfully")
        print("\nFinal Rankings:")
        print("-" * 40)
        
        # Use prettytable for nice formatting
        from prettytable import PrettyTable
        table = PrettyTable()
        table.field_names = ["Rank", "Crash ID", "Score", "Evals", "Win%", "Avg Rank"]
        table.align["Rank"] = "r"
        table.align["Score"] = "r"
        table.align["Evals"] = "r"
        table.align["Win%"] = "r"
        table.align["Avg Rank"] = "r"
        
        for i, (crash_id, score) in enumerate(rankings.items(), 1):
            eval_count = orchestrator.ranker.get_eval_count(crash_id)
            win_pct = orchestrator.ranker.get_win_percentage(crash_id)
            avg_rank = orchestrator.ranker.get_average_ranking(crash_id)
            table.add_row([
                i, 
                crash_id, 
                f"{score:.3f}",
                eval_count,
                f"{win_pct:.1f}%",
                f"{avg_rank:.1f}"
            ])
        
        print(table)
        
        # Create ranked directory with symlinks
        create_ranked_directory(rankings, orchestrator.fetcher, Path(args.output_dir))
        
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
