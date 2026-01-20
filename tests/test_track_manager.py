"""Unit tests for track management functionality."""

import pytest
from unittest.mock import Mock, MagicMock, patch
import gi
gi.require_version('Gst', '1.0')
from gi.repository import Gst

from subtitle_editor.media.track_manager import TrackManager, TrackInfo


class TestTrackInfo:
    """Tests for TrackInfo dataclass."""

    @pytest.mark.unit
    def test_track_info_creation(self):
        """Test creating a TrackInfo object."""
        track = TrackInfo(
            index=0,
            title="English",
            language="eng",
            codec="aac",
            track_type="audio"
        )
        
        assert track.index == 0
        assert track.title == "English"
        assert track.language == "eng"
        assert track.codec == "aac"
        assert track.track_type == "audio"

    @pytest.mark.unit
    def test_track_info_defaults(self):
        """Test TrackInfo with default values."""
        track = TrackInfo(index=0)
        
        assert track.index == 0
        assert track.title is None
        assert track.language is None
        assert track.codec is None
        assert track.track_type == 'unknown'

    @pytest.mark.unit
    def test_track_info_str(self):
        """Test TrackInfo string representation."""
        track = TrackInfo(
            index=0,
            title="English",
            language="eng",
            codec="aac",
            track_type="audio"
        )
        
        str_repr = str(track)
        assert "Track 0" in str_repr
        assert "[eng]" in str_repr
        assert "English" in str_repr
        assert "(aac)" in str_repr

    @pytest.mark.unit
    def test_track_info_to_dict(self):
        """Test TrackInfo conversion to dictionary."""
        track = TrackInfo(
            index=0,
            title="English",
            language="eng",
            codec="aac",
            track_type="audio"
        )
        
        track_dict = track.to_dict()
        assert track_dict['index'] == 0
        assert track_dict['title'] == "English"
        assert track_dict['language'] == "eng"
        assert track_dict['codec'] == "aac"
        assert track_dict['track_type'] == "audio"


class TestTrackManager:
    """Tests for TrackManager class."""

    @pytest.mark.unit
    def test_init(self):
        """Test TrackManager initialization."""
        mock_player = Mock()
        manager = TrackManager(mock_player)
        
        assert manager.player == mock_player
        assert len(manager._audio_tracks) == 0
        assert len(manager._subtitle_tracks) == 0
        assert manager._current_audio_track == -1
        assert manager._current_subtitle_track == -1

    @pytest.mark.unit
    def test_detect_tracks_no_tracks(self):
        """Test detecting tracks when none are available."""
        mock_player = Mock()
        mock_player.get_property.side_effect = lambda prop: 0
        
        manager = TrackManager(mock_player)
        result = manager.detect_tracks()
        
        assert result is False  # Should retry

    @pytest.mark.unit
    def test_detect_tracks_with_audio(self):
        """Test detecting audio tracks."""
        mock_player = Mock()
        
        # Mock track counts
        def get_property(prop):
            if prop == "n-audio":
                return 2
            elif prop == "n-text":
                return 0
            elif prop == "current-audio":
                return 0
            elif prop == "current-text":
                return -1
            return 0
        
        mock_player.get_property.side_effect = get_property
        
        # Mock emit for getting tags
        def emit(signal, index):
            tags = Mock()
            tags.get_string.return_value = (True, "eng")
            return tags
        
        mock_player.emit.side_effect = emit
        
        manager = TrackManager(mock_player)
        result = manager.detect_tracks()
        
        assert result is True
        assert len(manager._audio_tracks) == 2
        assert len(manager._subtitle_tracks) == 0

    @pytest.mark.unit
    def test_detect_tracks_with_subtitles(self):
        """Test detecting subtitle tracks."""
        mock_player = Mock()
        
        # Mock track counts
        def get_property(prop):
            if prop == "n-audio":
                return 0
            elif prop == "n-text":
                return 1
            elif prop == "current-audio":
                return -1
            elif prop == "current-text":
                return -1
            return 0
        
        mock_player.get_property.side_effect = get_property
        
        # Mock emit for getting tags
        def emit(signal, index):
            tags = Mock()
            if signal == "get-text-tags":
                tags.get_string.side_effect = [
                    (True, "eng"),  # language
                    (True, "English Subtitles"),  # title
                    (True, "subrip")  # codec
                ]
            return tags
        
        mock_player.emit.side_effect = emit
        
        manager = TrackManager(mock_player)
        result = manager.detect_tracks()
        
        assert result is True
        assert len(manager._audio_tracks) == 0
        assert len(manager._subtitle_tracks) == 1

    @pytest.mark.unit
    def test_get_audio_tracks(self):
        """Test getting audio track list."""
        mock_player = Mock()
        manager = TrackManager(mock_player)
        
        # Add mock tracks
        manager._audio_tracks = [
            TrackInfo(0, "Track 1", "eng", "aac", "audio"),
            TrackInfo(1, "Track 2", "spa", "aac", "audio")
        ]
        
        tracks = manager.get_audio_tracks()
        assert len(tracks) == 2
        assert tracks[0].language == "eng"
        assert tracks[1].language == "spa"
        
        # Should return a copy
        tracks.append(TrackInfo(2, "Track 3", "fra", "aac", "audio"))
        assert len(manager._audio_tracks) == 2

    @pytest.mark.unit
    def test_get_subtitle_tracks(self):
        """Test getting subtitle track list."""
        mock_player = Mock()
        manager = TrackManager(mock_player)
        
        # Add mock tracks
        manager._subtitle_tracks = [
            TrackInfo(0, "English", "eng", "srt", "subtitle")
        ]
        
        tracks = manager.get_subtitle_tracks()
        assert len(tracks) == 1
        assert tracks[0].language == "eng"

    @pytest.mark.unit
    def test_get_all_tracks(self):
        """Test getting all tracks."""
        mock_player = Mock()
        manager = TrackManager(mock_player)
        
        manager._audio_tracks = [TrackInfo(0, track_type="audio")]
        manager._subtitle_tracks = [TrackInfo(0, track_type="subtitle")]
        
        audio, subtitles = manager.get_all_tracks()
        assert len(audio) == 1
        assert len(subtitles) == 1

    @pytest.mark.unit
    def test_has_tracks(self):
        """Test checking if tracks are available."""
        mock_player = Mock()
        manager = TrackManager(mock_player)
        
        has_audio, has_subs = manager.has_tracks()
        assert has_audio is False
        assert has_subs is False
        
        manager._audio_tracks = [TrackInfo(0, track_type="audio")]
        has_audio, has_subs = manager.has_tracks()
        assert has_audio is True
        assert has_subs is False
        
        manager._subtitle_tracks = [TrackInfo(0, track_type="subtitle")]
        has_audio, has_subs = manager.has_tracks()
        assert has_audio is True
        assert has_subs is True

    @pytest.mark.unit
    def test_set_audio_track(self):
        """Test setting audio track."""
        mock_player = Mock()
        manager = TrackManager(mock_player)
        
        manager._audio_tracks = [
            TrackInfo(0, track_type="audio"),
            TrackInfo(1, track_type="audio")
        ]
        
        result = manager.set_audio_track(1)
        
        assert result is True
        mock_player.set_property.assert_called_with("current-audio", 1)
        assert manager._current_audio_track == 1

    @pytest.mark.unit
    def test_set_audio_track_invalid_index(self):
        """Test setting invalid audio track."""
        mock_player = Mock()
        manager = TrackManager(mock_player)
        
        manager._audio_tracks = [TrackInfo(0, track_type="audio")]
        
        result = manager.set_audio_track(5)
        
        assert result is False

    @pytest.mark.unit
    def test_set_subtitle_track(self):
        """Test setting subtitle track."""
        mock_player = Mock()
        manager = TrackManager(mock_player)
        
        manager._subtitle_tracks = [TrackInfo(0, track_type="subtitle")]
        
        result = manager.set_subtitle_track(0)
        
        assert result is True
        mock_player.set_property.assert_called_with("current-text", 0)
        assert manager._current_subtitle_track == 0

    @pytest.mark.unit
    def test_set_subtitle_track_disable(self):
        """Test disabling subtitle track."""
        mock_player = Mock()
        manager = TrackManager(mock_player)
        
        result = manager.set_subtitle_track(-1)
        
        assert result is True
        mock_player.set_property.assert_called_with("current-text", -1)
        assert manager._current_subtitle_track == -1

    @pytest.mark.unit
    def test_get_current_tracks(self):
        """Test getting current track indices."""
        mock_player = Mock()
        manager = TrackManager(mock_player)
        
        manager._current_audio_track = 2
        manager._current_subtitle_track = 1
        
        assert manager.get_current_audio_track() == 2
        assert manager.get_current_subtitle_track() == 1

    @pytest.mark.unit
    def test_get_track_info(self):
        """Test getting specific track information."""
        mock_player = Mock()
        manager = TrackManager(mock_player)
        
        audio_track = TrackInfo(0, "English", "eng", track_type="audio")
        subtitle_track = TrackInfo(0, "Spanish", "spa", track_type="subtitle")
        
        manager._audio_tracks = [audio_track]
        manager._subtitle_tracks = [subtitle_track]
        
        # Get valid tracks
        assert manager.get_audio_track_info(0) == audio_track
        assert manager.get_subtitle_track_info(0) == subtitle_track
        
        # Get invalid tracks
        assert manager.get_audio_track_info(5) is None
        assert manager.get_subtitle_track_info(-1) is None

    @pytest.mark.unit
    def test_clear(self):
        """Test clearing all track information."""
        mock_player = Mock()
        manager = TrackManager(mock_player)
        
        manager._audio_tracks = [TrackInfo(0, track_type="audio")]
        manager._subtitle_tracks = [TrackInfo(0, track_type="subtitle")]
        manager._current_audio_track = 0
        manager._current_subtitle_track = 0
        
        manager.clear()
        
        assert len(manager._audio_tracks) == 0
        assert len(manager._subtitle_tracks) == 0
        assert manager._current_audio_track == -1
        assert manager._current_subtitle_track == -1

    @pytest.mark.unit
    def test_get_audio_track_info_with_tags(self):
        """Test getting audio track info with full tag information."""
        mock_player = Mock()
        
        # Mock emit to return tags
        def emit(signal, index):
            tags = Mock()
            calls = []
            def get_string_side_effect(tag):
                if tag == Gst.TAG_LANGUAGE_CODE:
                    return (True, "eng")
                elif tag == Gst.TAG_TITLE:
                    return (True, "English Audio")
                elif tag == Gst.TAG_AUDIO_CODEC:
                    return (True, "AAC")
                return (False, None)
            tags.get_string.side_effect = get_string_side_effect
            return tags
        
        mock_player.emit.side_effect = emit
        
        manager = TrackManager(mock_player)
        track_info = manager._get_audio_track_info(0)
        
        assert track_info.index == 0
        assert track_info.language == "eng"
        assert track_info.title == "English Audio"
        assert track_info.codec == "AAC"
        assert track_info.track_type == "audio"
