"""
Track management for audio and subtitle tracks in video files.

Provides a clean interface for detecting, selecting, and managing media tracks.
"""

import gi
gi.require_version('Gst', '1.0')
from gi.repository import Gst
from typing import List, Dict, Optional, Tuple
from dataclasses import dataclass


@dataclass
class TrackInfo:
    """Information about a media track."""
    index: int
    title: Optional[str] = None
    language: Optional[str] = None
    codec: Optional[str] = None
    track_type: str = 'unknown'  # 'audio', 'subtitle', 'video'
    
    def __str__(self):
        parts = [f"Track {self.index}"]
        if self.language:
            parts.append(f"[{self.language}]")
        if self.title:
            parts.append(f"- {self.title}")
        if self.codec:
            parts.append(f"({self.codec})")
        return " ".join(parts)
    
    def to_dict(self) -> Dict:
        """Convert to dictionary for serialization."""
        return {
            'index': self.index,
            'title': self.title,
            'language': self.language,
            'codec': self.codec,
            'track_type': self.track_type
        }


class TrackManager:
    """Manages audio and subtitle tracks for a GStreamer playbin."""
    
    def __init__(self, player):
        """
        Initialize the TrackManager.
        
        Args:
            player: GStreamer playbin element
        """
        self.player = player
        self._audio_tracks: List[TrackInfo] = []
        self._subtitle_tracks: List[TrackInfo] = []
        self._current_audio_track: int = -1
        self._current_subtitle_track: int = -1
    
    def detect_tracks(self) -> bool:
        """
        Detect available audio and subtitle tracks in the loaded media.
        
        Returns:
            True if tracks were detected, False if detection should be retried
        """
        if not self.player:
            return False
        
        # Get number of tracks
        n_audio = self.player.get_property("n-audio")
        n_text = self.player.get_property("n-text")
        
        print(f"[TrackManager] Found {n_audio} audio tracks, {n_text} subtitle tracks")
        
        if n_audio == 0 and n_text == 0:
            return False  # No tracks found yet, retry
        
        # Get audio tracks
        self._audio_tracks = []
        for i in range(n_audio):
            track_info = self._get_audio_track_info(i)
            self._audio_tracks.append(track_info)
            print(f"[TrackManager] Audio: {track_info}")
        
        # Get subtitle tracks
        self._subtitle_tracks = []
        for i in range(n_text):
            track_info = self._get_subtitle_track_info(i)
            self._subtitle_tracks.append(track_info)
            print(f"[TrackManager] Subtitle: {track_info}")
        
        # Get current tracks
        self._current_audio_track = self.player.get_property("current-audio")
        self._current_subtitle_track = self.player.get_property("current-text")
        
        print(f"[TrackManager] Current audio: {self._current_audio_track}, "
              f"subtitle: {self._current_subtitle_track}")
        
        return True
    
    def _get_audio_track_info(self, index: int) -> TrackInfo:
        """
        Get information about an audio track.
        
        Args:
            index: Track index
            
        Returns:
            TrackInfo object with track details
        """
        track_info = TrackInfo(index=index, track_type='audio')
        
        try:
            # Get tags using emit signal
            tags = self.player.emit("get-audio-tags", index)
            if tags:
                # Get language
                success, language = tags.get_string(Gst.TAG_LANGUAGE_CODE)
                if success:
                    track_info.language = language
                
                # Get title
                success, title = tags.get_string(Gst.TAG_TITLE)
                if success:
                    track_info.title = title
                
                # Get codec
                success, codec = tags.get_string(Gst.TAG_AUDIO_CODEC)
                if success:
                    track_info.codec = codec
        except Exception as e:
            print(f"[TrackManager] Error getting audio track {index} info: {e}")
        
        return track_info
    
    def _get_subtitle_track_info(self, index: int) -> TrackInfo:
        """
        Get information about a subtitle track.
        
        Args:
            index: Track index
            
        Returns:
            TrackInfo object with track details
        """
        track_info = TrackInfo(index=index, track_type='subtitle')
        
        try:
            # Get tags using emit signal
            tags = self.player.emit("get-text-tags", index)
            if tags:
                # Get language
                success, language = tags.get_string(Gst.TAG_LANGUAGE_CODE)
                if success:
                    track_info.language = language
                
                # Get title
                success, title = tags.get_string(Gst.TAG_TITLE)
                if success:
                    track_info.title = title
                
                # Get codec
                success, codec = tags.get_string(Gst.TAG_SUBTITLE_CODEC)
                if not success:
                    success, codec = tags.get_string(Gst.TAG_CODEC)
                if success:
                    track_info.codec = codec
        except Exception as e:
            print(f"[TrackManager] Error getting subtitle track {index} info: {e}")
        
        return track_info
    
    def get_audio_tracks(self) -> List[TrackInfo]:
        """
        Get list of available audio tracks.
        
        Returns:
            List of TrackInfo objects for audio tracks
        """
        return self._audio_tracks.copy()
    
    def get_subtitle_tracks(self) -> List[TrackInfo]:
        """
        Get list of available subtitle tracks.
        
        Returns:
            List of TrackInfo objects for subtitle tracks
        """
        return self._subtitle_tracks.copy()
    
    def get_all_tracks(self) -> Tuple[List[TrackInfo], List[TrackInfo]]:
        """
        Get all available tracks.
        
        Returns:
            Tuple of (audio_tracks, subtitle_tracks)
        """
        return (self.get_audio_tracks(), self.get_subtitle_tracks())
    
    def has_tracks(self) -> Tuple[bool, bool]:
        """
        Check if media has audio or subtitle tracks.
        
        Returns:
            Tuple of (has_audio, has_subtitles)
        """
        return (len(self._audio_tracks) > 0, len(self._subtitle_tracks) > 0)
    
    def set_audio_track(self, track_index: int) -> bool:
        """
        Set the current audio track.
        
        Args:
            track_index: Index of audio track to select (-1 to disable)
            
        Returns:
            True if track was set successfully
        """
        if not self.player:
            return False
        
        if track_index >= len(self._audio_tracks) and track_index != -1:
            print(f"[TrackManager] Invalid audio track index: {track_index}")
            return False
        
        print(f"[TrackManager] Setting audio track to {track_index}")
        self.player.set_property("current-audio", track_index)
        self._current_audio_track = track_index
        return True
    
    def set_subtitle_track(self, track_index: int) -> bool:
        """
        Set the current subtitle track.
        
        Args:
            track_index: Index of subtitle track to select (-1 to disable)
            
        Returns:
            True if track was set successfully
        """
        if not self.player:
            return False
        
        if track_index >= len(self._subtitle_tracks) and track_index != -1:
            print(f"[TrackManager] Invalid subtitle track index: {track_index}")
            return False
        
        print(f"[TrackManager] Setting subtitle track to {track_index}")
        self.player.set_property("current-text", track_index)
        self._current_subtitle_track = track_index
        return True
    
    def get_current_audio_track(self) -> int:
        """
        Get the currently selected audio track index.
        
        Returns:
            Current audio track index (-1 if none)
        """
        return self._current_audio_track
    
    def get_current_subtitle_track(self) -> int:
        """
        Get the currently selected subtitle track index.
        
        Returns:
            Current subtitle track index (-1 if none)
        """
        return self._current_subtitle_track
    
    def get_audio_track_info(self, index: int) -> Optional[TrackInfo]:
        """
        Get information about a specific audio track.
        
        Args:
            index: Track index
            
        Returns:
            TrackInfo object or None if index is invalid
        """
        if 0 <= index < len(self._audio_tracks):
            return self._audio_tracks[index]
        return None
    
    def get_subtitle_track_info(self, index: int) -> Optional[TrackInfo]:
        """
        Get information about a specific subtitle track.
        
        Args:
            index: Track index
            
        Returns:
            TrackInfo object or None if index is invalid
        """
        if 0 <= index < len(self._subtitle_tracks):
            return self._subtitle_tracks[index]
        return None
    
    def clear(self):
        """Clear all track information."""
        self._audio_tracks.clear()
        self._subtitle_tracks.clear()
        self._current_audio_track = -1
        self._current_subtitle_track = -1
