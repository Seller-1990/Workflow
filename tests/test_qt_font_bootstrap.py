"""Conditional font bootstrap tests without changing the real Qt/font configuration."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

import _qt_font_bootstrap as bootstrap


@pytest.fixture
def fake_qt(monkeypatch, tmp_path):
    state = SimpleNamespace(
        application=None, created=0, families=[], coverage={}, registrations=[], removed=[],
        loaded_family="CJK Text", loaded_chars=set(bootstrap._TEXT_SAMPLE), font_id=7,
    )

    class Application:
        def __init__(self, args):
            state.created += 1
            state.application = self
            self.font = object()
            self.style = object()

        @classmethod
        def instance(cls):
            return state.application

    class Font:
        def __init__(self, family):
            self.family = family

        def setPixelSize(self, size):
            assert size > 0

    class Metrics:
        def __init__(self, font):
            self.family = font.family

        def inFontUcs4(self, codepoint):
            return chr(codepoint) in state.coverage.get(self.family, set())

        def horizontalAdvance(self, text):
            return sum(10 for char in text if self.inFontUcs4(ord(char)))

    class Database:
        @staticmethod
        def families():
            return list(state.families)

        @staticmethod
        def addApplicationFont(filename):
            state.registrations.append(filename)
            if state.font_id >= 0:
                state.families.append(state.loaded_family)
                state.coverage[state.loaded_family] = state.loaded_chars
            return state.font_id

        @staticmethod
        def removeApplicationFont(font_id):
            state.removed.append(font_id)
            state.families.remove(state.loaded_family)
            state.coverage.pop(state.loaded_family)
            return True

    monkeypatch.setattr(bootstrap, "sys", SimpleNamespace(platform="win32", argv=["pytest"]))
    monkeypatch.setattr(bootstrap, "os", SimpleNamespace(environ={"QT_QPA_PLATFORM": "offscreen"}))
    monkeypatch.setattr(bootstrap, "_APPLICATION", None)
    monkeypatch.setattr(bootstrap, "_qt_types", lambda: (Application, Database, Font, Metrics))
    font_path = tmp_path / "existing-cjk.ttc"
    font_path.write_bytes(b"test double; never loaded into Qt")
    monkeypatch.setattr(bootstrap, "_local_font_paths", lambda: (font_path,))
    return state, Application, font_path


@pytest.mark.parametrize("platform,qpa", [("linux", "offscreen"), ("darwin", "offscreen"), ("win32", "windows"), ("win32", "")])
def test_ordinary_platforms_do_not_import_qt_or_create_application(monkeypatch, platform, qpa):
    monkeypatch.setattr(bootstrap, "sys", SimpleNamespace(platform=platform, argv=["pytest"]))
    monkeypatch.setattr(bootstrap, "os", SimpleNamespace(environ={"QT_QPA_PLATFORM": qpa}))
    monkeypatch.setattr(bootstrap, "_qt_types", lambda: pytest.fail("ordinary platform must be untouched"))

    bootstrap.bootstrap_text_font_for_offscreen()


@pytest.mark.parametrize("argument", ["-h", "--help"])
def test_help_does_not_import_qt_or_product_modules(monkeypatch, argument):
    monkeypatch.setattr(bootstrap, "sys", SimpleNamespace(platform="win32", argv=["pytest", argument]))
    monkeypatch.setattr(bootstrap, "os", SimpleNamespace(environ={"QT_QPA_PLATFORM": "offscreen"}))
    monkeypatch.setattr(bootstrap, "_qt_types", lambda: pytest.fail("help must be import-light"))

    bootstrap.bootstrap_text_font_for_offscreen()


def test_fontless_process_registers_existing_font_once_and_keeps_application(fake_qt):
    state, Application, font_path = fake_qt

    bootstrap.bootstrap_text_font_for_offscreen()
    app = Application.instance()
    original_font, original_style = app.font, app.style
    bootstrap.bootstrap_text_font_for_offscreen()

    assert state.created == 1
    assert bootstrap._APPLICATION is app
    assert state.registrations == [str(font_path)]
    assert state.removed == []
    assert app.font is original_font
    assert app.style is original_style


def test_existing_usable_font_and_application_are_untouched(fake_qt):
    state, Application, _ = fake_qt
    app = Application([])
    state.families = ["Existing CJK"]
    state.coverage["Existing CJK"] = set(bootstrap._TEXT_SAMPLE)
    original_font, original_style = app.font, app.style

    bootstrap.bootstrap_text_font_for_offscreen()

    assert state.created == 1
    assert bootstrap._APPLICATION is app
    assert state.registrations == []
    assert app.font is original_font
    assert app.style is original_style


def test_icon_only_or_latin_only_fonts_do_not_satisfy_text_capability(fake_qt):
    state, _, font_path = fake_qt
    state.families = ["codicon", "Latin Text"]
    state.coverage = {"codicon": {""}, "Latin Text": set("ABCxyz012")}

    bootstrap.bootstrap_text_font_for_offscreen()

    assert state.registrations == [str(font_path)]
    assert state.families == ["codicon", "Latin Text", "CJK Text"]


def test_missing_local_font_fails_actionably_instead_of_skipping(fake_qt, monkeypatch, tmp_path):
    state, _, _ = fake_qt
    missing = tmp_path / "missing-cjk.ttc"
    monkeypatch.setattr(bootstrap, "_local_font_paths", lambda: (missing,))

    with pytest.raises(RuntimeError, match="no usable Chinese/Latin text font") as error:
        bootstrap.bootstrap_text_font_for_offscreen()

    assert str(missing) in str(error.value)
    assert "icon-only fonts cannot validate text geometry" in str(error.value)
    assert state.registrations == []


def test_failed_font_registration_fails_actionably(fake_qt):
    state, _, font_path = fake_qt
    state.font_id = -1

    with pytest.raises(RuntimeError, match="No fonts were downloaded or installed"):
        bootstrap.bootstrap_text_font_for_offscreen()

    assert state.registrations == [str(font_path)]
    assert state.removed == []


def test_registered_font_without_cjk_glyphs_is_removed_and_fails(fake_qt):
    state, _, font_path = fake_qt
    state.loaded_chars = set("ABCxyz012")

    with pytest.raises(RuntimeError, match="no usable Chinese/Latin text font"):
        bootstrap.bootstrap_text_font_for_offscreen()

    assert state.registrations == [str(font_path)]
    assert state.removed == [state.font_id]
    assert state.families == []


def test_existing_core_application_fails_without_creating_another(fake_qt):
    state, _, _ = fake_qt
    state.application = object()

    with pytest.raises(RuntimeError, match="existing QCoreApplication"):
        bootstrap.bootstrap_text_font_for_offscreen()

    assert state.created == 0
    assert state.registrations == []


def test_local_candidates_only_use_existing_windows_fonts_directory(monkeypatch, tmp_path):
    monkeypatch.setattr(bootstrap, "os", SimpleNamespace(environ={"WINDIR": str(tmp_path)}))

    paths = bootstrap._local_font_paths()

    assert paths[0] == tmp_path / "Fonts" / "msyh.ttc"
    assert all(path.parent == tmp_path / "Fonts" for path in paths)
