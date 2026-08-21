"""Logging configuration for subtitle editor application."""

import logging
import os
from pathlib import Path
from datetime import datetime


def setup_logger(name='gsub', log_dir=None):
    """
    Set up logger that writes to file instead of console.
    
    Args:
        name: Logger name
        log_dir: Directory to store log files. If None, uses ~/.gsub/logs
    
    Returns:
        logging.Logger instance
    """
    logger = logging.getLogger(name)
    
    # Only configure if not already configured
    if logger.handlers:
        return logger
    
    logger.setLevel(logging.DEBUG)
    
    # Determine log directory
    if log_dir is None:
        log_dir = Path.home() / '.gsub' / 'logs'
    else:
        log_dir = Path(log_dir)
    
    # Create log directory if it doesn't exist
    log_dir.mkdir(parents=True, exist_ok=True)
    
    # Create log file with timestamp
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    log_file = log_dir / f'gsub_{timestamp}.log'
    
    # Create file handler
    file_handler = logging.FileHandler(log_file, encoding='utf-8')
    file_handler.setLevel(logging.DEBUG)
    
    # Create formatter
    formatter = logging.Formatter(
        '%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )
    file_handler.setFormatter(formatter)
    
    # Add handler to logger
    logger.addHandler(file_handler)
    
    # Clean up old log files (keep only last 10)
    _cleanup_old_logs(log_dir, keep=10)
    
    logger.info(f"Logger initialized. Log file: {log_file}")
    
    return logger


def _cleanup_old_logs(log_dir, keep=10):
    """Remove old log files, keeping only the most recent ones."""
    try:
        log_files = sorted(log_dir.glob('gsub_*.log'), key=lambda p: p.stat().st_mtime, reverse=True)
        for old_log in log_files[keep:]:
            old_log.unlink()
    except Exception as e:
        # Silently fail if cleanup doesn't work
        pass


def get_logger(name='gsub'):
    """Get the configured logger instance."""
    logger = logging.getLogger(name)
    if not logger.handlers:
        setup_logger(name)
    return logger
