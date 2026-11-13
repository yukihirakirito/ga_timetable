from pathlib import Path

import numpy as np
import pytest

from builders import at, klass, lecturer, make_problem, make_schedule, room, section, subject
from solver.dsatur import dsatur
from solver.evaluate import evaluate
from solver.localsearch import Workspace, improve, repair
from solver.problem import load_snapshot
from solver.schedule import domain_errors, random_schedule

SEEDS = Path(__file__).resolve().parents[2] / "db" / "seeds"
COUNTERS = ["class_cnt", "lect_cnt", "grp_cnt", "sec_day", "class_day", "lect_day", "load"]


@pytest.fixture(scope="module")
def medium():
    return load_snapshot(SEEDS / "medium.snapshot.json")


def test_delta_updates_match_rebuild(medium):
    """Sau hàng trăm lần dời buổi / đổi giảng viên, mảng đếm cập nhật delta phải khớp khi dựng lại từ đầu."""
    p, rng = medium, np.random.default_rng(0)
    ws = Workspace(p, random_schedule(p, rng))
    for _ in range(300):
        e = int(rng.integers(p.n_events))
        ws.move(e, int(rng.choice(p.ev_domain(e))))
        s = int(rng.integers(p.n_sections))
        ws.set_lecturer(s, int(rng.choice(p.sec_candidates[s])))
    fresh = Workspace(p, ws.schedule())
    for name in COUNTERS:
        assert np.array_equal(getattr(ws, name), getattr(fresh, name)), name


def _two_classes():
    return make_problem(rooms=[room(1), room(2)], lecturers=[lecturer(1, [1], unavailable=[(6, 1, 6)]), lecturer(2, [1])],
                        subjects=[subject(1, 2)], classes=[klass(1), klass(2)],
                        sections=[section(1, 1, 1, 2), section(2, 2, 1, 2)])


@pytest.mark.parametrize("lecturers, starts, expected", [
    ([0, 1], [at(1, 1), at(1, 1)], []),          # khác giảng viên, đủ phòng: hợp lệ
    ([0, 0], [at(1, 1), at(1, 2)], [0, 1]),      # H2: cùng giảng viên chồng giờ
    ([0, 1], [at(6, 1), at(2, 1)], [0]),         # H5: GV1 bận sáng Thứ 7
])
def test_conflicted_events(lecturers, starts, expected):
    p = _two_classes()
    ws = Workspace(p, make_schedule(p, lecturers, starts))
    assert ws.conflicted_events().tolist() == expected


def test_conflicted_events_detects_room_shortage():
    # 1 phòng 40 chỗ; hai lớp 30 SV cùng giờ -> thiếu phòng (điều kiện Hall)
    p = make_problem(rooms=[room(1, capacity=40)], lecturers=[lecturer(1, [1]), lecturer(2, [1])],
                     subjects=[subject(1, 2)], classes=[klass(1), klass(2)],
                     sections=[section(1, 1, 1, 2), section(2, 2, 1, 2)])
    ws = Workspace(p, make_schedule(p, [0, 1], [at(1, 1), at(1, 2)]))
    assert ws.conflicted_events().tolist() == [0, 1]


def test_best_move_never_worsens_and_stays_in_domain(medium):
    p, rng = medium, np.random.default_rng(1)
    ws = Workspace(p, random_schedule(p, rng))
    for e in rng.integers(0, p.n_events, size=200):
        assert ws.best_move(int(e), rng) >= 0
    assert domain_errors(p, ws.schedule()) == []


def test_repair_reaches_zero_hard_from_random(medium):
    p, rng = medium, np.random.default_rng(2)
    ws = Workspace(p, random_schedule(p, rng))
    assert repair(ws, rng, max_steps=5000) == 0
    assert evaluate(p, ws.schedule()).hard_total == 0


def test_improve_lowers_soft_penalty(medium):
    p, rng = medium, np.random.default_rng(3)
    start = dsatur(p, np.random.default_rng(0), room_aware=False)
    ws = Workspace(p, start)
    repair(ws, rng, max_steps=2000)
    before = evaluate(p, ws.schedule())
    improve(ws, rng, steps=1000)
    repair(ws, rng, max_steps=2000)
    after = evaluate(p, ws.schedule())
    assert after.hard_total == 0
    assert after.soft_penalty < before.soft_penalty
