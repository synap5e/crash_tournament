"""
Test helper script that runs slowly for testing timeout handling.
"""

import sys
import time


def main():
    """Main entry point for slow test agent."""
    if len(sys.argv) < 2:
        print("Usage: slow_agent.py <input_file>")
        sys.exit(1)
    
    # Sleep for a long time to test timeout
    time.sleep(10)
    
    # This should never be reached due to timeout
    import json
    result = {
        "ordered": ["crash_a", "crash_b"],
        "rationale_top": "This should timeout"
    }
    print(json.dumps(result))


if __name__ == "__main__":
    main()
