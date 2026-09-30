"""CSV import engine tests: messy-data rejection and idempotency."""
import pytest

from app.services.import_service import import_csv

SEED_CSV = "../seed/episodes.csv"  # relative to backend/ (pytest rootdir)


def test_seed_file_import_report(db):
    report = import_csv(db, SEED_CSV)
    assert report["imported"] == 172
    assert report["skipped"] == 17
    assert len(report["errors"]) == 17
    assert any("Row 59: Missing episode_id" in e for e in report["errors"])
    assert any("excellent" in e for e in report["errors"])
    assert any("'-5'" in e for e in report["errors"])
    assert any("45.5" in e for e in report["errors"])
    assert any("N/A" in e for e in report["errors"])
    assert any("arm-99" in e for e in report["errors"])


def test_reimport_is_idempotent(db):
    first = import_csv(db, SEED_CSV)
    assert first["imported"] == 172
    second = import_csv(db, SEED_CSV)
    assert second["imported"] == 0
    assert second["skipped"] == 189  # 172 already in DB + 17 invalid rows
    from app.models.episode import Episode

    assert db.query(Episode).count() == 172


def test_in_file_duplicates_are_skipped(db, tmp_path):
    path = tmp_path / "dup.csv"
    path.write_text(
        "episode_id,robot_id,task_name,recorded_at,duration_seconds,operator_name,quality\n"
        "EP-D1,arm-01,pick cup,2026-08-16T10:00:00,30,Aline,good\n"
        "EP-D1,arm-01,pick cup,2026-08-16T10:00:00,30,Aline,good\n",
        encoding="utf-8",
    )
    report = import_csv(db, str(path))
    assert report["imported"] == 1
    assert report["skipped"] == 1
    assert any("duplicate episode_id EP-D1" in e for e in report["errors"])


def test_case_variant_episode_ids_dedupe(db, tmp_path):
    """`ep-00003` in a file must dedupe against an existing `EP-00003`."""
    from app.models.episode import Episode

    from tests.conftest import make_episode

    make_episode(db, "EP-00003", task="fold towel")
    path = tmp_path / "case.csv"
    path.write_text(
        "episode_id,robot_id,task_name,recorded_at,duration_seconds,operator_name,quality\n"
        "ep-00003,arm-02,wipe table,2026-08-22T09:10:00,33,Eric,good\n",
        encoding="utf-8",
    )
    report = import_csv(db, str(path))
    assert report["imported"] == 0
    assert report["skipped"] == 1
    assert db.query(Episode).filter(Episode.episode_id == "EP-00003").count() == 1


def test_european_and_iso_dates_both_parse(db, tmp_path):
    path = tmp_path / "dates.csv"
    path.write_text(
        "episode_id,robot_id,task_name,recorded_at,duration_seconds,operator_name,quality\n"
        "EP-X1,arm-01,pick cup,14/08/2026 09:15,30,Aline,good\n"
        "EP-X2,arm-01,pick cup,2026-08-16T23:28:00,30,Aline,good\n"
        "EP-X3,arm-01,pick cup,2026-08-14T09:20:00Z,30,Aline,good\n",
        encoding="utf-8",
    )
    report = import_csv(db, str(path))
    assert report["imported"] == 3
    from app.models.episode import Episode

    x1 = db.query(Episode).filter(Episode.episode_id == "EP-X1").first()
    assert (x1.recorded_at.day, x1.recorded_at.month) == (14, 8)


def test_whitespace_and_casing_normalised(db, tmp_path):
    path = tmp_path / "messy.csv"
    path.write_text(
        "episode_id,robot_id,task_name,recorded_at,duration_seconds,operator_name,quality\n"
        "  EP-Y1 , Arm-01 ,  Pick Cup ,2026-08-16T10:00:00,30, Aline , GOOD \n",
        encoding="utf-8",
    )
    report = import_csv(db, str(path))
    assert report["imported"] == 1
    from app.models.episode import Episode

    row = db.query(Episode).filter(Episode.episode_id == "EP-Y1").first()
    assert row.robot_id == "arm-01"
    assert row.task_name == "pick cup"
    assert row.quality.value == "good"


def test_quoted_comma_field_survives(db, tmp_path):
    path = tmp_path / "quoted.csv"
    path.write_text(
        'episode_id,robot_id,task_name,recorded_at,duration_seconds,operator_name,quality\n'
        'EP-Z1,arm-01,"pick cup, then place",2026-08-16T10:00:00,30,Aline,good\n',
        encoding="utf-8",
    )
    report = import_csv(db, str(path))
    assert report["imported"] == 1
    from app.models.episode import Episode

    row = db.query(Episode).filter(Episode.episode_id == "EP-Z1").first()
    assert row.task_name == "pick cup, then place"


def test_missing_required_columns_rejected(db, tmp_path):
    path = tmp_path / "bad_header.csv"
    path.write_text("episode_id,robot_id\nEP-1,arm-01\n", encoding="utf-8")
    with pytest.raises(ValueError, match="missing required columns"):
        import_csv(db, str(path))


def test_missing_file_raises(db):
    with pytest.raises(FileNotFoundError):
        import_csv(db, "does/not/exist.csv")
