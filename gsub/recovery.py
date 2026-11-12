"""Atomic subtitle writes and versioned, full-fidelity recovery snapshots.

Recovery uses the model rather than subtitle serialization: serialization can
round ASS timings and omit editor metadata, which must survive a crash.
"""

from dataclasses import asdict, dataclass, fields
import json
import math
import os
from pathlib import Path
import stat
import tempfile

from gsub.models import ASSStyle, SubtitleDocument, SubtitleEntry, SubtitleFormat, TimeCode


def atomic_write_text(path, content: str) -> None:
    """Replace a local file only after a complete UTF-8 write has succeeded.

    Follow symlinks as ordinary ``open(path, 'w')`` does, preserving the link
    itself. Existing permissions are kept; new files are private by default.
    A failed write/replace leaves the original file and no temporary file.
    """
    target = Path(os.path.realpath(os.fspath(path)))
    try:
        mode = stat.S_IMODE(target.stat().st_mode)
    except FileNotFoundError:
        mode = None
    descriptor, temporary = tempfile.mkstemp(prefix=f".{target.name}.", suffix=".tmp",
                                              dir=target.parent)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="") as stream:
            if mode is not None:
                os.fchmod(stream.fileno(), mode)
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, target)
    finally:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass


def document_to_dict(document: SubtitleDocument) -> dict:
    value = asdict(document)
    value["format"] = document.format.value
    return value


def document_from_dict(value: dict) -> SubtitleDocument:
    """Validate recovery input before constructing a document from it."""
    if not isinstance(value, dict):
        raise ValueError("Invalid recovered document")
    value = dict(value)
    try:
        value["format"] = SubtitleFormat(value["format"])
        entries = []
        for raw in value.get("entries", []):
            raw = dict(raw)
            for key in ("start_time", "end_time"):
                time = raw[key]
                if not isinstance(time, dict) or any(type(n) is not int for n in time.values()):
                    raise ValueError("Invalid recovered time")
                raw[key] = TimeCode(**time)
            if not isinstance(raw.get("text"), str) or type(raw.get("index")) is not int:
                raise ValueError("Invalid recovered subtitle")
            for key in ("margin_l", "margin_r", "margin_v", "layer"):
                if key in raw and type(raw[key]) is not int:
                    raise ValueError("Invalid recovered subtitle metadata")
            for key in ("actor", "effect"):
                if key in raw and not isinstance(raw[key], str):
                    raise ValueError("Invalid recovered subtitle metadata")
            if raw.get("style") is not None and not isinstance(raw["style"], str):
                raise ValueError("Invalid recovered subtitle style")
            # SubtitleEntry strips text in __post_init__; restore it exactly.
            entry = SubtitleEntry(**raw)
            entry.text = raw["text"]
            entries.append(entry)
        value["entries"] = entries
        styles = []
        defaults = ASSStyle()
        for raw in value.get("styles", []):
            style = ASSStyle(**raw)
            for item in fields(ASSStyle):
                default, current = getattr(defaults, item.name), getattr(style, item.name)
                if isinstance(default, bool):
                    valid = type(current) is bool
                elif isinstance(default, str):
                    valid = isinstance(current, str)
                else:
                    valid = (type(current) in (int, float) and math.isfinite(current))
                if not valid:
                    raise ValueError("Invalid recovered style property")
            styles.append(style)
        value["styles"] = styles
        allowed = {item.name for item in fields(SubtitleDocument)}
        if set(value) - allowed:
            raise ValueError("Unknown recovered document fields")
        for name in ("metadata", "aegisub_project_garbage"):
            metadata = value.get(name, {})
            if not isinstance(metadata, dict) or any(not isinstance(k, str) or not isinstance(v, str)
                                                     for k, v in metadata.items()):
                raise ValueError("Invalid recovered metadata")
        for name in ("script_info_order", "script_info_comments"):
            if not isinstance(value.get(name, []), list) or any(
                    not isinstance(item, str) for item in value.get(name, [])):
                raise ValueError("Invalid recovered section layout")
        if value.get("file_path") is not None and not isinstance(value["file_path"], str):
            raise ValueError("Invalid recovered file path")
        document = SubtitleDocument(**value)
        document.modified = True
        return document
    except (KeyError, TypeError, AttributeError) as error:
        raise ValueError("Invalid recovered document") from error


@dataclass
class RecoveredBatch:
    document: SubtitleDocument
    file_path: str
    selected: bool = True
    saved_content: str | None = None


@dataclass
class RecoverySession:
    editor: SubtitleDocument | None
    batch: list[RecoveredBatch]


class RecoveryStore:
    """One atomic snapshot of the dirty documents in an application window."""

    def __init__(self, directory, filename="recovery.json"):
        self.path = Path(directory) / filename
        self._last_content = None

    def save(self, editor=None, batch=()):
        batch = list(batch)
        if editor is None and not batch:
            self.clear()
            return
        value = {
            "version": 1,
            "editor": document_to_dict(editor) if editor is not None else None,
            "batch": [{"document": document_to_dict(item.document),
                       "file_path": item.file_path, "selected": item.selected,
                       "saved_content": item.saved_content} for item in batch],
        }
        content = json.dumps(value, ensure_ascii=False, allow_nan=False)
        if content == self._last_content and self.path.exists():
            return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        atomic_write_text(self.path, content)
        self._last_content = content

    def load(self):
        if not self.path.exists():
            return None
        try:
            value = json.loads(self.path.read_text(encoding="utf-8"))
            if not isinstance(value, dict) or value.get("version") != 1:
                raise ValueError("Unsupported recovery format")
            editor = (document_from_dict(value["editor"])
                      if value.get("editor") is not None else None)
            batch = []
            for raw in value.get("batch", []):
                if not isinstance(raw.get("file_path"), str) or not raw["file_path"]:
                    raise ValueError("Invalid recovered batch path")
                if type(raw.get("selected", True)) is not bool:
                    raise ValueError("Invalid recovered batch selection")
                if raw.get("saved_content") is not None and not isinstance(raw["saved_content"], str):
                    raise ValueError("Invalid saved batch content")
                batch.append(RecoveredBatch(document_from_dict(raw["document"]),
                                            raw["file_path"], raw.get("selected", True),
                                            raw.get("saved_content")))
            return RecoverySession(editor, batch) if editor is not None or batch else None
        except (TypeError, KeyError, AttributeError) as error:
            raise ValueError("Invalid recovery snapshot") from error

    def clear(self):
        self.path.unlink(missing_ok=True)
        self._last_content = None
