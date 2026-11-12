"""Crash recovery must preserve model fidelity and never damage saved files."""

from dataclasses import asdict
import json
import os
from pathlib import Path
from unittest.mock import patch

import pytest

from gsub.models import ASSStyle, SubtitleDocument, SubtitleEntry, SubtitleFormat, TimeCode
from gsub.recovery import (
    RecoveredBatch, RecoveryStore, atomic_write_text, document_from_dict, document_to_dict,
)


@pytest.fixture
def document():
    doc = SubtitleDocument(SubtitleFormat.ASS, modified=True, file_path="/original/subtitles.ass")
    doc.entries = [SubtitleEntry(4, TimeCode(0, 1, 2, 123), TimeCode(0, 1, 4, 987),
                                r"{\i1}مرحبا\N世界", "Signs", 12, 23, 34,
                                layer=3, actor="Narrator", effect="Banner;20;1;50")]
    doc.entries[0].text += "  "
    doc.styles = [ASSStyle(name="Signs", fontsize=37, scale_x=107.25, outline=2.5)]
    doc.metadata = {"Title": "Recovery ∑", "PlayResX": "1920", "Custom": "keep me"}
    doc.script_info_order = ["Custom", "Title", "PlayResX"]
    doc.script_info_comments = ["; Keep this comment"]
    doc.aegisub_project_garbage = {"Video File": "../movie.mkv"}
    return doc


def test_atomic_write_unicode_and_exact_line_endings(tmp_path):
    path = tmp_path / "字幕.srt"
    atomic_write_text(path, "Hello\r\n世界\n")
    assert path.read_bytes() == "Hello\r\n世界\n".encode()
    assert list(tmp_path.iterdir()) == [path]


def test_atomic_replace_preserves_permissions(tmp_path):
    path = tmp_path / "subtitle.srt"
    path.write_text("before")
    path.chmod(0o640)
    atomic_write_text(path, "after")
    assert path.read_text() == "after"
    assert path.stat().st_mode & 0o777 == 0o640


@pytest.mark.parametrize("existing", [True, False])
def test_atomic_write_follows_symlink_without_replacing_link(tmp_path, existing):
    target = tmp_path / "target.srt"
    if existing:
        target.write_text("before")
    link = tmp_path / "link.srt"
    link.symlink_to(target.name)
    atomic_write_text(link, "after")
    assert link.is_symlink()
    assert os.readlink(link) == target.name
    assert target.read_text() == "after"


@pytest.mark.parametrize("failure", ["replace", "fsync"])
def test_atomic_failure_leaves_original_and_removes_temp(tmp_path, failure):
    path = tmp_path / "subtitle.srt"
    path.write_text("precious original")
    with patch(f"gsub.recovery.os.{failure}", side_effect=OSError("disk failure")):
        with pytest.raises(OSError, match="disk failure"):
            atomic_write_text(path, "new content")
    assert path.read_text() == "precious original"
    assert list(tmp_path.iterdir()) == [path]


def test_atomic_failure_for_new_file_leaves_no_partial_file(tmp_path):
    path = tmp_path / "new.srt"
    with patch("gsub.recovery.os.replace", side_effect=OSError("disk failure")):
        with pytest.raises(OSError):
            atomic_write_text(path, "new content")
    assert list(tmp_path.iterdir()) == []


def test_missing_output_directory_is_not_silently_created(tmp_path):
    with pytest.raises(FileNotFoundError):
        atomic_write_text(tmp_path / "missing" / "subtitle.srt", "text")


def test_recovery_preserves_every_model_field_and_raw_text(document):
    recovered = document_from_dict(document_to_dict(document))
    assert asdict(recovered) == asdict(document)
    assert recovered.entries[0].start_time.milliseconds == 123
    assert recovered.entries[0].text.endswith("  ")


@pytest.mark.parametrize("format_", list(SubtitleFormat))
def test_recovery_supports_all_formats(document, format_):
    document.format = format_
    restored = document_from_dict(document_to_dict(document))
    assert restored.format == format_
    assert restored.entries[0].text == document.entries[0].text


def test_restored_document_is_always_unsaved(document):
    document.modified = False
    assert document_from_dict(document_to_dict(document)).modified


def test_recovery_session_includes_unchecked_dirty_batch(tmp_path, document):
    store = RecoveryStore(tmp_path)
    store.save(document, [RecoveredBatch(document, "batch.ass", False, "original disk content")])
    session = store.load()
    assert asdict(session.editor) == asdict(document)
    assert session.batch[0].selected is False
    assert session.batch[0].saved_content == "original disk content"
    assert asdict(session.batch[0].document) == asdict(document)


def test_recovery_does_not_write_original_file(tmp_path, document):
    source = tmp_path / "original.ass"
    source.write_text("original disk content")
    document.file_path = str(source)
    store = RecoveryStore(tmp_path / "state")
    store.save(document)
    assert source.read_text() == "original disk content"
    assert store.load().editor.file_path == str(source)


def test_empty_session_removes_obsolete_snapshot(tmp_path, document):
    store = RecoveryStore(tmp_path)
    store.save(document)
    assert store.path.exists()
    store.save()
    assert not store.path.exists()
    assert store.load() is None
    store.clear()


def test_unchanged_snapshot_avoids_rewriting_disk(tmp_path, document):
    store = RecoveryStore(tmp_path)
    store.save(document)
    with patch("gsub.recovery.atomic_write_text") as write:
        store.save(document)
    write.assert_not_called()


def test_failed_snapshot_update_preserves_previous_recovery(tmp_path, document):
    store = RecoveryStore(tmp_path)
    store.save(document)
    previous = store.path.read_bytes()
    document.entries[0].text = "changed"
    with patch("gsub.recovery.os.replace", side_effect=OSError("disk full")):
        with pytest.raises(OSError):
            store.save(document)
    assert store.path.read_bytes() == previous
    assert store.load().editor.entries[0].text != "changed"


@pytest.mark.parametrize("content", ["{broken", "null", "[]", '{"version":2}',
    '{"version":1,"editor":{}}', '{"version":1,"batch":[{}]}',
    '{"version":1,"batch":[{"file_path":"x","selected":"no"}]}'])
def test_malformed_recovery_is_rejected_without_deleting_it(tmp_path, content):
    store = RecoveryStore(tmp_path)
    store.path.write_text(content)
    with pytest.raises(ValueError):
        store.load()
    assert store.path.read_text() == content


@pytest.mark.parametrize("field,value", [("format", "vtt"), ("entries", 1),
    ("entries", [{"index": 1, "text": "bad"}]), ("styles", [{"unknown": 1}]),
    ("styles", [{"fontsize": "not a number"}]), ("styles", [{"fontname": 42}]),
    ("styles", [{"scale_x": float("inf")}]),
    ("metadata", []), ("metadata", {"Title": 9}), ("file_path", 5),
    ("script_info_comments", "not a list")])
def test_invalid_document_shapes_are_rejected(document, field, value):
    raw = document_to_dict(document)
    raw[field] = value
    with pytest.raises(ValueError):
        document_from_dict(raw)


@pytest.mark.parametrize("field,value", [("actor", []), ("effect", 5), ("layer", "2"),
                                         ("margin_l", None), ("style", {})])
def test_invalid_entry_metadata_is_rejected(document, field, value):
    raw = document_to_dict(document)
    raw["entries"][0][field] = value
    with pytest.raises(ValueError):
        document_from_dict(raw)


def test_recovery_is_private_by_default(tmp_path, document):
    store = RecoveryStore(tmp_path)
    store.save(document)
    assert store.path.stat().st_mode & 0o777 == 0o600
    assert json.loads(store.path.read_text())["version"] == 1
    assert not list(Path(tmp_path).glob("*.tmp"))
