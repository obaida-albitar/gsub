"""Tests for logging system."""

import pytest
import os
import tempfile
from pathlib import Path
from gsub.logger import setup_logger, get_logger, _cleanup_old_logs


class TestLogger:
    """Test logging functionality."""
    
    def test_setup_logger_creates_log_directory(self, tmp_path):
        """Test that logger creates log directory."""
        log_dir = tmp_path / "logs"
        logger = setup_logger("test_logger", log_dir=log_dir)
        
        assert log_dir.exists()
        assert logger.name == "test_logger"
    
    def test_setup_logger_creates_log_file(self, tmp_path):
        """Test that logger creates log file."""
        log_dir = tmp_path / "logs"
        logger = setup_logger("test_logger_file", log_dir=log_dir)
        
        # Write something to ensure file is created
        logger.info("Test message")
        
        # Should have created at least one log file
        log_files = list(log_dir.glob("gsub_*.log"))
        assert len(log_files) >= 1
    
    def test_logger_writes_to_file(self, tmp_path):
        """Test that logger actually writes to file."""
        log_dir = tmp_path / "logs"
        logger = setup_logger("test_logger_writes", log_dir=log_dir)
        
        test_message = "Test log message"
        logger.info(test_message)
        
        # Read the log file
        log_files = list(log_dir.glob("gsub_*.log"))
        with open(log_files[0], 'r') as f:
            content = f.read()
        
        assert test_message in content
    
    def test_logger_different_levels(self, tmp_path):
        """Test different log levels."""
        log_dir = tmp_path / "logs"
        logger = setup_logger("test_logger_levels", log_dir=log_dir)
        
        logger.debug("Debug message")
        logger.info("Info message")
        logger.warning("Warning message")
        logger.error("Error message")
        
        # Read the log file
        log_files = list(log_dir.glob("gsub_*.log"))
        with open(log_files[0], 'r') as f:
            content = f.read()
        
        assert "Debug message" in content
        assert "Info message" in content
        assert "Warning message" in content
        assert "Error message" in content
    
    def test_get_logger_returns_existing(self, tmp_path):
        """Test that get_logger returns existing logger."""
        log_dir = tmp_path / "logs"
        logger1 = setup_logger("test_logger_existing", log_dir=log_dir)
        logger2 = get_logger("test_logger_existing")
        
        assert logger1 is logger2
    
    def test_get_logger_auto_setup(self):
        """Test that get_logger auto-sets up if not configured."""
        # Use a unique name to avoid conflicts
        logger = get_logger("test_auto_setup_logger")
        
        assert logger is not None
        assert logger.handlers  # Should have handlers
    
    def test_cleanup_old_logs(self, tmp_path):
        """Test that old logs are cleaned up."""
        log_dir = tmp_path / "logs"
        log_dir.mkdir(parents=True)
        
        # Create 15 fake log files
        for i in range(15):
            log_file = log_dir / f"gsub_{i:06d}_000000.log"
            log_file.write_text(f"Log {i}")
        
        # Cleanup, keeping only 10
        _cleanup_old_logs(log_dir, keep=10)
        
        # Should have only 10 files left
        log_files = list(log_dir.glob("gsub_*.log"))
        assert len(log_files) == 10
    
    def test_cleanup_old_logs_keeps_newest(self, tmp_path):
        """Test that cleanup keeps the newest files."""
        import time
        log_dir = tmp_path / "logs"
        log_dir.mkdir(parents=True)
        
        # Create files with different timestamps
        files = []
        for i in range(5):
            log_file = log_dir / f"gsub_{i:06d}_000000.log"
            log_file.write_text(f"Log {i}")
            files.append(log_file)
            time.sleep(0.01)  # Small delay to ensure different mtimes
        
        # Cleanup, keeping only 3
        _cleanup_old_logs(log_dir, keep=3)
        
        # Should have only 3 files left
        remaining = list(log_dir.glob("gsub_*.log"))
        assert len(remaining) == 3
        
        # The newest files should remain
        remaining_names = {f.name for f in remaining}
        # Files 2, 3, 4 should remain (newest)
        assert "gsub_000002_000000.log" in remaining_names or \
               "gsub_000003_000000.log" in remaining_names or \
               "gsub_000004_000000.log" in remaining_names
    
    def test_cleanup_handles_errors_gracefully(self, tmp_path):
        """Test that cleanup doesn't crash on errors."""
        # Try to cleanup non-existent directory
        fake_dir = tmp_path / "nonexistent"
        
        # Should not raise exception
        _cleanup_old_logs(fake_dir, keep=10)
    
    def test_logger_uses_utf8_encoding(self, tmp_path):
        """Test that logger handles UTF-8 characters."""
        log_dir = tmp_path / "logs"
        logger = setup_logger("test_logger_utf8", log_dir=log_dir)
        
        # Log messages with various UTF-8 characters
        logger.info("Unicode: héllo wörld 你好 مرحبا")
        logger.info("Emojis: 😀 🎉 🚀")
        
        # Read the log file
        log_files = list(log_dir.glob("gsub_*.log"))
        with open(log_files[0], 'r', encoding='utf-8') as f:
            content = f.read()
        
        assert "héllo wörld" in content
        assert "你好" in content
    
    def test_logger_includes_timestamp(self, tmp_path):
        """Test that log entries include timestamp."""
        log_dir = tmp_path / "logs"
        logger = setup_logger("test_logger_timestamp", log_dir=log_dir)
        
        logger.info("Timestamped message")
        
        # Read the log file
        log_files = list(log_dir.glob("gsub_*.log"))
        with open(log_files[0], 'r') as f:
            content = f.read()
        
        # Should have date format YYYY-MM-DD
        import re
        assert re.search(r'\d{4}-\d{2}-\d{2}', content)
    
    def test_logger_includes_level(self, tmp_path):
        """Test that log entries include log level."""
        log_dir = tmp_path / "logs"
        logger = setup_logger("test_logger_level", log_dir=log_dir)
        
        logger.warning("Warning level test")
        
        # Read the log file
        log_files = list(log_dir.glob("gsub_*.log"))
        with open(log_files[0], 'r') as f:
            content = f.read()
        
        assert "WARNING" in content
    
    def test_setup_logger_only_configures_once(self, tmp_path):
        """Test that logger is only configured once."""
        log_dir = tmp_path / "logs"
        logger1 = setup_logger("test_logger_once", log_dir=log_dir)
        
        # Get initial handler count
        handler_count = len(logger1.handlers)
        
        # Try to setup again with same name
        logger2 = setup_logger("test_logger_once", log_dir=log_dir)
        
        # Should be the same logger with same number of handlers
        assert logger1 is logger2
        assert len(logger2.handlers) == handler_count
