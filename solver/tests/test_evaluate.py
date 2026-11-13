"""Mỗi ràng buộc: một ca vi phạm và một ca không vi phạm, các ràng buộc khác giữ ở mức nền."""

from pathlib import Path

import numpy as np
import pytest

from builders import at, klass, lecturer, make_problem, make_schedule, room, section, subject
from solver.evaluate import HARD_CODES, Weights, evaluate, violations
from solver.problem import load_snapshot
from solver.schedule import random_schedule

SEEDS = Path(__file__).resolve().parents[2] / "db" / "seeds"
ROOMS = [room(i) for i in range(1, 6)]


def two_classes_one_subject(**lect_kwargs):
    """2 lớp, mỗi lớp học môn 2 TC (1 buổi 3 tiết/tuần), 2 giảng viên dạy được."""
    return make_problem(rooms=ROOMS,
                        lecturers=[lecturer(1, [1], **lect_kwargs), lecturer(2, [1])],
                        subjects=[subject(1, 2)],
                        classes=[klass(1), klass(2)],
                        sections=[section(1, 1, 1, 2), section(2, 2, 1, 2)])


def one_class_two_subjects(credits=(2, 2), pps=(None, None)):
    return make_problem(rooms=ROOMS,
                        lecturers=[lecturer(1, [1, 2]), lecturer(2, [1, 2])],
                        subjects=[subject(1, credits[0]), subject(2, credits[1])],
                        classes=[klass(1)],
                        sections=[section(1, 1, 1, credits[0], pps[0]), section(2, 1, 2, credits[1], pps[1])])


# --- Cứng ---------------------------------------------------------------------

@pytest.mark.parametrize("second_start, expected", [(at(1, 2), 2), (at(1, 4), 0), (at(2, 1), 0)])
def test_h1_class_overlap_counts_periods(second_start, expected):
    p = one_class_two_subjects()
    ev = evaluate(p, make_schedule(p, [0, 1], [at(1, 1), second_start]))
    assert ev.hard["H1"] == expected


@pytest.mark.parametrize("lecturers, expected", [([0, 0], 3), ([0, 1], 0)])
def test_h2_lecturer_overlap(lecturers, expected):
    p = two_classes_one_subject()
    ev = evaluate(p, make_schedule(p, lecturers, [at(1, 1), at(1, 1)]))
    assert ev.hard["H2"] == expected


def test_h3_not_enough_rooms():
    p = make_problem(rooms=[room(1)], lecturers=[lecturer(1, [1]), lecturer(2, [1])], subjects=[subject(1, 2)],
                     classes=[klass(1), klass(2)], sections=[section(1, 1, 1, 2), section(2, 2, 1, 2)])
    assert evaluate(p, make_schedule(p, [0, 1], [at(1, 1), at(1, 1)])).hard["H3"] == 1
    assert evaluate(p, make_schedule(p, [0, 1], [at(1, 1), at(1, 4)])).hard["H3"] == 0


@pytest.mark.parametrize("start, expected", [(at(2, 1), 3), (at(2, 4), 3), (at(2, 7), 0)])
def test_h5_unavailable(start, expected):
    p = two_classes_one_subject(unavailable=[(2, 1, 6)])   # GV1 bận sáng Thứ 3
    ev = evaluate(p, make_schedule(p, [0, 1], [start, at(5, 1)]))
    assert ev.hard["H5"] == expected


@pytest.mark.parametrize("second_day, expected", [(1, 1), (3, 0)])
def test_h6_same_section_same_day(second_day, expected):
    p = make_problem(rooms=ROOMS, lecturers=[lecturer(1, [1])], subjects=[subject(1, 3)],
                     classes=[klass(1)], sections=[section(1, 1, 1, 3)])   # 3 TC: 2 buổi/tuần
    ev = evaluate(p, make_schedule(p, [0], [at(1, 1), at(second_day, 7)]))
    assert ev.hard["H6"] == expected


def test_h4_is_always_zero_on_random_schedules():
    p = load_snapshot(SEEDS / "large.snapshot.json")
    for seed in range(5):
        assert evaluate(p, random_schedule(p, np.random.default_rng(seed))).hard["H4"] == 0


# --- Mềm ----------------------------------------------------------------------

def test_s1_gap_and_days():
    p = one_class_two_subjects(pps=(2, 2))      # 2 buổi dài 2 tiết
    compact = evaluate(p, make_schedule(p, [0, 1], [at(1, 1), at(1, 3)]))
    gap = evaluate(p, make_schedule(p, [0, 1], [at(1, 1), at(1, 5)]))      # trống tiết 3-4
    two_days = evaluate(p, make_schedule(p, [0, 1], [at(1, 1), at(2, 1)]))
    assert compact.soft["S1"] == 1               # 0 tiết trống + 1 ngày
    assert gap.soft["S1"] == 3                   # 2 tiết trống + 1 ngày
    assert two_days.soft["S1"] == 2              # 0 tiết trống + 2 ngày


@pytest.mark.parametrize("second_day, expected", [(2, 1), (3, 0)])
def test_s2_consecutive_days(second_day, expected):
    p = make_problem(rooms=ROOMS, lecturers=[lecturer(1, [1])], subjects=[subject(1, 3)],
                     classes=[klass(1)], sections=[section(1, 1, 1, 3)])
    ev = evaluate(p, make_schedule(p, [0], [at(1, 1), at(second_day, 1)]))
    assert ev.soft["S2"] == expected


def test_s3_is_removed():
    p = one_class_two_subjects()
    ev = evaluate(p, make_schedule(p, [0, 1], [at(1, 1), at(1, 7)]))   # học cả sáng lẫn chiều
    assert "S3" not in ev.soft
    assert not hasattr(Weights(), "S3")


def test_default_weights():
    w = Weights()
    assert (w.hard, w.S2, w.S8) == (10000, 5, 5)


def test_s4_lecturer_days():
    p = two_classes_one_subject()
    same_day = evaluate(p, make_schedule(p, [0, 0], [at(1, 1), at(1, 4)]))
    two_days = evaluate(p, make_schedule(p, [0, 0], [at(1, 1), at(2, 1)]))
    assert same_day.soft["S4"] == 1
    assert two_days.soft["S4"] == 2


def test_s5_unused_preferred_periods():
    p = two_classes_one_subject(preferred=[(4, 7, 12)])     # GV1 thích dạy chiều Thứ 5 (6 tiết)
    used = evaluate(p, make_schedule(p, [0, 1], [at(4, 7), at(1, 1)]))
    unused = evaluate(p, make_schedule(p, [0, 1], [at(1, 1), at(1, 1)]))
    assert used.soft["S5"] == 3
    assert unused.soft["S5"] == 6


def test_s6_load_balance():
    p = two_classes_one_subject()                # 2 GV cùng tối đa 20, tổng tải 6 -> mục tiêu 3 mỗi người
    assert evaluate(p, make_schedule(p, [0, 1], [at(1, 1), at(2, 1)])).soft["S6"] == 0
    assert evaluate(p, make_schedule(p, [0, 0], [at(1, 1), at(2, 1)])).soft["S6"] == 6


def test_s7_section_changes_room():
    # Lớp 1 (3 TC, 2 buổi) học Thứ 2 ở R1. Lớp 2 (35 SV, 1 buổi) đông hơn nên được xét trước.
    p = make_problem(rooms=[room(1, capacity=40), room(2, capacity=40)],
                     lecturers=[lecturer(1, [1, 2])], subjects=[subject(1, 3), subject(2, 2)],
                     classes=[klass(1, 30), klass(2, 35)],
                     sections=[section(1, 1, 1, 3), section(2, 2, 2, 2)])
    # event: [lớp1-buổi1, lớp1-buổi2, lớp2]
    # Thứ 4 lớp 2 học buổi chiều: R1 rảnh, lớp 1 giữ được R1
    kept = evaluate(p, make_schedule(p, [0, 0], [at(1, 1), at(3, 1), at(3, 7)]))
    assert kept.room[0] == kept.room[1]
    assert kept.soft["S7"] == 0
    # Thứ 4 lớp 2 học cùng giờ và lấy mất R1 -> lớp 1 phải sang R2
    moved = evaluate(p, make_schedule(p, [0, 0], [at(1, 1), at(3, 1), at(3, 1)]))
    assert moved.room[2] == 0 and moved.room[1] == 1
    assert moved.soft["S7"] == 1


def test_s8_over_max_load():
    p = two_classes_one_subject(max_periods=3)
    ok = evaluate(p, make_schedule(p, [0, 1], [at(1, 1), at(2, 1)]))
    over = evaluate(p, make_schedule(p, [0, 0], [at(1, 1), at(2, 1)]))
    assert ok.soft["S8"] == 0
    assert over.soft["S8"] == 3


# --- Fitness và báo cáo --------------------------------------------------------

def test_fitness_combines_weights():
    p = two_classes_one_subject(max_periods=3)
    w = Weights(hard=100, S8=7)
    ev = evaluate(p, make_schedule(p, [0, 0], [at(1, 1), at(1, 1)]), w)   # H2 = 3, S8 = 3
    expected_soft = sum(getattr(w, c) * v for c, v in ev.soft.items())
    assert ev.hard["H2"] == 3
    assert ev.soft_penalty == pytest.approx(expected_soft)
    assert ev.fitness == pytest.approx(100 * ev.hard_total + expected_soft)


def test_violations_report():
    p = two_classes_one_subject(max_periods=3)
    s = make_schedule(p, [0, 0], [at(1, 1), at(1, 2)])
    rows = violations(p, s, evaluate(p, s))
    h2 = [r for r in rows if r["code"] == "H2"]
    assert len(h2) == 1 and h2[0]["detail"]["periods"] == 2
    assert {x["class"] for x in h2[0]["detail"]["sessions"]} == {"C1", "C2"}
    s8 = [r for r in rows if r["code"] == "S8" and "lecturer" in r["detail"]]
    assert s8[0]["detail"] == {"lecturer": "GV1", "load": 6, "max": 3}
    assert all(r["severity"] == ("HARD" if r["code"] in HARD_CODES else "SOFT") for r in rows)
