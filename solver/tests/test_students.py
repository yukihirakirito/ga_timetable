"""Snapshot 2.0: sĩ số lớp-môn và nhóm sinh viên học thêm (M8a: nạp + kiểm tra hợp đồng; H10 ở M8b)."""

from pathlib import Path

import pytest

from builders import group, klass, lecturer, make_problem, room, section, subject
from solver.problem import SnapshotError, load_snapshot

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
