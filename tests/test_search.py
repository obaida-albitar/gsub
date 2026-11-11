"""Literal visible-text search, formatting preservation, and replacement history."""

import copy

import pytest

from gsub.commands.command import CommandManager
from gsub.models import SubtitleDocument, SubtitleEntry, SubtitleFormat, TimeCode
from gsub.search import SearchOptions, build_replace_command, find_matches, visible_text


def document(*texts, fmt=SubtitleFormat.SRT):
    return SubtitleDocument(fmt, entries=[
        SubtitleEntry(index + 1, TimeCode.from_milliseconds(index * 3000),
                      TimeCode.from_milliseconds(index * 3000 + 2000), text,
                      style="Dialogue", actor="Speaker", layer=2)
        for index, text in enumerate(texts)
    ])


def replace(doc, query, replacement, options=None, positions=None):
    command = build_replace_command(doc, find_matches(doc, query, options, positions), replacement)
    manager = CommandManager()
    if command:
        manager.execute(command)
    return manager


@pytest.mark.unit
class TestSearch:
    def test_case_insensitive_is_default_and_all_occurrences_are_found(self):
        matches = find_matches(document("Hello HELLO hello", "Other HELLO"), "hello")
        assert [(m.position, m.start, m.end) for m in matches] == [
            (0, 0, 5), (0, 6, 11), (0, 12, 17), (1, 6, 11)]

    def test_case_sensitive(self):
        matches = find_matches(document("Hello hello HELLO"), "hello", SearchOptions(True))
        assert [(m.start, m.end) for m in matches] == [(6, 11)]

    def test_whole_words_unicode_and_underscore(self):
        doc = document("cat cats cat_cat (cat) 猫cat caté cat́")
        matches = find_matches(doc, "cat", SearchOptions(whole_words=True))
        assert [m.start for m in matches] == [0, 18]

    def test_casefold_expansion_matches_full_character(self):
        doc = document("Straße STRASSE Straße")
        matches = find_matches(doc, "strasse")
        assert [(m.start, m.end) for m in matches] == [(0, 6), (7, 14), (15, 21)]
        assert find_matches(document("ß"), "s") == []

    def test_literal_query_is_not_regex(self):
        assert len(find_matches(document("a.b axb [test]"), "a.b")) == 1
        assert len(find_matches(document("[test]"), "[test]")) == 1

    def test_empty_query_and_empty_selection(self):
        doc = document("hello", "hello")
        assert find_matches(doc, "") == []
        assert find_matches(doc, "hello", positions=[]) == []

    def test_selection_is_sorted_deduplicated_and_out_of_range_skipped(self):
        doc = document("hello", "hello", "hello")
        assert [m.position for m in find_matches(doc, "hello", positions=[2, 0, 2, -1, 8])] == [0, 2]

    def test_whitespace_is_searchable_without_stripping(self):
        matches = find_matches(document("a  b"), "  ")
        assert [(m.start, m.end) for m in matches] == [(1, 3)]

    def test_srt_tags_entities_and_breaks(self):
        text = '<font color="#ff0000"><b>Hello</b> &amp; world</font><br/>Next'
        assert visible_text(text, SubtitleFormat.SRT) == "Hello & world\nNext"
        assert not find_matches(document(text), "ff0000")
        assert len(find_matches(document(text), "Hello & world")) == 1

    def test_unknown_angle_bracket_text_stays_searchable(self):
        assert len(find_matches(document("x <unknown> y"), "<unknown>")) == 1

    @pytest.mark.parametrize("fmt", [SubtitleFormat.ASS, SubtitleFormat.SSA])
    def test_ass_tags_and_drawing_paths_are_not_searchable(self, fmt):
        text = r"{\fnArial\b1}Hello\Nworld{\p1}m 0 0 l 20 20{\p0}!"
        doc = document(text, fmt=fmt)
        assert visible_text(text, fmt) == "Hello\nworld!"
        assert not find_matches(doc, "Arial")
        assert not find_matches(doc, "20")
        assert len(find_matches(doc, "Hello\nworld!")) == 1

    def test_ass_reset_ends_drawing_and_transform_p_does_not_start_it(self):
        text = r"{\p1}m 0 0{\r}{\t(0,500,\p1)}hello"
        assert visible_text(text, SubtitleFormat.ASS) == "hello"

    def test_partial_multi_character_entity_is_not_matched(self):
        doc = document("&NotEqualTilde;")
        assert visible_text(doc.entries[0].text, doc.format) == "≂̸"
        assert find_matches(doc, "≂") == []
        assert len(find_matches(doc, "≂̸")) == 1


@pytest.mark.command
class TestReplacement:
    def test_replace_all_is_single_undo_step_and_preserves_other_fields(self):
        doc = document("hello hello", "HELLO", "untouched")
        original = copy.deepcopy(doc.entries)
        manager = replace(doc, "hello", "goodbye")
        expected = copy.deepcopy(doc.entries)
        assert [e.text for e in doc.entries] == ["goodbye goodbye", "goodbye", "untouched"]
        assert manager.get_undo_description() == "Replace 3 matches"
        assert manager.undo()
        assert doc.entries == original
        assert not manager.can_undo()
        assert manager.redo()
        assert doc.entries == expected

    def test_replace_one_changes_only_selected_occurrence(self):
        doc = document("hello hello", "hello")
        matches = find_matches(doc, "hello")
        command = build_replace_command(doc, matches[1:2], "bye")
        command.execute()
        assert [e.text for e in doc.entries] == ["hello bye", "hello"]
        command.undo()
        assert [e.text for e in doc.entries] == ["hello hello", "hello"]

    def test_empty_replacement_and_selection_scope(self):
        doc = document("one foo two foo", "foo")
        manager = replace(doc, "foo", "", positions=[0])
        assert [e.text for e in doc.entries] == ["one  two ", "foo"]
        manager.undo()
        assert doc.entries[0].text == "one foo two foo"

    def test_crossing_ass_inline_tags_preserves_all_tag_bytes(self):
        original = r"{\an2}hel{\b1}lo{\b0} world"
        doc = document(original, fmt=SubtitleFormat.ASS)
        manager = replace(doc, "hello", "Hi")
        assert doc.entries[0].text == r"{\an2}Hi{\b1}{\b0} world"
        assert visible_text(doc.entries[0].text, doc.format) == "Hi world"
        manager.undo()
        assert doc.entries[0].text == original

    def test_crossing_srt_tags_preserves_tag_attributes_and_entities(self):
        doc = document('<font color="red">hel<b>lo</b></font> &amp; bye')
        manager = replace(doc, "hello", "Hi & <friend>")
        assert doc.entries[0].text == '<font color="red">Hi &amp; &lt;friend&gt;<b></b></font> &amp; bye'
        manager.undo()
        assert doc.entries[0].text == '<font color="red">hel<b>lo</b></font> &amp; bye'

    def test_multiple_variable_length_replacements_keep_source_spans(self):
        doc = document("A &amp; A <b>A</b> A")
        replace(doc, "A", "longer")
        assert doc.entries[0].text == "longer &amp; longer <b>longer</b> longer"

    def test_entity_is_replaced_as_one_unit(self):
        doc = document("A &amp; B &#38; C")
        replace(doc, "&", "and")
        assert doc.entries[0].text == "A and B and C"

    def test_multichar_entity_full_match_is_replaced_atomically(self):
        doc = document("&NotEqualTilde;")
        replace(doc, "≂̸", "=")
        assert doc.entries[0].text == "="

    def test_ass_replacement_newlines_use_model_representation(self):
        from gsub.parsers import ASSParser

        doc = document(r"{\i1}hello", fmt=SubtitleFormat.ASS)
        replace(doc, "hello", "hi\nthere")
        assert doc.entries[0].text == "{\\i1}hi\nthere"
        serialized = ASSParser.serialize(doc)
        assert r"hi\Nthere" in serialized
        assert ASSParser.parse(serialized).entries[0].text == doc.entries[0].text

    @pytest.mark.parametrize("replacement, expected", [
        (r"first\Nsecond", "first\nsecond"),
        (r"first\nsecond", "first\nsecond"),
        (r"first\hsecond", "first\xa0second"),
    ])
    def test_ass_replacement_supports_text_escapes(self, replacement, expected):
        doc = document("hello", fmt=SubtitleFormat.ASS)
        replace(doc, "hello", replacement)
        assert doc.entries[0].text == expected

    def test_ass_braces_are_rejected_without_mutation(self):
        doc = document("hello", fmt=SubtitleFormat.ASS)
        with pytest.raises(ValueError, match="braces"):
            replace(doc, "hello", r"{\b1}")
        assert doc.entries[0].text == "hello"

    def test_noop_preserves_original_entity_spelling(self):
        doc = document("&#38;")
        assert build_replace_command(doc, find_matches(doc, "&"), "&") is None
        assert doc.entries[0].text == "&#38;"
        assert not doc.modified

    def test_no_matches_do_not_create_command(self):
        doc = document("text")
        assert build_replace_command(doc, find_matches(doc, "absent"), "new") is None

    def test_stale_preview_is_rejected_before_changing_any_entries(self):
        doc = document("hello", "hello")
        matches = find_matches(doc, "hello")
        doc.entries[1].text = "changed"
        with pytest.raises(ValueError, match="changed"):
            build_replace_command(doc, matches, "bye")
        assert [e.text for e in doc.entries] == ["hello", "changed"]

    def test_duplicate_matches_are_rejected(self):
        doc = document("hello")
        matches = find_matches(doc, "hello") * 2
        with pytest.raises(ValueError, match="nonoverlapping"):
            build_replace_command(doc, matches, "bye")

    def test_casefold_expansion_replacement_preserves_neighboring_characters(self):
        doc = document("Straße Straße")
        replace(doc, "strasse", "street")
        assert doc.entries[0].text == "street street"
