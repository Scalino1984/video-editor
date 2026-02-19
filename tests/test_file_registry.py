"""Tests for the central file registry (cross-tool file tracking & cleanup)."""

from __future__ import annotations

import pytest
from pathlib import Path


@pytest.fixture
def db_path(tmp_path):
    return tmp_path / "test_registry.sqlite"


@pytest.fixture
def setup_db(db_path):
    from src.db.library import init_db, close_db
    init_db(db_path)
    yield
    close_db()


# ── File Registry CRUD ────────────────────────────────────────────────────────

def test_register_file(setup_db):
    from src.db.library import register_file, get_registered_file

    file_id = register_file(
        storage_path="/data/uploads/song.mp3",
        original_name="song.mp3",
        file_type="original",
        tool_scope="karaoke",
        size=1024,
    )
    assert file_id

    rec = get_registered_file(file_id)
    assert rec is not None
    assert rec["original_name"] == "song.mp3"
    assert rec["file_type"] == "original"
    assert rec["tool_scope"] == "karaoke"
    assert rec["state"] == "active"
    assert rec["size"] == 1024


def test_register_file_dedup(setup_db):
    from src.db.library import register_file

    id1 = register_file(
        storage_path="/data/uploads/song.mp3",
        original_name="song.mp3",
    )
    id2 = register_file(
        storage_path="/data/uploads/song.mp3",
        original_name="song.mp3",
    )
    assert id1 == id2


def test_get_file_by_path(setup_db):
    from src.db.library import register_file, get_file_by_path

    register_file(
        storage_path="/data/uploads/track.wav",
        original_name="track.wav",
    )
    rec = get_file_by_path("/data/uploads/track.wav")
    assert rec is not None
    assert rec["original_name"] == "track.wav"

    assert get_file_by_path("/nonexistent/path") is None


def test_list_registered_files(setup_db):
    from src.db.library import register_file, list_registered_files

    register_file(
        storage_path="/data/uploads/a.mp3",
        original_name="a.mp3",
        tool_scope="karaoke",
        file_type="original",
    )
    register_file(
        storage_path="/data/editor/assets/b.mp4",
        original_name="b.mp4",
        tool_scope="editor",
        file_type="project_asset",
    )

    all_files = list_registered_files()
    assert len(all_files) == 2

    karaoke_only = list_registered_files(tool_scope="karaoke")
    assert len(karaoke_only) == 1
    assert karaoke_only[0]["original_name"] == "a.mp3"

    editor_only = list_registered_files(tool_scope="editor")
    assert len(editor_only) == 1
    assert editor_only[0]["original_name"] == "b.mp4"


def test_update_file_state(setup_db):
    from src.db.library import register_file, get_registered_file, update_file_state

    file_id = register_file(
        storage_path="/data/uploads/x.mp3",
        original_name="x.mp3",
    )
    assert get_registered_file(file_id)["state"] == "active"

    update_file_state(file_id, "deleted")
    assert get_registered_file(file_id)["state"] == "deleted"


def test_update_file_scope(setup_db):
    from src.db.library import register_file, get_registered_file, update_file_scope

    file_id = register_file(
        storage_path="/data/uploads/x.mp3",
        original_name="x.mp3",
        tool_scope="karaoke",
    )
    update_file_scope(file_id, "both")
    assert get_registered_file(file_id)["tool_scope"] == "both"


# ── File References ───────────────────────────────────────────────────────────

def test_add_and_get_references(setup_db):
    from src.db.library import register_file, add_file_reference, get_file_references

    file_id = register_file(
        storage_path="/data/uploads/song.mp3",
        original_name="song.mp3",
    )

    add_file_reference(file_id, "job", "job123")
    add_file_reference(file_id, "project", "proj456")

    refs = get_file_references(file_id)
    assert len(refs) == 2
    ref_types = {r["ref_type"] for r in refs}
    assert ref_types == {"job", "project"}


def test_add_reference_dedup(setup_db):
    from src.db.library import register_file, add_file_reference, get_file_references

    file_id = register_file(
        storage_path="/data/uploads/song.mp3",
        original_name="song.mp3",
    )

    id1 = add_file_reference(file_id, "job", "job123")
    id2 = add_file_reference(file_id, "job", "job123")
    assert id1 == id2

    refs = get_file_references(file_id)
    assert len(refs) == 1


def test_remove_file_references(setup_db):
    from src.db.library import (
        register_file, add_file_reference, remove_file_references,
        get_file_references,
    )

    file_id = register_file(
        storage_path="/data/uploads/song.mp3",
        original_name="song.mp3",
    )
    add_file_reference(file_id, "job", "job123")
    add_file_reference(file_id, "project", "proj456")

    removed = remove_file_references("job", "job123")
    assert removed == 1

    refs = get_file_references(file_id)
    assert len(refs) == 1
    assert refs[0]["ref_type"] == "project"


def test_get_references_by_ref(setup_db):
    from src.db.library import register_file, add_file_reference, get_references_by_ref

    fid1 = register_file(
        storage_path="/data/editor/assets/a.mp3",
        original_name="a.mp3",
    )
    fid2 = register_file(
        storage_path="/data/editor/assets/b.srt",
        original_name="b.srt",
    )
    add_file_reference(fid1, "project", "proj1")
    add_file_reference(fid2, "project", "proj1")

    refs = get_references_by_ref("project", "proj1")
    assert len(refs) == 2


def test_check_file_has_references(setup_db):
    from src.db.library import register_file, add_file_reference, check_file_has_references

    file_id = register_file(
        storage_path="/data/uploads/song.mp3",
        original_name="song.mp3",
    )
    assert check_file_has_references(file_id) is False

    add_file_reference(file_id, "job", "job123")
    assert check_file_has_references(file_id) is True


# ── Orphan Detection ──────────────────────────────────────────────────────────

def test_find_orphaned_files(setup_db):
    from src.db.library import (
        register_file, add_file_reference, find_orphaned_files,
    )

    # File with reference — not an orphan
    fid1 = register_file(
        storage_path="/data/uploads/referenced.mp3",
        original_name="referenced.mp3",
    )
    add_file_reference(fid1, "job", "job123")

    # File without reference — orphan
    register_file(
        storage_path="/data/uploads/orphan.mp3",
        original_name="orphan.mp3",
    )

    orphans = find_orphaned_files()
    assert len(orphans) == 1
    assert orphans[0]["original_name"] == "orphan.mp3"


def test_find_files_for_job(setup_db):
    from src.db.library import register_file, find_files_for_job

    register_file(
        storage_path="/data/output/job1/song.srt",
        original_name="song.srt",
        job_id="job1",
    )
    register_file(
        storage_path="/data/output/job2/other.srt",
        original_name="other.srt",
        job_id="job2",
    )

    files = find_files_for_job("job1")
    assert len(files) == 1
    assert files[0]["original_name"] == "song.srt"


def test_find_files_for_project(setup_db):
    from src.db.library import register_file, find_files_for_project

    register_file(
        storage_path="/data/editor/assets/a.mp3",
        original_name="a.mp3",
        project_id="proj1",
    )
    files = find_files_for_project("proj1")
    assert len(files) == 1


# ── Delete with reference check ──────────────────────────────────────────────

def test_delete_registered_file_soft(setup_db):
    from src.db.library import register_file, get_registered_file, delete_registered_file

    file_id = register_file(
        storage_path="/data/uploads/song.mp3",
        original_name="song.mp3",
    )
    delete_registered_file(file_id, hard=False)
    rec = get_registered_file(file_id)
    assert rec is not None
    assert rec["state"] == "deleted"


def test_delete_registered_file_hard(setup_db):
    from src.db.library import register_file, get_registered_file, delete_registered_file

    file_id = register_file(
        storage_path="/data/uploads/song.mp3",
        original_name="song.mp3",
    )
    delete_registered_file(file_id, hard=True)
    assert get_registered_file(file_id) is None


def test_hard_delete_also_removes_references(setup_db):
    from src.db.library import (
        register_file, add_file_reference, get_file_references,
        delete_registered_file,
    )

    file_id = register_file(
        storage_path="/data/uploads/song.mp3",
        original_name="song.mp3",
    )
    add_file_reference(file_id, "job", "job123")
    add_file_reference(file_id, "project", "proj456")

    delete_registered_file(file_id, hard=True)
    refs = get_file_references(file_id)
    assert len(refs) == 0


# ── Cross-tool scenario: Karaoke delete with editor references ────────────────

def test_cascade_job_delete_marks_unreferenced_files(setup_db):
    """When a job is deleted, files only referenced by that job should be marked deleted."""
    from src.db.library import (
        register_file, add_file_reference, remove_file_references,
        get_file_references, get_registered_file, update_file_state,
    )

    # Simulate: file registered for a job AND a project
    file_id = register_file(
        storage_path="/data/editor/assets/song.srt",
        original_name="song.srt",
        job_id="job1",
        project_id="proj1",
    )
    add_file_reference(file_id, "job", "job1")
    add_file_reference(file_id, "project", "proj1")

    # Delete job references
    remove_file_references("job", "job1")

    # File still has project reference — should stay active
    refs = get_file_references(file_id)
    assert len(refs) == 1
    assert refs[0]["ref_type"] == "project"

    # Now delete project reference too
    remove_file_references("project", "proj1")
    refs = get_file_references(file_id)
    assert len(refs) == 0

    # Mark as deleted since no references remain
    if not refs:
        update_file_state(file_id, "deleted")
    assert get_registered_file(file_id)["state"] == "deleted"


def test_existing_tables_unaffected(setup_db):
    """File registry tables should not affect existing transcriptions/media tables."""
    from src.db.library import (
        save_transcription, list_transcriptions,
        register_media, list_media,
        register_file, list_registered_files,
    )

    # Existing functionality still works
    rec_id = save_transcription(
        source_filename="test.mp3", backend="voxtral", language="de",
    )
    records, total = list_transcriptions()
    assert total == 1

    media_id = register_media(
        filename="test.mp3", path="/data/uploads/test.mp3", size=100,
    )
    media = list_media()
    assert len(media) == 1

    # File registry is independent
    file_id = register_file(
        storage_path="/data/uploads/test.mp3",
        original_name="test.mp3",
    )
    files = list_registered_files()
    assert len(files) == 1
