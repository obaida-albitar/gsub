"""Unit tests for media extraction functionality."""

import pytest
import tempfile
import os
from unittest.mock import Mock, patch, MagicMock
from subtitle_editor.media.media_extractor import MediaExtractor, ExtractionError


class TestMediaExtractor:
    """Tests for MediaExtractor class."""

    @pytest.mark.unit
    def test_init_success(self):
        """Test MediaExtractor initialization with ffmpeg available."""
        with patch('subprocess.run') as mock_run:
            mock_run.return_value = Mock(returncode=0)
            extractor = MediaExtractor()
            assert extractor.ffmpeg_path == 'ffmpeg'
            mock_run.assert_called_once()

    @pytest.mark.unit
    def test_init_ffmpeg_not_found(self):
        """Test MediaExtractor initialization when ffmpeg is not found."""
        with patch('subprocess.run', side_effect=FileNotFoundError):
            with pytest.raises(ExtractionError, match="ffmpeg not found"):
                MediaExtractor()

    @pytest.mark.unit
    def test_init_ffmpeg_not_working(self):
        """Test MediaExtractor initialization when ffmpeg returns error."""
        with patch('subprocess.run') as mock_run:
            mock_run.return_value = Mock(returncode=1)
            with pytest.raises(ExtractionError, match="not working properly"):
                MediaExtractor()

    @pytest.mark.unit
    def test_extract_subtitle_track_success(self):
        """Test successful subtitle extraction."""
        with patch('subprocess.run') as mock_run:
            # Mock ffmpeg verification
            mock_run.return_value = Mock(returncode=0)
            extractor = MediaExtractor()
            
            # Mock the extraction
            with tempfile.NamedTemporaryFile(mode='w', suffix='.srt', delete=False) as f:
                output_path = f.name
                f.write("Test subtitle content")
            
            try:
                with patch('os.path.exists', return_value=True):
                    with patch('os.path.getsize', return_value=100):
                        result = extractor.extract_subtitle_track(
                            '/path/to/video.mp4',
                            0,
                            output_path,
                            format='srt'
                        )
                        assert result is True
            finally:
                os.unlink(output_path)

    @pytest.mark.unit
    def test_extract_subtitle_track_video_not_found(self):
        """Test extraction with non-existent video file."""
        with patch('subprocess.run') as mock_run:
            mock_run.return_value = Mock(returncode=0)
            extractor = MediaExtractor()
            
            with pytest.raises(ExtractionError, match="Video file not found"):
                extractor.extract_subtitle_track(
                    '/nonexistent/video.mp4',
                    0,
                    '/tmp/output.srt'
                )

    @pytest.mark.unit
    def test_extract_subtitle_track_invalid_track(self):
        """Test extraction with invalid track index."""
        with patch('subprocess.run') as mock_run:
            # Mock ffmpeg verification
            mock_run.return_value = Mock(returncode=0)
            extractor = MediaExtractor()
            
            # Mock extraction failure
            mock_run.return_value = Mock(returncode=1, stderr=b'Invalid stream specifier')
            
            with patch('os.path.exists', return_value=True):
                with pytest.raises(ExtractionError, match="ffmpeg failed"):
                    extractor.extract_subtitle_track(
                        '/path/to/video.mp4',
                        99,
                        '/tmp/output.srt'
                    )

    @pytest.mark.unit
    def test_extract_subtitle_track_timeout(self):
        """Test extraction timeout."""
        with patch('subprocess.run') as mock_run:
            # Mock ffmpeg verification
            mock_run.return_value = Mock(returncode=0)
            extractor = MediaExtractor()
            
            # Mock timeout
            from subprocess import TimeoutExpired
            mock_run.side_effect = TimeoutExpired('ffmpeg', 30)
            
            with patch('os.path.exists', return_value=True):
                with pytest.raises(ExtractionError, match="timed out"):
                    extractor.extract_subtitle_track(
                        '/path/to/video.mp4',
                        0,
                        '/tmp/output.srt',
                        timeout=1
                    )

    @pytest.mark.unit
    def test_extract_audio_track_success(self):
        """Test successful audio extraction."""
        with patch('subprocess.run') as mock_run:
            # Mock ffmpeg verification
            mock_run.return_value = Mock(returncode=0)
            extractor = MediaExtractor()
            
            # Mock the extraction
            with tempfile.NamedTemporaryFile(mode='wb', suffix='.mp3', delete=False) as f:
                output_path = f.name
                f.write(b"Test audio content")
            
            try:
                with patch('os.path.exists', return_value=True):
                    with patch('os.path.getsize', return_value=1000):
                        result = extractor.extract_audio_track(
                            '/path/to/video.mp4',
                            0,
                            output_path,
                            format='mp3'
                        )
                        assert result is True
            finally:
                os.unlink(output_path)

    @pytest.mark.unit
    def test_extract_audio_track_different_formats(self):
        """Test audio extraction with different formats."""
        with patch('subprocess.run') as mock_run:
            mock_run.return_value = Mock(returncode=0)
            extractor = MediaExtractor()
            
            formats = ['mp3', 'aac', 'wav']
            
            for fmt in formats:
                with patch('os.path.exists', return_value=True):
                    with patch('os.path.getsize', return_value=1000):
                        result = extractor.extract_audio_track(
                            '/path/to/video.mp4',
                            0,
                            f'/tmp/output.{fmt}',
                            format=fmt
                        )
                        # Should not raise exception
                        assert result is True or isinstance(result, bool)

    @pytest.mark.unit
    def test_clean_subtitle_file_removes_html_tags(self):
        """Test cleaning HTML tags from subtitle file."""
        with patch('subprocess.run') as mock_run:
            mock_run.return_value = Mock(returncode=0)
            extractor = MediaExtractor()
            
            # Create test file with HTML tags
            with tempfile.NamedTemporaryFile(mode='w', suffix='.srt', delete=False, encoding='utf-8') as f:
                f.write("""1
00:00:01,000 --> 00:00:02,000
<font color="red">Hello</font> <b>World</b>

2
00:00:03,000 --> 00:00:04,000
<i>Italic text</i> and <u>underlined</u>
""")
                temp_path = f.name
            
            try:
                extractor.clean_subtitle_file(temp_path)
                
                with open(temp_path, 'r', encoding='utf-8') as f:
                    content = f.read()
                
                # Check that HTML tags are removed
                assert '<font' not in content
                assert '</font>' not in content
                assert '<b>' not in content
                assert '</b>' not in content
                assert '<i>' not in content
                assert '</i>' not in content
                assert '<u>' not in content
                assert '</u>' not in content
                
                # Check that text content is preserved
                assert 'Hello' in content
                assert 'World' in content
                assert 'Italic text' in content
                
            finally:
                os.unlink(temp_path)

    @pytest.mark.unit
    def test_clean_subtitle_file_fixes_ass_newlines(self):
        """Test fixing ASS format newlines in subtitle file."""
        with patch('subprocess.run') as mock_run:
            mock_run.return_value = Mock(returncode=0)
            extractor = MediaExtractor()
            
            # Create test file with ASS newlines
            with tempfile.NamedTemporaryFile(mode='w', suffix='.srt', delete=False, encoding='utf-8') as f:
                f.write(r"""1
00:00:01,000 --> 00:00:02,000
Line one\NLine two
""")
                temp_path = f.name
            
            try:
                extractor.clean_subtitle_file(temp_path)
                
                with open(temp_path, 'r', encoding='utf-8') as f:
                    content = f.read()
                
                # Check that \N is converted to actual newline
                assert r'\N' not in content
                assert 'Line one\nLine two' in content
                
            finally:
                os.unlink(temp_path)

    @pytest.mark.unit
    def test_clean_subtitle_file_removes_ass_codes(self):
        """Test removing ASS override codes from subtitle file."""
        with patch('subprocess.run') as mock_run:
            mock_run.return_value = Mock(returncode=0)
            extractor = MediaExtractor()
            
            # Create test file with ASS codes
            with tempfile.NamedTemporaryFile(mode='w', suffix='.srt', delete=False, encoding='utf-8') as f:
                f.write(r"""1
00:00:01,000 --> 00:00:02,000
{\i1}Italic{\i0} and {\b1}bold{\b0}
""")
                temp_path = f.name
            
            try:
                extractor.clean_subtitle_file(temp_path)
                
                with open(temp_path, 'r', encoding='utf-8') as f:
                    content = f.read()
                
                # Check that ASS codes are removed
                assert r'{\i1}' not in content
                assert r'{\i0}' not in content
                assert r'{\b1}' not in content
                assert r'{\b0}' not in content
                
                # Check that text content is preserved
                assert 'Italic' in content
                assert 'bold' in content
                
            finally:
                os.unlink(temp_path)

    @pytest.mark.unit
    def test_clean_subtitle_file_error_handling(self):
        """Test error handling in clean_subtitle_file."""
        with patch('subprocess.run') as mock_run:
            mock_run.return_value = Mock(returncode=0)
            extractor = MediaExtractor()
            
            with pytest.raises(ExtractionError, match="Failed to clean"):
                extractor.clean_subtitle_file('/nonexistent/file.srt')

    @pytest.mark.unit
    def test_get_stream_info_success(self):
        """Test getting stream information from video file."""
        with patch('subprocess.run') as mock_run:
            # Mock ffmpeg verification
            mock_run.return_value = Mock(returncode=0)
            extractor = MediaExtractor()
            
            # Mock ffprobe output
            mock_output = b'{"streams": [{"codec_type": "video", "width": 1920, "height": 1080}]}'
            mock_run.return_value = Mock(returncode=0, stdout=mock_output)
            
            info = extractor.get_stream_info('/path/to/video.mp4')
            
            assert 'streams' in info
            assert len(info['streams']) > 0

    @pytest.mark.unit
    def test_get_stream_info_timeout(self):
        """Test stream info query timeout."""
        with patch('subprocess.run') as mock_run:
            # Mock ffmpeg verification
            mock_run.return_value = Mock(returncode=0)
            extractor = MediaExtractor()
            
            # Mock timeout
            from subprocess import TimeoutExpired
            mock_run.side_effect = TimeoutExpired('ffprobe', 10)
            
            with pytest.raises(ExtractionError, match="timed out"):
                extractor.get_stream_info('/path/to/video.mp4')

    @pytest.mark.unit
    def test_extract_subtitle_formats(self):
        """Test extraction with different subtitle formats."""
        with patch('subprocess.run') as mock_run:
            mock_run.return_value = Mock(returncode=0)
            extractor = MediaExtractor()
            
            formats = ['srt', 'ass', 'vtt']
            
            for fmt in formats:
                with patch('os.path.exists', return_value=True):
                    with patch('os.path.getsize', return_value=100):
                        result = extractor.extract_subtitle_track(
                            '/path/to/video.mp4',
                            0,
                            f'/tmp/output.{fmt}',
                            format=fmt
                        )
                        assert result is True or isinstance(result, bool)
