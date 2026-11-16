"""Sinh viên học thêm: snapshot 2.0 (M8a) và ràng buộc H10 trong solver (M8b)."""

from collections import defaultdict
from datetime import date, timedelta
from pathlib import Path

import numpy as np
import pytest

from builders import at, group, klass, lecturer, make_problem, make_schedule, room, section, subject
from solver.calendar import _bit, expand_calendar
from solver.dsatur import dsatur
from solver.evaluate import evaluate, violations
from solver.ga import GAParams, run_ga
from solver.localsearch import Workspace, repair
from solver.problem import SnapshotError, load_snapshot
from solver.schedule import random_schedule

SEEDS = Path(__file__).resolve().parents[2] / "db" / "seeds"


def _problem(student_groups=(), sections=None, rooms=None, classes=None):
    """Lớp 1 học môn 1, 2; lớp 2 học môn 3, 1; lớp 3 học môn 3. Mọi lớp 30 SV."""
    return make_problem(
        rooms=rooms or [room(1, capacity=60), room(2, capacity=60)],
        lecturers=[lecturer(1, [1, 2, 3]), lecturer(2, [1, 2, 3])],
        subjects=[subject(1), subject(2), subject(3)],
        classes=classes or [klass(1), klass(2), klass(3)],
        sections=sections or [section(1, 1, 1, 2), section(2, 1, 2, 2),
                              section(3, 2, 3, 2), section(4, 2, 1, 2), section(5, 3, 3, 2)],
        student_groups=student_groups)


def test_groups_and_section_size_are_loaded():
    p = _problem([group(1, [3], students=2), group(2, [2], students=1)])
    assert p.n_groups == 2
    assert p.group_class.tolist() == [0, 1]
    assert [g.tolist() for g in p.group_extra] == [[2], [1]]      # chỉ số lớp-môn (0-based)
    assert p.group_students.tolist() == [2, 1]
    assert p.sec_size.tolist() == [30, 31, 32, 30, 30]            # lớp-môn 2 +1 SV, lớp-môn 3 +2 SV
    assert p.ev_size[p.sec_events[2]].tolist() == [32]


def test_no_groups():
    p = _problem()
    assert p.n_groups == 0 and p.sec_size.tolist() == [30] * 5


@pytest.mark.parametrize("groups, needle", [
    ([group(1, [1])], "thuộc chính lớp"),                 # lớp-môn của chính lớp 1
    ([group(1, [99])], "không tồn tại"),
    ([group(9, [3])], "class_id 9 không tồn tại"),
    ([group(1, [4])], "trùng môn"),                        # lớp 1 đang học môn 1, lại học thêm môn 1 ở lớp 2
    ([group(1, [3, 5])], "hai lần"),                       # môn 3 ở cả lớp 2 và lớp 3
    ([group(1, [3]), group(1, [3])], "trùng nhóm"),        # phải gộp thành một nhóm 2 SV
    ([group(1, [3], students=31)], "> sĩ số lớp"),
])
def test_invalid_groups_rejected(groups, needle):
    with pytest.raises(SnapshotError, match=needle):
        _problem(groups)


def test_section_size_must_count_extra_students():
    secs = [section(1, 1, 1, 2), section(2, 1, 2, 2), {**section(3, 2, 3, 2), "size": 30},   # thiếu 2 SV học thêm
            section(4, 2, 1, 2), section(5, 3, 3, 2)]
    with pytest.raises(SnapshotError, match=r"size 30 != sĩ số lớp 30 \+ 2"):
        _problem([group(1, [3], students=2)], sections=secs)


def test_room_capacity_uses_section_size():
    rooms = [room(1, capacity=40), room(2, capacity=40)]
    _problem([group(1, [3], students=10)], rooms=rooms)                      # 30 + 10 = 40: vừa
    with pytest.raises(SnapshotError, match="không có phòng THEORY chứa được 41 SV") as exc:
        _problem([group(1, [3], students=10), group(3, [4], students=11)],  # lớp-môn 4: 30 + 11 = 41 > 40
                 rooms=rooms)
    assert len(exc.value.errors) == 1                                        # lớp-môn 3 (40) vẫn vừa phòng


@pytest.mark.parametrize("name, groups, students", [("small", 19, 20), ("medium", 68, 68), ("large", 124, 124)])
def test_generated_datasets_have_retake_groups(name, groups, students):
    p = load_snapshot(SEEDS / f"{name}.snapshot.json")
    assert p.n_groups == groups and int(p.group_students.sum()) == students
    # sĩ số lớp-môn >= sĩ số lớp
    assert (p.sec_size >= p.class_size[p.sec_class]).all()
    # nhóm không học thêm lớp-môn của chính lớp mình
    assert all((p.sec_class[g] != c).all() for g, c in zip(p.group_extra, p.group_class))


# --- M8b: H10 ----------------------------------------------------------------------

def _linked(extra_groups=((1, [3]),), n_class1=1):
    """Lớp 1 học môn 1 (và môn 4 nếu n_class1 = 2); lớp 2 học môn 2; lớp 3 học môn 3. Mỗi môn 2 TC = 1 buổi 3 tiết.
    Lớp-môn: 1 = (lớp 1, môn 1), 2 = (lớp 2, môn 2), 3 = (lớp 3, môn 3), 4 = (lớp 1, môn 4).
    Mỗi lớp-môn một giảng viên riêng, đủ phòng: chỉ H1 / H10 có thể vi phạm."""
    sections = [section(1, 1, 1, 2), section(2, 2, 2, 2), section(3, 3, 3, 2)]
    if n_class1 == 2:
        sections.append(section(4, 1, 4, 2))
    return make_problem(rooms=[room(i) for i in range(1, 6)],
                        lecturers=[lecturer(i, [i]) for i in range(1, len(sections) + 1)],
                        subjects=[subject(i) for i in range(1, len(sections) + 1)],
                        classes=[klass(1), klass(2), klass(3)], sections=sections,
                        student_groups=[group(c, x) for c, x in extra_groups])


@pytest.mark.parametrize("starts, h1, h10", [
    ([at(1, 1), at(1, 1), at(1, 2)], 0, 2),          # học thêm (lớp-môn 3) trùng 2 tiết với lớp 1
    ([at(1, 1), at(1, 1), at(1, 4)], 0, 0),          # nối tiếp, không trùng
    ([at(1, 1), at(1, 1), at(2, 1)], 0, 0),          # khác ngày
])
def test_h10_counts_overlap_between_class_and_extra(starts, h1, h10):
    p = _linked()
    ev = evaluate(p, make_schedule(p, [0, 1, 2], starts))
    assert (ev.hard["H1"], ev.hard["H10"]) == (h1, h10)


def test_h10_does_not_double_count_class_overlap():
    # Lớp 1 tự trùng 3 tiết (H1 = 3); buổi học thêm chồng lên cả hai: mỗi ô k_lớp = 2, k_thêm = 1
    # -> H10 = (2 + 1 - 1) - (2 - 1) = 1 mỗi ô = 3, không phải 6
    p = _linked(n_class1=2)
    ev = evaluate(p, make_schedule(p, [0, 1, 2, 3], [at(1, 1), at(3, 1), at(1, 1), at(1, 1)]))
    assert (ev.hard["H1"], ev.hard["H10"]) == (3, 3)


def test_h10_counts_two_extras_of_one_group():
    # Nhóm của lớp 1 học thêm lớp-môn 2 và 3, hai lớp-môn này trùng nhau (lớp 1 rảnh): 3 tiết
    p = _linked(extra_groups=((1, [2, 3]),))
    ev = evaluate(p, make_schedule(p, [0, 1, 2], [at(2, 1), at(1, 1), at(1, 1)]))
    assert ev.hard["H10"] == 3 and ev.hard["H1"] == 0


def test_class_overlap_with_unrelated_class_is_not_h10():
    # Lớp 2 không có ai học lại với lớp 1: trùng giờ lớp 1 / lớp 2 không sao
    p = _linked()
    ev = evaluate(p, make_schedule(p, [0, 1, 2], [at(1, 1), at(1, 1), at(2, 1)]))
    assert ev.hard_total == 0


def test_h10_violation_rows():
    p = _linked(extra_groups=((1, [3]),))
    s = make_schedule(p, [0, 1, 2], [at(1, 1), at(4, 1), at(1, 2)])
    rows = [r for r in violations(p, s, evaluate(p, s)) if r["code"] == "H10"]
    assert len(rows) == 1
    d = rows[0]["detail"]
    assert d["periods"] == 2 and d["group"] == {"class": "C1", "students": 1, "extra_section_ids": [3]}
    assert {x["class"] for x in d["sessions"]} == {"C1", "C3"}


def test_conflicted_events_and_repair_fix_h10():
    p = _linked()
    ws = Workspace(p, make_schedule(p, [0, 1, 2], [at(1, 1), at(1, 1), at(1, 2)]))
    assert ws.conflicted_events().tolist() == [0, 2]          # buổi lớp 1 và buổi học thêm
    assert repair(ws, np.random.default_rng(0)) == 0
    assert evaluate(p, ws.schedule()).hard["H10"] == 0


def test_position_cost_matches_true_h10_delta():
    """Phần H10 trong chi phí dời buổi của Workspace phải bằng đúng mức thay đổi H10 của evaluate()."""
    p = load_snapshot(SEEDS / "small.snapshot.json")
    rng = np.random.default_rng(0)
    sched = random_schedule(p, rng)
    ws = Workspace(p, sched)
    linked = [e for e in range(p.n_events)
              if len(p.class_groups[p.ev_class[e]]) or len(p.sec_extra_groups[p.ev_section[e]])]
    for e in rng.choice(linked, size=15, replace=False).tolist():
        L = int(p.ev_len[e])
        ws._apply(e, -1)
        gs, xs, c = p.class_groups[p.ev_class[e]], p.sec_extra_groups[p.ev_section[e]], int(p.ev_class[e])
        win = p.windows[L]
        part = np.zeros(len(win))
        if len(gs):
            part += ((ws.gx_cnt[gs][:, win] > 0) & (ws.class_cnt[c][win] == 0)[None]).sum((0, 2))
        if len(xs):
            part += ((ws.class_cnt[p.group_class[xs]] + ws.gx_cnt[xs])[:, win] > 0).sum((0, 2))
        ws._apply(e, +1)
        without = _h10_without(p, sched, e)
        for i in rng.choice(len(win), size=6, replace=False).tolist():
            s1 = sched.copy()
            s1.start[e] = int(p.starts_by_len[L][i])
            assert evaluate(p, s1).hard["H10"] - without == part[i], (e, i)


def _h10_without(p, sched, e):
    """H10 của lịch khi bỏ hẳn buổi e ra (tính lại từ đầu bằng công thức của evaluate)."""
    from solver.evaluate import h10
    nc = p.n_cells
    keep = np.ones(len(p.cell_event), bool)
    keep[p.cell_event == e] = False
    cell = sched.start[p.cell_event] + p.cell_offset
    cl = p.ev_class[p.cell_event]
    class_cnt = np.bincount(cl[keep] * nc + cell[keep], minlength=p.n_classes * nc).reshape(p.n_classes, nc)
    gkeep = p.gx_event != e
    gcell = sched.start[p.gx_event] + p.gx_offset
    gx = np.bincount(p.gx_group[gkeep] * nc + gcell[gkeep], minlength=p.n_groups * nc).reshape(p.n_groups, nc)
    return h10(class_cnt[p.group_class], gx)


def test_dsatur_avoids_student_overlap():
    p = _linked(extra_groups=((1, [2, 3]),), n_class1=2)
    for seed in range(5):
        assert evaluate(p, dsatur(p, np.random.default_rng(seed))).hard_total == 0


def test_makeup_avoids_extra_students():
    # Lớp-môn 1 (lớp 1) kín 15 tuần, nghỉ lễ 1 buổi -> phải học bù. Nhóm của lớp 1 học thêm lớp-môn 2 (lớp 2)
    # vào sáng Thứ 3: chỗ bù sớm nhất cùng tiết (sáng Thứ 3 tuần 1) bị chặn bởi H10.
    p = make_problem(rooms=[room(1), room(2)], lecturers=[lecturer(1, [1]), lecturer(2, [2])],
                     subjects=[subject(1, 2), subject(2, 2)], classes=[klass(1), klass(2)],
                     sections=[section(1, 1, 1, 2, periods_per_session=2), section(2, 2, 2, 2)],
                     student_groups=[group(1, [2])])
    s = make_schedule(p, [0, 1], [at(1, 1), at(2, 1)])
    r = expand_calendar(p, s, evaluate(p, s).room, [date(2026, 9, 7) + timedelta(weeks=4)])
    m = [x for x in r.sessions if x.is_makeup]
    assert len(m) == 1
    assert not (m[0].date == date(2026, 9, 8) and m[0].start_period <= 3)   # không trùng buổi học thêm
    assert r.h9 == 0


def _student_overlaps(p, sessions):
    """Đếm (nhóm, ngày, tiết) bị trùng trên lịch thật: kiểm tra độc lập với evaluate()."""
    by_sec = defaultdict(list)
    for x in sessions:
        by_sec[x.section].append(x)
    bad = 0
    for g in range(p.n_groups):
        secs = np.flatnonzero(p.sec_class == p.group_class[g]).tolist() + p.group_extra[g].tolist()
        used: dict = defaultdict(int)
        for s in secs:
            for x in by_sec[s]:
                m = _bit(x.start_period - 1, x.length)
                bad += bin(used[x.date] & m).count("1")
                used[x.date] |= m
    return bad


def test_ga_on_generated_data_has_no_student_overlap():
    p = load_snapshot(SEEDS / "small.snapshot.json")
    res = run_ga(p, GAParams(seed=0, pop_size=6, generations=4, ls_steps=30, init_ls_steps=100))
    assert res.best.evaluation.hard_total == 0
    cal = expand_calendar(p, res.best.schedule, res.best.evaluation.room)
    assert cal.h9 == 0 and _student_overlaps(p, cal.sessions) == 0
