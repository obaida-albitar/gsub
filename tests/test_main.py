"""Tests for the application entry point (GsubApplication).

The real GsubWindow is replaced by a recording fake so activation and
file-open routing can be asserted without instantiating the full window
(a separate test module covers the real window).
"""

import pytest

try:
    from subtitle_editor.resources import register_resources

    register_resources()
    from subtitle_editor import main as main_module
    from subtitle_editor.main import GsubApplication
except Exception as exc:  # pragma: no cover - depends on GTK/libmpv stack
    pytest.skip(
        f"main module not importable in this environment: {exc}",
        allow_module_level=True,
    )


class _FakeWindow:
    """Records what the application asks the window to do."""

    def __init__(self, application=None):
        self.application = application
        self.presented = 0
        self.opened_files = []
        self.opened_videos = []

    def present(self):
        self.presented += 1

    def open_file(self, gfile):
        self.opened_files.append(gfile)

    def open_video(self, gfile):
        self.opened_videos.append(gfile)


class _FakeFileInfo:
    def __init__(self, content_type):
        self._content_type = content_type

    def get_attribute_string(self, attribute):
        assert attribute == "standard::content-type"
        return self._content_type


class _FakeFile:
    """Duck-typed Gio.File: query_info returns a content type (or raises)."""

    def __init__(self, content_type=None, fail_query=False, name="f"):
        self.content_type = content_type
        self.fail_query = fail_query
        self.name = name

    def query_info(self, attributes, flags, cancellable):
        assert attributes == "standard::content-type"
        if self.fail_query:
            raise RuntimeError("query failed")
        return _FakeFileInfo(self.content_type)


@pytest.fixture
def app(monkeypatch):
    """A GsubApplication whose GsubWindow is a recording fake."""
    created = []

    def _fake_window_ctor(**kwargs):
        window = _FakeWindow(**kwargs)
        created.append(window)
        return window

    monkeypatch.setattr(main_module, "GsubWindow", _fake_window_ctor)

    application = GsubApplication()
    application._created_windows = created
    return application


@pytest.mark.unit
class TestActivate:
    def test_activate_creates_and_presents_window_once(self, app):
        app.do_activate()

        assert len(app._created_windows) == 1
        assert app.window is app._created_windows[0]
        assert app.window.presented == 1
        # The window is bound to the application.
        assert app.window.application is app

    def test_repeated_activation_presents_existing_window(self, app):
        app.do_activate()
        first = app.window

        app.do_activate()
        app.do_activate()

        assert app.window is first
        assert len(app._created_windows) == 1
        assert first.presented == 3


@pytest.mark.unit
class TestIsVideoFile:
    def test_video_content_type_is_video(self):
        assert GsubApplication._is_video_file(_FakeFile("video/mp4")) is True
        assert GsubApplication._is_video_file(
            _FakeFile("video/x-matroska")) is True

    def test_subtitle_content_type_is_not_video(self):
        assert GsubApplication._is_video_file(
            _FakeFile("application/x-subrip")) is False
        assert GsubApplication._is_video_file(_FakeFile("text/plain")) is False

    def test_query_failure_falls_back_to_subtitle(self):
        # Any failure to query must not crash; the file then goes through
        # the regular subtitle path.
        assert GsubApplication._is_video_file(_FakeFile(fail_query=True)) is False


@pytest.mark.unit
class TestOpenDispatch:
    def test_video_file_routed_to_open_video(self, app):
        app.do_activate()
        video = _FakeFile("video/mp4", name="movie.mkv")

        app.do_open([video], 1, "")

        assert app.window.opened_videos == [video]
        assert app.window.opened_files == []

    def test_subtitle_file_routed_to_open_file(self, app):
        app.do_activate()
        subtitle = _FakeFile("application/x-subrip", name="subs.srt")

        app.do_open([subtitle], 1, "")

        assert app.window.opened_files == [subtitle]
        assert app.window.opened_videos == []

    def test_open_activates_window_when_not_yet_created(self, app):
        # Cold start via "Open With": no window exists before do_open.
        assert app.window is None
        subtitle = _FakeFile("text/plain")

        app.do_open([subtitle], 1, "")

        assert len(app._created_windows) == 1
        assert app.window.opened_files == [subtitle]

    def test_only_first_file_is_opened(self, app):
        app.do_activate()
        first = _FakeFile("text/plain", name="a.srt")
        second = _FakeFile("video/mp4", name="b.mkv")

        app.do_open([first, second], 2, "")

        assert app.window.opened_files == [first]
        assert app.window.opened_videos == []

    def test_empty_file_list_just_activates(self, app):
        app.do_open([], 0, "")
        assert app.window is not None
        assert app.window.opened_files == []
        assert app.window.opened_videos == []
