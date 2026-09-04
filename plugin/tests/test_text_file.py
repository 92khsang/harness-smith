"""Reading a whole file's bytes as text, in one open.

The split that has to hold is "nothing is there" against "something is there and would not
read": a caller that cannot tell them apart reads a botched file as a deliberate silence.
"""

from __future__ import annotations

import os
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
    assert file.reason == "the path is not a regular file"
    assert file.text == ""


def test_a_link_with_nothing_at_the_other_end_is_unreadable_rather_than_absent(
    tmp_path: Path,
) -> None:
    """The entry is there, and reading it as silence would let a broken link pass for a
    deliberate decision to declare nothing."""
    path = tmp_path / "harness.manifest.yaml"
    path.symlink_to(tmp_path / "gone.yaml")

    file = read_text_file(path)

    assert file.state is TextFileState.UNREADABLE
    assert file.reason == "the path is a symbolic link with nothing at the other end"


def test_a_link_to_a_file_is_read_as_the_file_it_names(tmp_path: Path) -> None:
    (tmp_path / "elsewhere.yaml").write_text("schemaVersion: 1\n", encoding="utf-8")
    path = tmp_path / "harness.manifest.yaml"
    path.symlink_to(tmp_path / "elsewhere.yaml")

    file = read_text_file(path)

    assert file.state is TextFileState.PRESENT
    assert file.text == "schemaVersion: 1\n"


@pytest.mark.skipif(not hasattr(os, "mkfifo"), reason="the platform has no named pipes")
def test_a_named_pipe_answers_instead_of_waiting_for_a_writer(tmp_path: Path) -> None:
    """A pipe with no writer would hold a blocking read open for as long as nobody writes, so
    the open is non-blocking and what it found is answered on."""
    path = tmp_path / "harness.lock.json"
    os.mkfifo(path)

    file = read_text_file(path)

    assert file.state is TextFileState.UNREADABLE
    assert file.reason == "the path is not a regular file"


def test_no_reason_repeats_what_the_operating_system_called_it(tmp_path: Path) -> None:
    """A message built from `strerror` differs by platform and locale, and a result document
    that has to read the same on two machines cannot carry one."""
    directory = tmp_path / "harness.lock.json"
    directory.mkdir()

    reasons = {read_text_file(directory).reason, read_text_file(tmp_path / "gone.json").reason}

    assert not any("Is a directory" in reason or "No such file" in reason for reason in reasons)


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
