#!/usr/bin/env python3
"""
Simple CLI demo to rank crashes using a selected judge.

Usage:
    uv run python crash_tournament/rank_crashes_demo.py --judge cursor_agent crash1.json crash2.json crash3.json
    uv run python crash_tournament/rank_crashes_demo.py --judge simulated crash1.json crash2.json
    uv run python crash_tournament/rank_crashes_demo.py --judge dummy crash1.json crash2.json
"""

import argparse
import sys
from pathlib import Path
from typing import cast

from crash_tournament.models import Crash
from crash_tournament.judges.cursor_agent_judge import CursorAgentJudge
from crash_tournament.judges.cursor_agent_streaming_judge import CursorAgentStreamingJudge
from crash_tournament.judges.sim_judge import SimulatedJudge
from crash_tournament.judges.dummy_judge import DummyJudge
from crash_tournament.logging_config import setup_logging, get_logger


def create_crash_from_path(filepath: str) -> Crash:
    """Create a minimal Crash object from a file path (black box)."""
    path = Path(filepath)
    
    if not path.exists():
        raise FileNotFoundError(f"Crash file not found: {filepath}")
    
    # Extract crash_id from parent directory name (more unique than filename)
    # This matches what cursor-agent returns in its analysis
    crash_id = path.parent.name
    
    # Store the file path as-is (relative to current working directory)
    file_path = str(path)
    
    return Crash(
        crash_id=crash_id,
        file_path=file_path
    )


def create_judge(judge_type: str, timeout: float = 500.0, prompt_file: str | None = None):
    """Create a judge instance based on type."""
    if judge_type == "cursor_agent":
        return CursorAgentJudge(timeout=timeout, prompt_file=prompt_file)
    elif judge_type == "cursor_agent_streaming":
        return CursorAgentStreamingJudge(timeout=timeout, prompt_file=prompt_file)
    elif judge_type == "simulated":
        # Create simple ground truth based on file order
        ground_truth = dict[str, float]()
        return SimulatedJudge(ground_truth, noise=0.1)
    elif judge_type == "dummy":
        return DummyJudge(mode="deterministic")
    else:
        raise ValueError(f"Unknown judge type: {judge_type}")


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="Rank crashes using a selected judge",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Rank crashes using cursor-agent
  uv run python crash_tournament/rank_crashes_demo.py --judge cursor_agent crash1.json crash2.json crash3.json
  
  # Rank crashes using cursor-agent with custom prompt
  uv run python crash_tournament/rank_crashes_demo.py --judge cursor_agent -p custom_prompt.md crash1.json crash2.json
  
  # Rank crashes using simulated judge
  uv run python crash_tournament/rank_crashes_demo.py --judge simulated crash1.json crash2.json
  
  # Rank crashes using dummy judge
  uv run python crash_tournament/rank_crashes_demo.py --judge dummy crash1.json crash2.json
        """
    )
    
    _ = parser.add_argument(
        "--judge",
        choices=["cursor_agent", "cursor_agent_streaming", "simulated", "dummy"],
        required=True,
        help="Type of judge to use"
    )
    
    _ = parser.add_argument(
        "--timeout",
        type=float,
        default=300.0,
        help="Timeout for judge in seconds (default: 300)"
    )
    
    _ = parser.add_argument(
        "-p", "--prompt",
        help="Custom prompt file path (overrides default prompt)"
    )
    
    _ = parser.add_argument(
        "crash_files",
        nargs="+",
        help="Paths to crash JSON files"
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
    
    
    args: argparse.Namespace = parser.parse_args()
    
    # Type the argparse attributes for better type checking
    crash_files: list[str] = cast(list[str], args.crash_files)
    judge_type: str = cast(str, args.judge)
    timeout: float = cast(float, args.timeout)
    prompt: str | None = cast(str | None, args.prompt)
    debug: bool = cast(bool, args.debug)
    log_level: str = cast(str, args.log_level)
    
    # Validate arguments
    
    if len(crash_files) < 2:
        parser.error("At least 2 crash files are required for ranking")
    
    # Setup logging
    setup_logging(level=log_level, debug=debug)
    logger = get_logger("rank_crashes_demo")
    
    try:
        
        logger.info("Starting crash ranking demo")
        
        # Create crash objects from file paths
        print(f"Creating {len(crash_files)} crash objects...")
        logger.info(f"Creating {len(crash_files)} crash objects from file paths")
        crashes = list[Crash]()
        for filepath in crash_files:
            crash = create_crash_from_path(filepath)
            crashes.append(crash)
            logger.info(f"Created crash: {crash.crash_id}")
            print(f"  ✓ Created: {crash.crash_id} - {crash.file_path}")
        
        print()
        
        # Create judge
        print(f"Creating {judge_type} judge...")
        logger.info(f"Creating {judge_type} judge with timeout {timeout}")
        if judge_type == "dummy":
            judge = DummyJudge(mode="deterministic")
        elif judge_type == "simulated":
            # Create ground truth from file order
            ground_truth: dict[str, float] = {crash.crash_id: float(i) for i, crash in enumerate(crashes)}
            judge = SimulatedJudge(ground_truth, noise=0.1)
        else:
            judge = create_judge(judge_type, timeout=timeout, prompt_file=prompt)
        
        # Test connection for cursor-agent
        if judge_type in ["cursor_agent", "cursor_agent_streaming"]:
            print("Testing cursor-agent connection...")
            logger.info("Testing cursor-agent connection")
            if hasattr(judge, 'test_connection'):
                test_method = getattr(judge, 'test_connection')
                test_method()  # type: ignore[no-untyped-call, no-any-return]
                logger.info("Cursor-agent connection successful")
                print("  ✓ Connection successful")
            else:
                logger.warning("Judge does not support connection testing")
                print("  ⚠ Connection testing not available")
        
        print()
        
        # Rank crashes
        print(f"Ranking {len(crashes)} crashes...")
        logger.info(f"Starting evaluation of {len(crashes)} crashes")
        result = judge.evaluate_matchup(crashes)
        logger.info(f"Evaluation completed: {result.ordered_ids}")
        
        print()
        print("=" * 80)
        print("RANKING RESULTS")
        print("=" * 80)
        print()
        
        # Display rankings
        for rank, crash_id in enumerate(result.ordered_ids, 1):
            # Find the crash details
            crash: Crash = next(c for c in crashes if c.crash_id == crash_id)
            print(f"{rank}. {crash_id}")
            print(f"   File: {crash.file_path}")
            print()
        
        print("=" * 80)
        print("JUDGE OUTPUT")
        print("=" * 80)
        print()
        import json
        print(json.dumps(result.parsed_result, indent=2))
        print()
        
        # Show judge metadata
        print("=" * 80)
        print("METADATA")
        print("=" * 80)
        print(f"Judge ID: {result.judge_id}")
        print(f"Group size: {result.group_size}")
        print(f"Timestamp: {result.timestamp}")
        print()
        
        # Success!
        logger.info("Ranking completed successfully")
        print("✓ Ranking complete!")
        
    except KeyboardInterrupt:
        logger.warning("Interrupted by user")
        print("\n\nInterrupted by user", file=sys.stderr)
        sys.exit(130)


if __name__ == "__main__":
    main()
