"""
Concrete command implementations for subtitle editing operations.
"""

from typing import List
from subtitle_editor.commands.command import Command
from subtitle_editor.models import SubtitleEntry, SubtitleDocument, TimeCode


class AddEntryCommand(Command):
    """Command to add a new subtitle entry."""
    
    def __init__(self, document: SubtitleDocument, entry: SubtitleEntry, position: int = -1):
        """
        Initialize the add entry command.
        
        Args:
            document: The subtitle document
            entry: The entry to add
            position: Position to insert (-1 for end)
        """
        self.document = document
        self.entry = entry
        self.position = position if position >= 0 else len(document.entries)
    
    def execute(self):
        """Add the entry to the document."""
        if self.position >= len(self.document.entries):
            self.document.entries.append(self.entry)
        else:
            self.document.entries.insert(self.position, self.entry)
        self.document.reindex()
        self.document.modified = True
    
    def undo(self):
        """Remove the added entry."""
        if self.position < len(self.document.entries):
            self.document.entries.pop(self.position)
            self.document.reindex()
            self.document.modified = True
    
    def description(self) -> str:
        return f"Add subtitle at {self.entry.start_time}"


class RemoveEntryCommand(Command):
    """Command to remove a subtitle entry."""
    
    def __init__(self, document: SubtitleDocument, position: int):
        """
        Initialize the remove entry command.
        
        Args:
            document: The subtitle document
            position: Index of the entry to remove
        """
        self.document = document
        self.position = position
        self.removed_entry = None
    
    def execute(self):
        """Remove the entry from the document."""
        if 0 <= self.position < len(self.document.entries):
            self.removed_entry = self.document.entries.pop(self.position)
            self.document.reindex()
            self.document.modified = True
    
    def undo(self):
        """Restore the removed entry."""
        if self.removed_entry:
            self.document.entries.insert(self.position, self.removed_entry)
            self.document.reindex()
            self.document.modified = True
    
    def description(self) -> str:
        return f"Remove subtitle #{self.position + 1}"


class EditTextCommand(Command):
    """Command to edit subtitle text."""
    
    def __init__(self, document: SubtitleDocument, position: int, new_text: str):
        """
        Initialize the edit text command.
        
        Args:
            document: The subtitle document
            position: Index of the entry to edit
            new_text: New text content
        """
        self.document = document
        self.position = position
        self.new_text = new_text
        self.old_text = None
    
    def execute(self):
        """Change the subtitle text."""
        if 0 <= self.position < len(self.document.entries):
            entry = self.document.entries[self.position]
            self.old_text = entry.text
            entry.text = self.new_text
            self.document.modified = True
    
    def undo(self):
        """Restore the original text."""
        if self.old_text is not None and 0 <= self.position < len(self.document.entries):
            self.document.entries[self.position].text = self.old_text
            self.document.modified = True
    
    def description(self) -> str:
        return f"Edit text of subtitle #{self.position + 1}"


class EditTimingCommand(Command):
    """Command to edit subtitle timing."""
    
    def __init__(self, document: SubtitleDocument, position: int, 
                 new_start: TimeCode = None, new_end: TimeCode = None):
        """
        Initialize the edit timing command.
        
        Args:
            document: The subtitle document
            position: Index of the entry to edit
            new_start: New start time (None to keep current)
            new_end: New end time (None to keep current)
        """
        self.document = document
        self.position = position
        self.new_start = new_start
        self.new_end = new_end
        self.old_start = None
        self.old_end = None
    
    def execute(self):
        """Change the subtitle timing."""
        if 0 <= self.position < len(self.document.entries):
            entry = self.document.entries[self.position]
            self.old_start = entry.start_time
            self.old_end = entry.end_time
            
            if self.new_start:
                entry.start_time = self.new_start
            if self.new_end:
                entry.end_time = self.new_end
            
            self.document.modified = True
    
    def undo(self):
        """Restore the original timing."""
        if self.old_start is not None and 0 <= self.position < len(self.document.entries):
            entry = self.document.entries[self.position]
            entry.start_time = self.old_start
            entry.end_time = self.old_end
            self.document.modified = True
    
    def description(self) -> str:
        return f"Edit timing of subtitle #{self.position + 1}"


class DuplicateEntryCommand(Command):
    """Command to duplicate a subtitle entry."""
    
    def __init__(self, document: SubtitleDocument, position: int):
        """
        Initialize the duplicate entry command.
        
        Args:
            document: The subtitle document
            position: Index of the entry to duplicate
        """
        self.document = document
        self.position = position
        self.new_position = position + 1
    
    def execute(self):
        """Duplicate the entry."""
        if 0 <= self.position < len(self.document.entries):
            original = self.document.entries[self.position]
            
            # Create a copy with adjusted timing
            duration = original.duration_ms
            new_start_ms = original.end_time.total_milliseconds + 100  # 100ms gap
            new_end_ms = new_start_ms + duration
            
            duplicate = SubtitleEntry(
                index=original.index + 1,
                start_time=TimeCode.from_milliseconds(new_start_ms),
                end_time=TimeCode.from_milliseconds(new_end_ms),
                text=original.text,
                style=original.style
            )
            
            self.document.entries.insert(self.new_position, duplicate)
            self.document.reindex()
            self.document.modified = True
    
    def undo(self):
        """Remove the duplicated entry."""
        if self.new_position < len(self.document.entries):
            self.document.entries.pop(self.new_position)
            self.document.reindex()
            self.document.modified = True
    
    def description(self) -> str:
        return f"Duplicate subtitle #{self.position + 1}"


class MoveEntryCommand(Command):
    """Command to move a subtitle entry to a different position."""
    
    def __init__(self, document: SubtitleDocument, from_position: int, to_position: int):
        """
        Initialize the move entry command.
        
        Args:
            document: The subtitle document
            from_position: Current index
            to_position: Target index
        """
        self.document = document
        self.from_position = from_position
        self.to_position = to_position
    
    def execute(self):
        """Move the entry."""
        if (0 <= self.from_position < len(self.document.entries) and
            0 <= self.to_position < len(self.document.entries)):
            entry = self.document.entries.pop(self.from_position)
            self.document.entries.insert(self.to_position, entry)
            self.document.reindex()
            self.document.modified = True
    
    def undo(self):
        """Move the entry back."""
        if (0 <= self.to_position < len(self.document.entries) and
            0 <= self.from_position < len(self.document.entries)):
            entry = self.document.entries.pop(self.to_position)
            self.document.entries.insert(self.from_position, entry)
            self.document.reindex()
            self.document.modified = True
    
    def description(self) -> str:
        return f"Move subtitle from #{self.from_position + 1} to #{self.to_position + 1}"


class TimeShiftCommand(Command):
    """Command to shift timing of multiple subtitles."""
    
    def __init__(self, document: SubtitleDocument, offset_ms: int, 
                 positions: List[int] = None):
        """
        Initialize the time shift command.
        
        Args:
            document: The subtitle document
            offset_ms: Time offset in milliseconds (can be negative)
            positions: List of entry indices to shift (None for all)
        """
        self.document = document
        self.offset_ms = offset_ms
        self.positions = positions if positions else list(range(len(document.entries)))
    
    def execute(self):
        """Shift the timing of selected entries."""
        for position in self.positions:
            if 0 <= position < len(self.document.entries):
                entry = self.document.entries[position]
                entry.shift_time(self.offset_ms)
        self.document.modified = True
    
    def undo(self):
        """Shift back the timing."""
        for position in self.positions:
            if 0 <= position < len(self.document.entries):
                entry = self.document.entries[position]
                entry.shift_time(-self.offset_ms)
        self.document.modified = True
    
    def description(self) -> str:
        count = len(self.positions)
        direction = "forward" if self.offset_ms > 0 else "backward"
        return f"Shift {count} subtitle(s) {direction} by {abs(self.offset_ms)}ms"


class EditMarginsCommand(Command):
    """Command to edit subtitle margins (ASS/SSA position overrides)."""

    def __init__(self, document: SubtitleDocument, position: int,
                 new_margin_l: int, new_margin_r: int, new_margin_v: int):
        self.document = document
        self.position = position
        self.new_margin_l = new_margin_l
        self.new_margin_r = new_margin_r
        self.new_margin_v = new_margin_v
        self.old_margin_l = None
        self.old_margin_r = None
        self.old_margin_v = None

    def execute(self):
        if 0 <= self.position < len(self.document.entries):
            entry = self.document.entries[self.position]
            self.old_margin_l = entry.margin_l
            self.old_margin_r = entry.margin_r
            self.old_margin_v = entry.margin_v
            entry.margin_l = self.new_margin_l
            entry.margin_r = self.new_margin_r
            entry.margin_v = self.new_margin_v
            self.document.modified = True

    def undo(self):
        if self.old_margin_l is not None and 0 <= self.position < len(self.document.entries):
            entry = self.document.entries[self.position]
            entry.margin_l = self.old_margin_l
            entry.margin_r = self.old_margin_r
            entry.margin_v = self.old_margin_v
            self.document.modified = True

    def description(self) -> str:
        return f"Edit margins of subtitle #{self.position + 1}"


class SortByTimeCommand(Command):
    """Command to sort subtitles by start time."""

    def __init__(self, document: SubtitleDocument):
        self.document = document
        self.old_order = []

    def execute(self):
        self.old_order = list(self.document.entries)
        self.document.sort_by_time()

    def undo(self):
        self.document.entries.clear()
        self.document.entries.extend(self.old_order)
        self.document.reindex()
        self.document.modified = True

    def description(self) -> str:
        return "Sort subtitles by time"
