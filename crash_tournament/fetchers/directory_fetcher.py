"""
Directory crash fetcher implementation.

Reads crashes from directory structure with JSON files.
"""

from collections.abc import Iterable
from pathlib import Path

from typing_extensions import override

from ..interfaces import CrashFetcher
from ..logging_config import get_logger
from ..models import Crash


class DirectoryCrashFetcher(CrashFetcher):
    """
    Crash fetcher that reads from directory structure.

    Treats crash files as opaque - only stores file paths.
    """

    def __init__(self, crashes_dir: Path, pattern: str = "*.json"):
        """
        Initialize directory crash fetcher.

        Args:
            crashes_dir: Directory containing crash files
            pattern: File pattern to match (default: "*")
        """
        self.crashes_dir: Path = Path(crashes_dir)
        self.pattern: str = pattern

        # Setup logger
        self.logger = get_logger("directory_fetcher")

        # Validate directory exists and is a directory
        if not self.crashes_dir.exists():
            raise FileNotFoundError(
                f"Crashes directory does not exist: {self.crashes_dir}"
            )

        if not self.crashes_dir.is_dir():
            raise NotADirectoryError(f"Path is not a directory: {self.crashes_dir}")

        # Cache for loaded crashes
        self._cache = dict[str, Crash]()
        self._cache_loaded: bool = False

    def _load_crashes(self) -> None:
        """Load all crashes from directory into cache."""
        if self._cache_loaded:
            return

        # Find all matching files (recursively)
        crash_files = list(self.crashes_dir.rglob(self.pattern))

        if not crash_files:
            self.logger.warning(
                f"No files matching pattern '{self.pattern}' found in {self.crashes_dir}"
            )
            return

        # Load each crash file
        for crash_file in crash_files:
            # Security: Ensure file is within the crashes directory (path traversal protection)
            try:
                crash_file.resolve().relative_to(self.crashes_dir.resolve())
            except ValueError:
                self.logger.warning(
                    f"Skipping file outside crashes directory: {crash_file}"
                )
                continue
            # Skip directories
            if crash_file.is_dir():
                continue

            # Extract crash_id from parent directory name and file stem for unique identification
            # This prevents collisions when multiple files exist in the same directory
            crash_id = f"{crash_file.parent.name}_{crash_file.stem}"

            # Create Crash object with absolute file path
            crash = Crash(crash_id=crash_id, file_path=str(crash_file.resolve()))

            self._cache[crash.crash_id] = crash

        self._cache_loaded = True
        self.logger.info(f"Loaded {len(self._cache)} crashes from {self.crashes_dir}")

    @override
    def list_crashes(self) -> Iterable[Crash]:
        """Return all available crashes."""
        self._load_crashes()
        return self._cache.values()

    @override
    def get_crash(self, crash_id: str) -> Crash:
        """Get a specific crash by ID."""
        self._load_crashes()

        if crash_id not in self._cache:
            raise KeyError(f"Crash not found: {crash_id}")

        return self._cache[crash_id]

    def get_crash_count(self) -> int:
        """Get total number of available crashes."""
        self._load_crashes()
        return len(self._cache)

    def get_crash_ids(self) -> list[str]:
        """Get list of all crash IDs."""
        self._load_crashes()
        return list(self._cache.keys())

    def clear_cache(self) -> None:
        """Clear the crash cache and force reload on next access.

        This method resets the internal cache, causing crashes to be reloaded
        from the directory on the next call to list_crashes() or get_crash().
        Useful for refreshing data when files may have changed.
        """
        self._cache.clear()
        self._cache_loaded = False

    def reload_crashes(self) -> None:
        """Force reload crashes from directory."""
        self.clear_cache()
        self._load_crashes()
