"""Integration tests for parsing the large sample ASS subtitle file."""

import pytest
from subtitle_editor.parsers import ASSParser
from subtitle_editor.models import SubtitleFormat, SubtitleEntry, TimeCode


class TestSampleFileParse:
    """Integration tests using the large sample ASS subtitle file."""

    @pytest.mark.parser
    @pytest.mark.integration
    def test_parse_sample_file(self, sample_ass_file_content):
        """Test parsing the complete sample ASS file."""
        doc = ASSParser.parse(sample_ass_file_content)

        assert doc.format == SubtitleFormat.ASS
        assert len(doc.entries) == 120
        assert len(doc.styles) == 4
        assert doc.modified is False

    @pytest.mark.parser
    @pytest.mark.integration
    def test_parse_all_styles_present(self, sample_ass_file_content):
        """Verify all 4 styles are parsed correctly."""
        doc = ASSParser.parse(sample_ass_file_content)

        default = doc.get_style_by_name("Default")
        assert default is not None
        assert default.fontname == "Arial"
        assert default.fontsize == 48
        assert default.bold is True

        alternate = doc.get_style_by_name("Alternate")
        assert alternate is not None
        assert alternate.fontname == "Times New Roman"
        assert alternate.fontsize == 42
        assert alternate.italic is True

        top = doc.get_style_by_name("Top")
        assert top is not None
        assert top.fontname == "Calibri"
        assert top.fontsize == 36

        draw = doc.get_style_by_name("Draw")
        assert draw is not None
        assert draw.fontname == "Arial"
        assert draw.fontsize == 20

    @pytest.mark.parser
    @pytest.mark.integration
    def test_parse_aegisub_project_garbage(self, sample_ass_file_content):
        """Verify [Aegisub Project Garbage] is parsed."""
        doc = ASSParser.parse(sample_ass_file_content)
        garbage = doc.aegisub_project_garbage

        assert garbage["Audio File"] == "?dummy"
        assert garbage["Video File"] == "?dummy"
        assert garbage["Video AR Mode"] == "4"
        assert garbage["Video AR Value"] == "1.777778"
        assert garbage["Video Zoom Percent"] == "0.500000"
        assert garbage["Video Position"] == "24576"
        assert "Scroll Position" in garbage
        assert "Active Line" in garbage

    @pytest.mark.parser
    @pytest.mark.integration
    def test_parse_aegisub_extradata(self, sample_ass_file_content):
        """Verify [Aegisub Extradata] is handled gracefully (not stored)."""
        doc = ASSParser.parse(sample_ass_file_content)
        assert doc is not None
        assert not hasattr(doc, 'aegisub_extradata')

    @pytest.mark.parser
    @pytest.mark.integration
    def test_serialize_roundtrip_entries(self, sample_ass_file_content):
        """Verify serialization roundtrip preserves entries."""
        doc = ASSParser.parse(sample_ass_file_content)
        output = ASSParser.serialize(doc)
        doc2 = ASSParser.parse(output)

        assert len(doc2.entries) == len(doc.entries)
        assert len(doc2.styles) == len(doc.styles)

        for s1, s2 in zip(doc.styles, doc2.styles):
            assert s1.name == s2.name

        assert doc.entries[0].text == doc2.entries[0].text

    @pytest.mark.parser
    @pytest.mark.integration
    def test_serialize_produces_valid_ass(self, sample_ass_file_content):
        """Verify serialized output contains required sections and styles."""
        doc = ASSParser.parse(sample_ass_file_content)
        output = ASSParser.serialize(doc)

        assert "[Script Info]" in output
        assert "[V4+ Styles]" in output
        assert "[Events]" in output
        assert "Style: Default," in output
        assert "Style: Alternate," in output
        assert "Style: Top," in output
        assert "Style: Draw," in output

    @pytest.mark.parser
    @pytest.mark.integration
    def test_parse_with_different_override_tags(self, sample_ass_file_content):
        """Verify entries with specific override tags are parsed correctly."""
        doc = ASSParser.parse(sample_ass_file_content)
        texts = [e.text for e in doc.entries]

        assert any(r'{\i1}' in t for t in texts)
        assert any(r'{\b1}' in t for t in texts)
        assert sum(1 for t in texts if r'\pos(' in t) >= 2
        assert any(r'\clip' in t for t in texts)
        assert any(r'\t(' in t for t in texts)
        assert any(r'\move(' in t for t in texts)
        assert any(r'\fad' in t for t in texts)
        assert any(r'\kf' in t for t in texts)

    @pytest.mark.parser
    @pytest.mark.integration
    def test_parse_first_entry(self, sample_ass_file_content):
        """Verify the first Dialogue entry is parsed correctly."""
        doc = ASSParser.parse(sample_ass_file_content)
        entry = doc.entries[0]

        assert entry.index == 1
        assert entry.start_time.total_milliseconds == 0
        assert entry.end_time.total_milliseconds == 2000
        assert entry.text == "Line 1 - Default style."
        assert entry.style == "Default"

    @pytest.mark.parser
    @pytest.mark.integration
    def test_parse_last_entry(self, sample_ass_file_content):
        """Verify the last Dialogue entry is parsed correctly."""
        doc = ASSParser.parse(sample_ass_file_content)
        entry = doc.entries[-1]

        assert entry.index == 120
        assert entry.start_time.total_milliseconds == 258000
        assert entry.end_time.total_milliseconds == 260000

    @pytest.mark.parser
    @pytest.mark.integration
    def test_serialized_text_newlines(self, sample_ass_file_content):
        """Verify newlines in text are serialized as \\N."""
        doc = ASSParser.parse(sample_ass_file_content)
        entry = SubtitleEntry(
            121, TimeCode(0, 0, 5, 0), TimeCode(0, 0, 7, 0), "Line 1\nLine 2"
        )
        doc.entries.append(entry)
        output = ASSParser.serialize(doc)
        assert "Line 1\\NLine 2" in output

    @pytest.mark.parser
    @pytest.mark.integration
    def test_serialize_roundtrip_styles(self, sample_ass_file_content):
        """Verify style properties survive serialization roundtrip."""
        doc = ASSParser.parse(sample_ass_file_content)
        output = ASSParser.serialize(doc)
        doc2 = ASSParser.parse(output)

        for style in doc2.styles:
            original = doc.get_style_by_name(style.name)
            assert original is not None
            assert style.fontsize == original.fontsize
            assert style.fontname == original.fontname
            assert style.bold == original.bold
            assert style.italic == original.italic

    @pytest.mark.parser
    @pytest.mark.integration
    def test_comment_entries_not_in_doc_entries(self, sample_ass_file_content):
        """Verify Comment lines are excluded from doc.entries."""
        doc = ASSParser.parse(sample_ass_file_content)
        for entry in doc.entries:
            assert "===" not in entry.text
            assert "Block" not in entry.text
