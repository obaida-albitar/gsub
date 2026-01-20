"""
Media extraction utilities for extracting audio and subtitle tracks from video files.

Uses ffmpeg for reliable extraction across different container formats.
"""

import os
import subprocess
import tempfile
from pathlib import Path
from typing import Optional, Callable, List, Dict
import re
from subtitle_editor.logger import get_logger

logger = get_logger(__name__)


class ExtractionError(Exception):
    """Exception raised when media extraction fails."""
    pass


class MediaExtractor:
    """Handles extraction of audio and subtitle tracks from video files using ffmpeg."""
    
    def __init__(self, ffmpeg_path: str = 'ffmpeg'):
        """
        Initialize the MediaExtractor.
        
        Args:
            ffmpeg_path: Path to ffmpeg binary (default: 'ffmpeg' from PATH)
        """
        self.ffmpeg_path = ffmpeg_path
        self._verify_ffmpeg()
    
    def _verify_ffmpeg(self) -> bool:
        """
        Verify that ffmpeg is available.
        
        Returns:
            True if ffmpeg is available
            
        Raises:
            ExtractionError: If ffmpeg is not found
        """
        try:
            result = subprocess.run(
                [self.ffmpeg_path, '-version'],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=5
            )
            if result.returncode != 0:
                raise ExtractionError("ffmpeg is not working properly")
            return True
        except FileNotFoundError:
            raise ExtractionError(
                "ffmpeg not found. Please install ffmpeg to use extraction features."
            )
        except subprocess.TimeoutExpired:
            raise ExtractionError("ffmpeg verification timed out")
    
    def extract_subtitle_track(
        self,
        video_path: str,
        track_index: int,
        output_path: str,
        format: str = 'srt',
        timeout: int = 30
    ) -> bool:
        """
        Extract a subtitle track from a video file.
        
        Args:
            video_path: Path to the input video file
            track_index: Index of the subtitle track to extract (0-based)
            output_path: Path where the extracted subtitle file should be saved
            format: Output subtitle format ('srt', 'ass', 'vtt', etc.)
            timeout: Maximum time in seconds to wait for extraction
            
        Returns:
            True if extraction succeeded, False otherwise
            
        Raises:
            ExtractionError: If extraction fails with error details
        """
        if not os.path.exists(video_path):
            raise ExtractionError(f"Video file not found: {video_path}")
        
        # Build ffmpeg command
        # -i: input file
        # -map 0:s:N: select subtitle stream N
        # -c:s: subtitle codec (copy to preserve original, or specify format)
        cmd = [
            self.ffmpeg_path,
            '-i', video_path,
            '-map', f'0:s:{track_index}',
        ]
        
        # For subtitle format conversion
        if format.lower() == 'srt':
            cmd.extend(['-c:s', 'srt', '-f', 'srt'])
        elif format.lower() == 'ass':
            cmd.extend(['-c:s', 'ass', '-f', 'ass'])
        elif format.lower() == 'vtt':
            cmd.extend(['-c:s', 'webvtt', '-f', 'webvtt'])
        else:
            # Try to copy the subtitle as-is
            cmd.extend(['-c:s', 'copy'])
        
        cmd.extend([
            '-y',  # Overwrite output file
            output_path
        ])
        
        logger.info(f"Running: {' '.join(cmd)}")
        
        try:
            result = subprocess.run(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=timeout
            )
            
            if result.returncode == 0:
                # Verify output file was created and has content
                if os.path.exists(output_path) and os.path.getsize(output_path) > 0:
                    logger.info(f"Successfully extracted to: {output_path}")
                    return True
                else:
                    raise ExtractionError("Output file was not created or is empty")
            else:
                error = result.stderr.decode('utf-8', errors='ignore')
                raise ExtractionError(f"ffmpeg failed: {error}")
                
        except subprocess.TimeoutExpired:
            raise ExtractionError(f"Extraction timed out after {timeout} seconds")
        except Exception as e:
            raise ExtractionError(f"Extraction failed: {str(e)}")
    
    def extract_audio_track(
        self,
        video_path: str,
        track_index: int,
        output_path: str,
        format: str = 'mp3',
        timeout: int = 60
    ) -> bool:
        """
        Extract an audio track from a video file.
        
        Args:
            video_path: Path to the input video file
            track_index: Index of the audio track to extract (0-based)
            output_path: Path where the extracted audio file should be saved
            format: Output audio format ('mp3', 'aac', 'wav', etc.)
            timeout: Maximum time in seconds to wait for extraction
            
        Returns:
            True if extraction succeeded, False otherwise
            
        Raises:
            ExtractionError: If extraction fails with error details
        """
        if not os.path.exists(video_path):
            raise ExtractionError(f"Video file not found: {video_path}")
        
        # Build ffmpeg command
        cmd = [
            self.ffmpeg_path,
            '-i', video_path,
            '-map', f'0:a:{track_index}',
            '-vn',  # No video
        ]
        
        # Audio codec based on format
        if format.lower() == 'mp3':
            cmd.extend(['-c:a', 'libmp3lame', '-q:a', '2'])
        elif format.lower() == 'aac':
            cmd.extend(['-c:a', 'aac', '-b:a', '192k'])
        elif format.lower() == 'wav':
            cmd.extend(['-c:a', 'pcm_s16le'])
        else:
            cmd.extend(['-c:a', 'copy'])
        
        cmd.extend([
            '-y',  # Overwrite output file
            output_path
        ])
        
        logger.info(f"Running: {' '.join(cmd)}")
        
        try:
            result = subprocess.run(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=timeout
            )
            
            if result.returncode == 0:
                if os.path.exists(output_path) and os.path.getsize(output_path) > 0:
                    logger.info(f"Successfully extracted to: {output_path}")
                    return True
                else:
                    raise ExtractionError("Output file was not created or is empty")
            else:
                error = result.stderr.decode('utf-8', errors='ignore')
                raise ExtractionError(f"ffmpeg failed: {error}")
                
        except subprocess.TimeoutExpired:
            raise ExtractionError(f"Extraction timed out after {timeout} seconds")
        except Exception as e:
            raise ExtractionError(f"Extraction failed: {str(e)}")
    
    def clean_subtitle_file(self, subtitle_path: str) -> None:
        """
        Clean HTML tags and formatting issues from extracted subtitle file.
        
        Many subtitle tracks contain HTML formatting tags like <font>, <b>, <i>
        which can cause display issues. This method strips those tags and fixes
        common formatting problems.
        
        Args:
            subtitle_path: Path to the subtitle file to clean
            
        Raises:
            ExtractionError: If cleaning fails
        """
        try:
            with open(subtitle_path, 'r', encoding='utf-8') as f:
                content = f.read()
            
            # Remove common HTML tags while preserving text
            content = re.sub(r'<font[^>]*>', '', content)
            content = re.sub(r'</font>', '', content)
            content = re.sub(r'<b>', '', content)
            content = re.sub(r'</b>', '', content)
            content = re.sub(r'<i>', '', content)
            content = re.sub(r'</i>', '', content)
            content = re.sub(r'<u>', '', content)
            content = re.sub(r'</u>', '', content)
            
            # Fix ASS format newlines: backslash-N should be actual newlines in SRT
            content = content.replace(r'\N', '\n')
            
            # Remove ASS drawing commands and style overrides
            content = re.sub(r'\{\\[^}]*\}', '', content)
            
            # Fix lines that have only one word (likely formatting issue)
            lines = content.split('\n')
            fixed_lines = []
            i = 0
            while i < len(lines):
                line = lines[i]
                # If line is subtitle text (not number, not timestamp, not empty)
                if line.strip() and not line.strip().isdigit() and '-->' not in line:
                    # Check if it's suspiciously short (single word)
                    if len(line.strip().split()) == 1 and i + 1 < len(lines):
                        # Look ahead to see if next line is also short text
                        next_line = lines[i + 1]
                        if next_line.strip() and not next_line.strip().isdigit() and '-->' not in next_line:
                            # Merge with next line
                            fixed_lines.append(line.rstrip() + ' ' + next_line.lstrip())
                            i += 2
                            continue
                fixed_lines.append(line)
                i += 1
            
            content = '\n'.join(fixed_lines)
            
            # Write cleaned content back
            with open(subtitle_path, 'w', encoding='utf-8') as f:
                f.write(content)
            
            logger.info(f"Cleaned subtitle file: {subtitle_path}")
            
        except Exception as e:
            raise ExtractionError(f"Failed to clean subtitle file: {str(e)}")
    
    def get_stream_info(self, video_path: str) -> Dict:
        """
        Get information about streams in a video file using ffprobe.
        
        Args:
            video_path: Path to the video file
            
        Returns:
            Dictionary containing stream information
            
        Raises:
            ExtractionError: If ffprobe fails
        """
        ffprobe_path = self.ffmpeg_path.replace('ffmpeg', 'ffprobe')
        
        cmd = [
            ffprobe_path,
            '-v', 'quiet',
            '-print_format', 'json',
            '-show_streams',
            video_path
        ]
        
        try:
            result = subprocess.run(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=10
            )
            
            if result.returncode == 0:
                import json
                return json.loads(result.stdout.decode('utf-8'))
            else:
                raise ExtractionError("Failed to get stream information")
                
        except subprocess.TimeoutExpired:
            raise ExtractionError("Stream info query timed out")
        except Exception as e:
            raise ExtractionError(f"Failed to get stream info: {str(e)}")
