"""
Command pattern base classes for undo/redo functionality.

Following the Command pattern, each action is encapsulated as a command object
that can be executed, undone, and redone.
"""

from abc import ABC, abstractmethod
from typing import List

from gsub.logger import get_logger

logger = get_logger(__name__)


class Command(ABC):
    """Abstract base class for all commands."""
    
    @abstractmethod
    def execute(self):
        """Execute the command."""
        pass
    
    @abstractmethod
    def undo(self):
        """Undo the command."""
        pass
    
    def redo(self):
        """Redo the command (by default, same as execute)."""
        self.execute()
    
    @abstractmethod
    def description(self) -> str:
        """Return a human-readable description of the command."""
        pass


class CompositeCommand(Command):
    """Execute a sequence of commands as a single undoable unit.

    Children are executed in order; undo runs them in reverse. If a child's
    ``execute`` raises, the already-executed children are undone and the
    exception is re-raised so the manager does not record a partial command.
    """

    def __init__(self, commands: List[Command], description: str = "Composite command"):
        self._commands = list(commands)
        self._description = description

    def execute(self):
        done = []
        try:
            for cmd in self._commands:
                cmd.execute()
                done.append(cmd)
        except Exception:
            for cmd in reversed(done):
                try:
                    cmd.undo()
                except Exception:
                    pass
            raise

    def undo(self):
        for cmd in reversed(self._commands):
            try:
                cmd.undo()
            except Exception:
                # Best effort: a failing child must not stop the remaining
                # undos, or the document would be left half-undone.
                logger.exception("Failed to undo step of: %s", self._description)

    def redo(self):
        for cmd in self._commands:
            try:
                cmd.redo()
            except Exception:
                logger.exception("Failed to redo step of: %s", self._description)

    def description(self) -> str:
        return self._description


class CommandManager:
    """
    Manages command history for undo/redo functionality.
    
    Maintains two stacks: one for undo and one for redo.
    When a new command is executed, the redo stack is cleared.
    """
    
    def __init__(self, max_history: int = 100):
        """
        Initialize the command manager.
        
        Args:
            max_history: Maximum number of commands to keep in history
        """
        if max_history < 1:
            max_history = 1
        self._undo_stack: List[Command] = []
        self._redo_stack: List[Command] = []
        self._max_history = max_history
    
    def execute(self, command: Command):
        """
        Execute a command and add it to the undo stack.

        Args:
            command: The command to execute
        """
        command.execute()
        self._undo_stack.append(command)

        # Clear redo stack when a new command is executed
        self._redo_stack.clear()

        # Limit history size
        if len(self._undo_stack) > self._max_history:
            self._undo_stack.pop(0)
    
    def undo(self) -> bool:
        """
        Undo the last command.
        
        Returns:
            True if a command was undone, False if undo stack is empty
        """
        if not self.can_undo():
            return False
        
        command = self._undo_stack.pop()
        command.undo()
        self._redo_stack.append(command)
        return True
    
    def redo(self) -> bool:
        """
        Redo the last undone command.
        
        Returns:
            True if a command was redone, False if redo stack is empty
        """
        if not self.can_redo():
            return False
        
        command = self._redo_stack.pop()
        command.redo()
        self._undo_stack.append(command)
        return True
    
    def can_undo(self) -> bool:
        """Check if there are commands available to undo."""
        return len(self._undo_stack) > 0
    
    def can_redo(self) -> bool:
        """Check if there are commands available to redo."""
        return len(self._redo_stack) > 0
    
    def clear(self):
        """Clear both undo and redo stacks."""
        self._undo_stack.clear()
        self._redo_stack.clear()
    
    def get_undo_description(self) -> str:
        """Get description of the next command to undo."""
        if self.can_undo():
            return self._undo_stack[-1].description()
        return ""
    
    def get_redo_description(self) -> str:
        """Get description of the next command to redo."""
        if self.can_redo():
            return self._redo_stack[-1].description()
        return ""
