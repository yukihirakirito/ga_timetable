from pathlib import Path

import numpy as np
import pytest

from builders import at, klass, lecturer, make_problem, room, section, subject
from solver.problem import Problem, SnapshotError, load_snapshot
from solver.schedule import domain_errors, random_schedule

SEEDS = Path(__file__).resolve().parents[2] / "db" / "seeds"


@pytest.mark.parametrize("name, weekly", [("small", 340), ("medium", 1236), ("large", 2349)])
def test_loads_generated_datasets(name, weekly):
    p = load_snapshot(SEEDS / f"{name}.snapshot.json")
    assert int(p.sec_weekly.sum()) == weekly
    assert p.n_events == int(p.sec_spw.sum())
    assert all(len(c) >= 2 for c in p.sec_candidates)
    s = random_schedule(p, np.random.default_rng(1))
    assert domain_errors(p, s) == []


def test_starts_never_cross_a_shift():
    p = load_snapshot(SEEDS / "small.snapshot.json")
    for length, starts in p.starts_by_len.items():
        period = starts % 12
        end = period + length - 1
        assert (p.shift_of_period[period] == p.shift_of_period[end]).all()
        # Buổi 5 tiết: 2 vị trí mỗi ca, 2 ca, 6 ngày
        if length == 5:
            assert len(starts) == 24


def _tiny(**overrides):
    args = dict(rooms=[room(1)], lecturers=[lecturer(1, [1])], subjects=[subject(1, credits=3)],
                classes=[klass(1)], sections=[section(1, 1, 1, credits=3)])
    args.update(overrides)
    return make_problem(**args)


def test_events_and_candidates():
    p = _tiny(lecturers=[lecturer(1, [1]), lecturer(2, [2]), lecturer(3, [1])],
              subjects=[subject(1, credits=3), subject(2)])
    assert p.n_events == 2                      # 3 TC: 2 buổi/tuần
    assert p.ev_len.tolist() == [3, 3]
    assert p.sec_candidates[0].tolist() == [0, 2]


def test_unavailable_mask():
    p = _tiny(lecturers=[lecturer(1, [1], unavailable=[(2, 7, 12)])])
    assert p.unavailable[0].sum() == 6
    assert p.unavailable[0, at(2, 7)] and p.unavailable[0, at(2, 12)]
    assert not p.unavailable[0, at(2, 6)]


def test_rejects_unknown_schema_version():
    p = _tiny()
    snap = dict(p.snapshot, schema_version="9.9")
    with pytest.raises(SnapshotError):
        Problem(snap)


def test_rejects_subject_without_lecturer():
    with pytest.raises(SnapshotError, match="không giảng viên nào"):
        _tiny(lecturers=[lecturer(1, [])])


def test_domain_errors_detect_h7_h8():
    p = _tiny(lecturers=[lecturer(1, [1]), lecturer(2, [])], subjects=[subject(1, credits=3), subject(2)])
    from solver.schedule import Schedule
    bad = Schedule(np.array([1]), np.array([at(1, 5), at(2, 1)]))  # GV2 không dạy được; tiết 5-7 vắt trưa
    errors = domain_errors(p, bad)
    assert any(e.startswith("H7") for e in errors)
    assert any(e.startswith("H8") for e in errors)
