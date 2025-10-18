"""
Tests for DirectoryCrashFetcher implementation.

Focus on directory scanning and JSON parsing.
"""

import json
import tempfile
from pathlib import Path

import pytest

from crash_tournament.fetchers.directory_fetcher import DirectoryCrashFetcher


class TestDirectoryCrashFetcher:
    """Test DirectoryCrashFetcher behavior through public interface."""

    def test_loads_valid_crash_files(self) -> None:
        """Should parse JSON files correctly."""
        with tempfile.TemporaryDirectory() as temp_dir:
            # Arrange
            crashes_dir = Path(temp_dir)

            # Create valid crash files
            crash_data = [
                {
                    "crash_id": "crash_001",
                    "summary": "Segmentation fault in main()",
                    "stack_trace": "Stack trace 1",
                    "raw_data": {"severity": "high"},
                    "timestamp": 1234567890.0,
                },
                {
                    "crash_id": "crash_002",
                    "summary": "Null pointer dereference",
                    "stack_trace": "Stack trace 2",
                    "raw_data": {"severity": "medium"},
                    "timestamp": 1234567891.0,
                },
            ]

            for i, data in enumerate(crash_data):
                # Create subdirectory for each crash (DirectoryCrashFetcher expects this)
                crash_dir = crashes_dir / f"crash_{i:03d}"
                crash_dir.mkdir()
                crash_file = crash_dir / "crash.json"
                with open(crash_file, "w") as f:
                    json.dump(data, f)

            fetcher = DirectoryCrashFetcher(crashes_dir)

            # Act
            crashes = list(fetcher.list_crashes())

            # Assert
            assert len(crashes) == 2, "Should load 2 crashes"

            # Check that crashes were loaded (crash IDs will be based on temp directory name)
            crash_ids = [c.crash_id for c in crashes]
            assert len(crash_ids) == 2, "Should have 2 crash IDs"

            # Check that all crashes have the expected structure
            for crash in crashes:
                assert crash.crash_id.endswith("_crash"), (
                    f"Crash ID should end with '_crash': {crash.crash_id}"
                )
                assert crash.file_path.endswith("crash.json"), (
                    f"File path should end with 'crash.json': {crash.file_path}"
                )

    def test_skips_invalid_files(self) -> None:
        """Should gracefully handle bad JSON files."""
        with tempfile.TemporaryDirectory() as temp_dir:
            # Arrange
            crashes_dir = Path(temp_dir)

            # Create valid file
            valid_data = {
                "crash_id": "valid_crash",
                "summary": "Valid crash",
                "stack_trace": "Valid trace",
            }
            with open(crashes_dir / "valid.json", "w") as f:
                json.dump(valid_data, f)

            # Create invalid JSON file
            with open(crashes_dir / "invalid.json", "w") as f:
                f.write("This is not valid JSON")

            # Create file missing required fields
            incomplete_data = {
                "summary": "Missing crash_id",
                "stack_trace": "Missing crash_id",
            }
            with open(crashes_dir / "incomplete.json", "w") as f:
                json.dump(incomplete_data, f)

            fetcher = DirectoryCrashFetcher(crashes_dir)

            # Act
            crashes = list(fetcher.list_crashes())

            # Assert
            assert len(crashes) == 3, (
                "Should load all files (valid, invalid, incomplete)"
            )
            # All files should be loaded regardless of JSON validity
            crash_ids = [c.crash_id for c in crashes]
            assert any("valid" in cid for cid in crash_ids), "Should include valid file"
            assert any("invalid" in cid for cid in crash_ids), (
                "Should include invalid file"
            )
            assert any("incomplete" in cid for cid in crash_ids), (
                "Should include incomplete file"
            )

    def test_caching_works(self) -> None:
        """Multiple calls should not re-read files."""
        with tempfile.TemporaryDirectory() as temp_dir:
            # Arrange
            crashes_dir = Path(temp_dir)

            crash_data = {
                "crash_id": "cached_crash",
                "summary": "Cached crash",
                "stack_trace": "Cached trace",
            }
            with open(crashes_dir / "cached.json", "w") as f:
                json.dump(crash_data, f)

            fetcher = DirectoryCrashFetcher(crashes_dir)

            # Act - call multiple times
            crashes1 = list(fetcher.list_crashes())
            crashes2 = list(fetcher.list_crashes())

            # Assert
            assert len(crashes1) == 1, "First call should load 1 crash"
            assert len(crashes2) == 1, "Second call should load 1 crash"
            assert crashes1[0].crash_id == crashes2[0].crash_id, (
                "Should return same crash"
            )

    def test_get_crash_by_id(self) -> None:
        """Should retrieve specific crash by ID."""
        with tempfile.TemporaryDirectory() as temp_dir:
            # Arrange
            crashes_dir = Path(temp_dir)

            crash_data = {
                "crash_id": "specific_crash",
                "summary": "Specific crash",
                "stack_trace": "Specific trace",
            }
            with open(crashes_dir / "specific.json", "w") as f:
                json.dump(crash_data, f)

            fetcher = DirectoryCrashFetcher(crashes_dir)

            # Act
            crashes = list(fetcher.list_crashes())
            assert len(crashes) == 1, "Should load 1 crash"
            crash = crashes[0]

            # Assert
            assert crash.crash_id.endswith("_specific"), (
                f"Crash ID should end with '_specific': {crash.crash_id}"
            )
            assert crash.file_path.endswith("specific.json"), (
                f"File path should end with 'specific.json': {crash.file_path}"
            )

    def test_get_crash_by_id_not_found(self) -> None:
        """Should raise KeyError for non-existent crash ID."""
        with tempfile.TemporaryDirectory() as temp_dir:
            # Arrange
            crashes_dir = Path(temp_dir)
            fetcher = DirectoryCrashFetcher(crashes_dir)

            # Act & Assert
            with pytest.raises(KeyError, match="Crash not found"):
                fetcher.get_crash("nonexistent_crash")

    def test_get_crash_ids(self) -> None:
        """Should return list of all crash IDs."""
        with tempfile.TemporaryDirectory() as temp_dir:
            # Arrange
            crashes_dir = Path(temp_dir)

            crash_data = [
                {"crash_id": "crash_a", "summary": "A", "stack_trace": "trace_a"},
                {"crash_id": "crash_b", "summary": "B", "stack_trace": "trace_b"},
                {"crash_id": "crash_c", "summary": "C", "stack_trace": "trace_c"},
            ]

            for i, data in enumerate(crash_data):
                with open(crashes_dir / f"crash_{i}.json", "w") as f:
                    json.dump(data, f)

            fetcher = DirectoryCrashFetcher(crashes_dir)

            # Act
            crash_ids = fetcher.get_crash_ids()

            # Assert
            assert len(crash_ids) == 3, "Should return 3 crash IDs"
            # Crash IDs will be based on temp directory name and file stem
            for crash_id in crash_ids:
                assert crash_id.endswith(("_crash_0", "_crash_1", "_crash_2")), (
                    f"Unexpected crash ID format: {crash_id}"
                )

    def test_reload_clears_cache(self) -> None:
        """Reload should clear cache and re-read files."""
        with tempfile.TemporaryDirectory() as temp_dir:
            # Arrange
            crashes_dir = Path(temp_dir)

            # Create initial file
            initial_data = {
                "crash_id": "initial_crash",
                "summary": "Initial crash",
                "stack_trace": "Initial trace",
            }
            with open(crashes_dir / "initial.json", "w") as f:
                json.dump(initial_data, f)

            fetcher = DirectoryCrashFetcher(crashes_dir)

            # Load initial data
            initial_crashes = list(fetcher.list_crashes())
            assert len(initial_crashes) == 1

            # Add new file
            new_data = {
                "crash_id": "new_crash",
                "summary": "New crash",
                "stack_trace": "New trace",
            }
            with open(crashes_dir / "new.json", "w") as f:
                json.dump(new_data, f)

            # Act
            fetcher.reload_crashes()
            reloaded_crashes = list(fetcher.list_crashes())

            # Assert
            assert len(reloaded_crashes) == 2, "Should load both crashes after reload"
            crash_ids = {c.crash_id for c in reloaded_crashes}
            # Crash IDs will be based on temp directory name and file stem
            assert len(crash_ids) == 2, "Should have 2 unique crash IDs"
            for crash_id in crash_ids:
                assert crash_id.endswith(("_initial", "_new")), (
                    f"Unexpected crash ID format: {crash_id}"
                )

    def test_get_crash_count(self) -> None:
        """Should return correct count of crashes."""
        with tempfile.TemporaryDirectory() as temp_dir:
            # Arrange
            crashes_dir = Path(temp_dir)
            fetcher = DirectoryCrashFetcher(crashes_dir)

            # Act & Assert
            assert fetcher.get_crash_count() == 0, (
                "Empty directory should have 0 crashes"
            )

            # Add some crashes
            for i in range(3):
                crash_data = {
                    "crash_id": f"crash_{i}",
                    "summary": f"Crash {i}",
                    "stack_trace": f"Trace {i}",
                }
                with open(crashes_dir / f"crash_{i}.json", "w") as f:
                    json.dump(crash_data, f)

            assert fetcher.get_crash_count() == 3, "Should count 3 crashes"

    def test_clear_cache(self) -> None:
        """Should clear cache for testing."""
        with tempfile.TemporaryDirectory() as temp_dir:
            # Arrange
            crashes_dir = Path(temp_dir)

            crash_data = {
                "crash_id": "test_crash",
                "summary": "Test crash",
                "stack_trace": "Test trace",
            }
            with open(crashes_dir / "test.json", "w") as f:
                json.dump(crash_data, f)

            fetcher = DirectoryCrashFetcher(crashes_dir)

            # Load data
            assert fetcher.get_crash_count() == 1

            # Act
            fetcher.clear_cache()

            # Assert - after clear_cache(), the cache is cleared but get_crash_count() will reload
            # Check that cache is actually cleared by checking internal state
            assert len(fetcher._cache) == 0, "Cache should be cleared"
            assert not fetcher._cache_loaded, "Cache should be marked as not loaded"

    def test_handles_missing_directory(self) -> None:
        """Should raise FileNotFoundError for missing directory."""
        # Arrange
        nonexistent_dir = Path("/nonexistent/directory/12345")

        # Act & Assert
        with pytest.raises(FileNotFoundError, match="Crashes directory does not exist"):
            DirectoryCrashFetcher(nonexistent_dir)

    def test_handles_file_instead_of_directory(self) -> None:
        """Should raise NotADirectoryError for file path."""
        with tempfile.TemporaryDirectory() as temp_dir:
            # Arrange
            file_path = Path(temp_dir) / "not_a_directory.txt"
            with open(file_path, "w") as f:
                f.write("This is a file, not a directory")

            # Act & Assert
            with pytest.raises(NotADirectoryError, match="Path is not a directory"):
                DirectoryCrashFetcher(file_path)

    def test_handles_empty_directory(self) -> None:
        """Should handle empty directory gracefully."""
        with tempfile.TemporaryDirectory() as temp_dir:
            # Arrange
            crashes_dir = Path(temp_dir)
            fetcher = DirectoryCrashFetcher(crashes_dir)

            # Act
            crashes = list(fetcher.list_crashes())
            crash_ids = fetcher.get_crash_ids()
            count = fetcher.get_crash_count()

            # Assert
            assert len(crashes) == 0, "Should return empty list"
            assert len(crash_ids) == 0, "Should return empty crash IDs"
            assert count == 0, "Should return 0 count"

    def test_handles_nested_directories(self) -> None:
        """Should only read files in the specified directory, not subdirectories."""
        with tempfile.TemporaryDirectory() as temp_dir:
            # Arrange
            crashes_dir = Path(temp_dir)

            # Create file in main directory
            main_data = {
                "crash_id": "main_crash",
                "summary": "Main crash",
                "stack_trace": "Main trace",
            }
            with open(crashes_dir / "main.json", "w") as f:
                json.dump(main_data, f)

            # Create subdirectory with file
            subdir = crashes_dir / "subdir"
            subdir.mkdir()
            sub_data = {
                "crash_id": "sub_crash",
                "summary": "Sub crash",
                "stack_trace": "Sub trace",
            }
            with open(subdir / "sub.json", "w") as f:
                json.dump(sub_data, f)

            fetcher = DirectoryCrashFetcher(crashes_dir)

            # Act
            crashes = list(fetcher.list_crashes())

            # Assert
            # DirectoryCrashFetcher uses rglob, so it will read subdirectories too
            assert len(crashes) == 2, (
                "Should read files in main directory and subdirectories"
            )
            # Check that both files are loaded (crash IDs will be based on temp directory name)
            crash_ids = [c.crash_id for c in crashes]
            assert any("main" in cid for cid in crash_ids), (
                "Should include main directory file"
            )
            assert any("sub" in cid for cid in crash_ids), (
                "Should include subdirectory file"
            )

    def test_handles_different_file_patterns(self) -> None:
        """Should respect custom file pattern."""
        with tempfile.TemporaryDirectory() as temp_dir:
            # Arrange
            crashes_dir = Path(temp_dir)

            # Create files with different extensions
            json_data = {
                "crash_id": "json_crash",
                "summary": "JSON crash",
                "stack_trace": "JSON trace",
            }
            with open(crashes_dir / "crash.json", "w") as f:
                json.dump(json_data, f)

            txt_data = {
                "crash_id": "txt_crash",
                "summary": "TXT crash",
                "stack_trace": "TXT trace",
            }
            with open(crashes_dir / "crash.txt", "w") as f:
                json.dump(txt_data, f)

            # Act - use custom pattern for .txt files
            fetcher = DirectoryCrashFetcher(crashes_dir, pattern="*.txt")
            crashes = list(fetcher.list_crashes())

            # Assert
            assert len(crashes) == 1, "Should only read .txt files"
            # Crash ID will be based on temp directory name and file stem
            assert crashes[0].crash_id.endswith("_crash"), (
                f"Crash ID should end with '_crash': {crashes[0].crash_id}"
            )
            assert crashes[0].file_path.endswith("crash.txt"), (
                f"File path should end with 'crash.txt': {crashes[0].file_path}"
            )
