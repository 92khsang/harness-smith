"""Reading a whole file's bytes as text, in one open.

The split that has to hold is "nothing is there" against "something is there and would not
read": a caller that cannot tell them apart reads a botched file as a deliberate silence.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from harness_smith.text_file import TextFile, TextFileState, read_text_file


def test_a_file_that_reads_hands_back_its_text(tmp_path: Path) -> None:
    path = tmp_path / "settings.json"
    path.write_text('{"model": "a"}\n', encoding="utf-8")

    file = read_text_file(path)

    assert file.state is TextFileState.PRESENT
    assert file.text == '{"model": "a"}\n'
    assert file.reason == ""


def test_nothing_at_the_path_is_absent(tmp_path: Path) -> None:
    assert read_text_file(tmp_path / "missing.json").state is TextFileState.ABSENT


def test_nothing_on_the_way_to_the_path_is_absent(tmp_path: Path) -> None:
    """A file where a directory would have to be means the named file cannot exist."""
    (tmp_path / "settings.json").write_text("{}", encoding="utf-8")

    assert read_text_file(tmp_path / "settings.json" / "nested.json").state is TextFileState.ABSENT


def test_a_directory_at_the_path_is_unreadable_rather_than_absent(tmp_path: Path) -> None:
    """Somebody put it there, so it is not a path that holds nothing."""
    path = tmp_path / "harness.lock.json"
    path.mkdir()

    file = read_text_file(path)

    assert file.state is TextFileState.UNREADABLE
    assert file.reason
    assert file.text == ""


def test_bytes_that_never_became_text_are_unreadable(tmp_path: Path) -> None:
    path = tmp_path / "settings.json"
    path.write_bytes(b'{"model": "\xff\xfe"}')

    file = read_text_file(path)

    assert file.state is TextFileState.UNREADABLE
    assert "UTF-8" in file.reason


def test_no_reason_names_the_path_it_came_from(tmp_path: Path) -> None:
    """A diagnostic carries the Locator in its subject, so a message stays free of paths."""
    path = tmp_path / "harness.manifest.yaml"
    path.mkdir()

    reason = read_text_file(path).reason

    assert str(tmp_path) not in reason
    assert "harness.manifest.yaml" not in reason


def test_only_a_file_that_read_carries_text() -> None:
    with pytest.raises(ValueError, match="only a file that read"):
        TextFile(TextFileState.ABSENT, text="{}", reason="there is no file at that path")


def test_a_file_that_read_carries_no_reason() -> None:
    with pytest.raises(ValueError, match="only then"):
        TextFile(TextFileState.PRESENT, text="{}", reason="the file could not be read")


def test_a_file_that_did_not_read_says_why() -> None:
    with pytest.raises(ValueError, match="only then"):
        TextFile(TextFileState.UNREADABLE)
