from collections import defaultdict
from datetime import date, timedelta
from pathlib import Path

import numpy as np
import pytest

from builders import at, klass, lecturer, make_problem, make_schedule, room, section, subject
from solver.calendar import _bit, expand_calendar
from solver.dsatur import dsatur
from solver.evaluate import evaluate
from solver.problem import load_snapshot

SEEDS = Path(__file__).resolve().parents[2] / "db" / "seeds"
MONDAY = date(2026, 9, 7)   # ngày bắt đầu học kỳ trong builders


def week_day(w: int, d: int) -> date:
    """Tuần w (từ 1), thứ d (1 = Thứ 2)."""
    return MONDAY + timedelta(days=7 * (w - 1) + d - 1)


def run(p, lecturers, starts, holidays=()):
    s = make_schedule(p, lecturers, starts)
    return expand_calendar(p, s, evaluate(p, s).room, list(holidays))


def by_section(result, s):
    return [x for x in result.sessions if x.section == s]


def test_pattern_without_holidays():
    # 4 TC: 60 tiết, 4 tiết/buổi, 2 buổi/tuần (Thứ 2, Thứ 4) -> 15 buổi, 8 tuần
    p = make_problem(rooms=[room(1)], lecturers=[lecturer(1, [1])], subjects=[subject(1, 4)],
                     classes=[klass(1)], sections=[section(1, 1, 1, 4)])
    r = run(p, [0], [at(1, 1), at(3, 7)])
    ss = by_section(r, 0)
    assert len(ss) == 15 and sum(x.length for x in ss) == 60
    assert [x.seq_no for x in ss] == list(range(1, 16))
    assert {x.date.isoweekday() for x in ss} == {1, 3}
    assert ss[0].date == week_day(1, 1) and ss[-1].date == week_day(8, 1)   # tuần 8 chỉ còn buổi Thứ 2
    assert r.h9 == 0 and not r.makeups and not r.shifted


def test_last_session_is_shorter():
    # 2 TC = 30 tiết, ép 4 tiết/buổi -> 8 buổi, buổi cuối 30 - 7*4 = 2 tiết
    p = make_problem(rooms=[room(1)], lecturers=[lecturer(1, [1])], subjects=[subject(1, 2)],
                     classes=[klass(1)], sections=[section(1, 1, 1, 2, periods_per_session=4)])
    ss = by_section(run(p, [0], [at(2, 1)]), 0)
    assert [x.length for x in ss] == [4] * 7 + [2]


def test_holiday_shifts_pattern_to_next_week():
    p = make_problem(rooms=[room(1)], lecturers=[lecturer(1, [1])], subjects=[subject(1, 3)],
                     classes=[klass(1)], sections=[section(1, 1, 1, 3)])          # 15 buổi, 2 buổi/tuần
    r = run(p, [0], [at(1, 1), at(4, 1)], holidays=[week_day(2, 1)])               # nghỉ Thứ 2 tuần 2
    ss = by_section(r, 0)
    assert len(ss) == 15
    assert week_day(2, 1) not in {x.date for x in ss}
    assert ss[-1].date == week_day(8, 4)            # bình thường kết thúc Thứ 2 tuần 8, nay lùi sang Thứ 5
    assert r.shifted == [0] and r.holidays_hit == {0: 1} and not r.makeups and r.h9 == 0


def _full_term_problem(lect_unavailable=()):
    """Môn 2 TC ép 2 tiết/buổi -> 15 buổi x 1 buổi/tuần = kín đủ 15 tuần, không còn tuần dư để lùi."""
    return make_problem(rooms=[room(1)], lecturers=[lecturer(1, [1], unavailable=lect_unavailable)],
                        subjects=[subject(1, 2)], classes=[klass(1)],
                        sections=[section(1, 1, 1, 2, periods_per_session=2)])


def test_makeup_when_no_week_left():
    p = _full_term_problem()
    r = run(p, [0], [at(1, 1)], holidays=[week_day(5, 1)])
    ss = by_section(r, 0)
    assert len(ss) == 15
    makeup = [x for x in ss if x.is_makeup]
    assert len(makeup) == 1 and r.makeups == {0: 1} and r.h9 == 0
    m = makeup[0]
    assert m.date != week_day(5, 1) and m.date <= week_day(15, 6)
    assert m.date == MONDAY + timedelta(days=1)       # chỗ sớm nhất: Thứ 3 tuần 1
    assert m.start_period == 1                        # cùng tiết như tuần mẫu


def test_makeup_respects_lecturer_unavailability():
    # Giảng viên chỉ rảnh sáng Thứ 2 và sáng Thứ 5 (day 4) -> buổi bù phải rơi vào Thứ 5
    busy = [(d, 1, 12) for d in (2, 3, 5, 6)] + [(1, 7, 12), (4, 7, 12)]
    p = _full_term_problem(lect_unavailable=busy)
    r = run(p, [0], [at(1, 1)], holidays=[week_day(5, 1)])
    m = [x for x in by_section(r, 0) if x.is_makeup]
    assert len(m) == 1 and m[0].date.isoweekday() == 4 and m[0].start_period <= 5


def test_h9_when_no_makeup_slot():
    # Giảng viên chỉ rảnh tiết 1-2 sáng Thứ 2; Thứ 2 nào cũng đã có buổi của chính lớp-môn này
    busy = [(1, 3, 12)] + [(d, 1, 12) for d in range(2, 7)]
    p = _full_term_problem(lect_unavailable=busy)
    r = run(p, [0], [at(1, 1)], holidays=[week_day(5, 1)])
    assert r.missing == {0: 1} and r.h9 == 1
    assert len(by_section(r, 0)) == 14


@pytest.mark.parametrize("extra", [[], [date(2026, 9, 21), date(2026, 9, 22)]])
def test_no_overlaps_and_complete_on_generated_data(extra):
    p = load_snapshot(SEEDS / "medium.snapshot.json")
    s = dsatur(p, np.random.default_rng(0), room_aware=False)
    r = expand_calendar(p, s, evaluate(p, s).room, extra)
    per_sec = defaultdict(list)
    for x in r.sessions:
        per_sec[x.section].append(x)
    for sec, ss in per_sec.items():
        assert len(ss) == p.sec_total_sessions[sec]
        assert sum(x.length for x in ss) == p.sec_total_periods[sec]
        assert len({x.date for x in ss}) == len(ss)            # không 2 buổi một ngày
    assert r.h9 == 0
    # Không trùng lớp / giảng viên / phòng trong cùng một ngày
    for key in ("class", "lecturer", "room"):
        used: dict = defaultdict(int)
        for x in r.sessions:
            owner = {"class": p.sec_class[x.section], "lecturer": x.lecturer, "room": x.room}[key]
            if key == "room" and owner < 0:
                continue
            m = _bit(x.start_period - 1, x.length)
            assert used[(x.date, owner)] & m == 0, f"trùng {key} ngày {x.date}"
            used[(x.date, owner)] |= m
    holidays = set(extra) | {date.fromisoformat(h["date"]) for h in p.snapshot["semester"]["holidays"]}
    assert not any(x.date in holidays for x in r.sessions)
