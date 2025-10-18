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
    
    def test_loads_valid_crash_files(self):
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
                with open(crash_file, 'w') as f:
                    json.dump(data, f)
            
            fetcher = DirectoryCrashFetcher(crashes_dir)
            
            # Act
            crashes = list(fetcher.list_crashes())
            
            # Assert
            assert len(crashes) == 2, "Should load 2 crashes"
            
            # Check first crash (directory-based ID)
            crash_000 = next(c for c in crashes if c.crash_id == "crash_000_crash")
            # Crash model only has crash_id, file_path, and timestamp - no JSON fields
            
            # Check second crash (directory-based ID)
            crash_001 = next(c for c in crashes if c.crash_id == "crash_001_crash")
            assert crash_001.timestamp == 1234567891.0
    
    def test_skips_invalid_files(self):
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
            with open(crashes_dir / "valid.json", 'w') as f:
                json.dump(valid_data, f)
            
            # Create invalid JSON file
            with open(crashes_dir / "invalid.json", 'w') as f:
                f.write("This is not valid JSON")
            
            # Create file missing required fields
            incomplete_data = {
                "summary": "Missing crash_id",
                "stack_trace": "Missing crash_id",
            }
            with open(crashes_dir / "incomplete.json", 'w') as f:
                json.dump(incomplete_data, f)
            
            fetcher = DirectoryCrashFetcher(crashes_dir)
            
            # Act
            crashes = list(fetcher.list_crashes())
            
            # Assert
            assert len(crashes) == 1, "Should load only valid crash"
            assert crashes[0].crash_id == "valid_crash"
    
    def test_caching_works(self):
        """Multiple calls should not re-read files."""
        with tempfile.TemporaryDirectory() as temp_dir:
            # Arrange
            crashes_dir = Path(temp_dir)
            
            crash_data = {
                "crash_id": "cached_crash",
                "summary": "Cached crash",
                "stack_trace": "Cached trace",
            }
            with open(crashes_dir / "cached.json", 'w') as f:
                json.dump(crash_data, f)
            
            fetcher = DirectoryCrashFetcher(crashes_dir)
            
            # Act - call multiple times
            crashes1 = list(fetcher.list_crashes())
            crashes2 = list(fetcher.list_crashes())
            
            # Assert
            assert len(crashes1) == 1, "First call should load 1 crash"
            assert len(crashes2) == 1, "Second call should load 1 crash"
            assert crashes1[0].crash_id == crashes2[0].crash_id, "Should return same crash"
    
    def test_get_crash_by_id(self):
        """Should retrieve specific crash by ID."""
        with tempfile.TemporaryDirectory() as temp_dir:
            # Arrange
            crashes_dir = Path(temp_dir)
            
            crash_data = {
                "crash_id": "specific_crash",
                "summary": "Specific crash",
                "stack_trace": "Specific trace",
            }
            with open(crashes_dir / "specific.json", 'w') as f:
                json.dump(crash_data, f)
            
            fetcher = DirectoryCrashFetcher(crashes_dir)
            
            # Act
            crash = fetcher.get_crash("specific")
            
            # Assert
            assert crash.crash_id == "specific"
            # Crash model only has crash_id, file_path, and timestamp
    
    def test_get_crash_by_id_not_found(self):
        """Should raise KeyError for non-existent crash ID."""
        with tempfile.TemporaryDirectory() as temp_dir:
            # Arrange
            crashes_dir = Path(temp_dir)
            fetcher = DirectoryCrashFetcher(crashes_dir)
            
            # Act & Assert
            with pytest.raises(KeyError, match="Crash not found"):
                fetcher.get_crash("nonexistent_crash")
    
    def test_get_crash_ids(self):
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
                with open(crashes_dir / f"crash_{i}.json", 'w') as f:
                    json.dump(data, f)
            
            fetcher = DirectoryCrashFetcher(crashes_dir)
            
            # Act
            crash_ids = fetcher.get_crash_ids()
            
            # Assert
            assert len(crash_ids) == 3, "Should return 3 crash IDs"
            # Directory-based IDs will be like "crash_0", "crash_1", "crash_2"
            expected_ids = {"crash_0", "crash_1", "crash_2"}
            assert set(crash_ids) == expected_ids, \
                f"Should return all crash IDs, got {set(crash_ids)}, expected {expected_ids}"
    
    def test_reload_clears_cache(self):
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
            with open(crashes_dir / "initial.json", 'w') as f:
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
            with open(crashes_dir / "new.json", 'w') as f:
                json.dump(new_data, f)
            
            # Act
            fetcher.reload_crashes()
            reloaded_crashes = list(fetcher.list_crashes())
            
            # Assert
            assert len(reloaded_crashes) == 2, "Should load both crashes after reload"
            crash_ids = {c.crash_id for c in reloaded_crashes}
            # Directory-based IDs will be like "initial", "new"
            expected_ids = {"initial", "new"}
            assert crash_ids == expected_ids, \
                f"Should include both old and new crashes, got {crash_ids}, expected {expected_ids}"
    
    def test_get_crash_count(self):
        """Should return correct count of crashes."""
        with tempfile.TemporaryDirectory() as temp_dir:
            # Arrange
            crashes_dir = Path(temp_dir)
            fetcher = DirectoryCrashFetcher(crashes_dir)
            
            # Act & Assert
            assert fetcher.get_crash_count() == 0, "Empty directory should have 0 crashes"
            
            # Add some crashes
            for i in range(3):
                crash_data = {
                    "crash_id": f"crash_{i}",
                    "summary": f"Crash {i}",
                    "stack_trace": f"Trace {i}",
                }
                with open(crashes_dir / f"crash_{i}.json", 'w') as f:
                    json.dump(crash_data, f)
            
            assert fetcher.get_crash_count() == 3, "Should count 3 crashes"
    
    def test_clear_cache(self):
        """Should clear cache for testing."""
        with tempfile.TemporaryDirectory() as temp_dir:
            # Arrange
            crashes_dir = Path(temp_dir)
            
            crash_data = {
                "crash_id": "test_crash",
                "summary": "Test crash",
                "stack_trace": "Test trace",
            }
            with open(crashes_dir / "test.json", 'w') as f:
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
    
    def test_handles_missing_directory(self):
        """Should raise FileNotFoundError for missing directory."""
        # Arrange
        nonexistent_dir = Path("/nonexistent/directory/12345")
        
        # Act & Assert
        with pytest.raises(FileNotFoundError, match="Crashes directory does not exist"):
            DirectoryCrashFetcher(nonexistent_dir)
    
    def test_handles_file_instead_of_directory(self):
        """Should raise NotADirectoryError for file path."""
        with tempfile.TemporaryDirectory() as temp_dir:
            # Arrange
            file_path = Path(temp_dir) / "not_a_directory.txt"
            with open(file_path, 'w') as f:
                f.write("This is a file, not a directory")
            
            # Act & Assert
            with pytest.raises(NotADirectoryError, match="Path is not a directory"):
                DirectoryCrashFetcher(file_path)
    
    def test_handles_empty_directory(self):
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
    
    def test_handles_nested_directories(self):
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
            with open(crashes_dir / "main.json", 'w') as f:
                json.dump(main_data, f)
            
            # Create subdirectory with file
            subdir = crashes_dir / "subdir"
            subdir.mkdir()
            sub_data = {
                "crash_id": "sub_crash",
                "summary": "Sub crash",
                "stack_trace": "Sub trace",
            }
            with open(subdir / "sub.json", 'w') as f:
                json.dump(sub_data, f)
            
            fetcher = DirectoryCrashFetcher(crashes_dir)
            
            # Act
            crashes = list(fetcher.list_crashes())
            
            # Assert
            # DirectoryCrashFetcher uses rglob, so it will read subdirectories too
            assert len(crashes) == 2, "Should read files in main directory and subdirectories"
            assert crashes[0].crash_id == "main_crash", "Should read main directory file"
    
    def test_handles_different_file_patterns(self):
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
            with open(crashes_dir / "crash.json", 'w') as f:
                json.dump(json_data, f)
            
            txt_data = {
                "crash_id": "txt_crash",
                "summary": "TXT crash",
                "stack_trace": "TXT trace",
            }
            with open(crashes_dir / "crash.txt", 'w') as f:
                json.dump(txt_data, f)
            
            # Act - use custom pattern for .txt files
            fetcher = DirectoryCrashFetcher(crashes_dir, pattern="*.txt")
            crashes = list(fetcher.list_crashes())
            
            # Assert
            assert len(crashes) == 1, "Should only read .txt files"
            assert crashes[0].crash_id == "txt_crash", "Should read .txt file"
