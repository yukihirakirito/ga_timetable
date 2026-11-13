import numpy as np

from builders import at, klass, lecturer, make_problem, room, section, subject
from solver.rooms import NO_ROOM, assign_rooms


def _problem(rooms, sizes, credits=2, room_type="THEORY", pps=None):
    """Mỗi lớp học đúng một môn (một lớp-môn), các lớp-môn đều cùng môn."""
    return make_problem(
        rooms=rooms,
        lecturers=[lecturer(1, [1])],
        subjects=[subject(1, credits=credits, room_type=room_type)],
        classes=[klass(i + 1, size) for i, size in enumerate(sizes)],
        sections=[section(i + 1, i + 1, 1, credits, periods_per_session=pps) for i in range(len(sizes))],
    )


def test_uses_exactly_max_overlap_rooms():
    # Tiết 1-3, 2-4, 4-6: chồng nhau nhiều nhất 2 buổi cùng lúc -> 2 phòng là đủ
    p = _problem([room(1), room(2)], [30, 30, 30])
    r = assign_rooms(p, np.array([at(1, 1), at(1, 2), at(1, 4)]))
    assert (r != NO_ROOM).all()
    assert r[2] == r[0]          # buổi 4-6 dùng lại phòng của buổi 1-3 vừa kết thúc


def test_reports_no_room_when_overlap_exceeds_rooms():
    p = _problem([room(1)], [30, 30])
    r = assign_rooms(p, np.array([at(1, 1), at(1, 2)]))
    assert sorted(r.tolist()) == [NO_ROOM, 0]


def test_best_fit_keeps_big_room_for_big_class():
    # Phòng 60 và 40; lớp 35 phải lấy phòng 40 để lớp 55 cùng giờ còn phòng 60
    p = _problem([room(1, capacity=60), room(2, capacity=40)], [35, 55])
    r = assign_rooms(p, np.array([at(1, 1), at(1, 1)]))
    assert r.tolist() == [1, 0]


def test_augmenting_path_frees_a_room():
    # Phòng A(40), B(60). z (50 SV, tiết 4-6) chỉ vừa B nên được xếp trước -> B.
    # x (30 SV, tiết 1-3) -> A. y (30 SV, tiết 2-6) kẹt: A bận tiết 2-3 (x), B bận tiết 4-6 (z).
    # Đường tăng: y chiếm A, đẩy x sang B (B rảnh tiết 1-3).
    p = make_problem(
        rooms=[room(1, capacity=40), room(2, capacity=60)],
        lecturers=[lecturer(1, [1, 2])],
        subjects=[subject(1, 2), subject(2, 5)],
        classes=[klass(1, 30), klass(2, 30), klass(3, 50)],
        sections=[section(1, 1, 1, 2), section(2, 2, 2, 5), section(3, 3, 1, 2)],
    )
    # event: [x, y-buổi1, y-buổi2, z]
    r = assign_rooms(p, np.array([at(1, 1), at(1, 2), at(3, 2), at(1, 4)]))
    assert (r != NO_ROOM).all(), r
    assert r.tolist() == [1, 0, 0, 1]


def test_room_type_is_respected():
    p = _problem([room(1, "THEORY"), room(2, "LAB")], [30, 30], room_type="LAB")
    r = assign_rooms(p, np.array([at(1, 1), at(1, 1)]))
    assert sorted(r.tolist()) == [NO_ROOM, 1]


def test_section_keeps_its_room_on_later_days():
    # Thứ 2: lớp 1 lấy R1, lớp 2 lấy R2. Thứ 3 chỉ có lớp 2 học: best-fit thuần sẽ chọn R1,
    # nhưng ưu tiên S7 giữ lớp 2 ở R2.
    p = make_problem(
        rooms=[room(1, capacity=40), room(2, capacity=45)],
        lecturers=[lecturer(1, [1])],
        subjects=[subject(1, credits=3)],
        classes=[klass(1, 30), klass(2, 30)],
        sections=[section(1, 1, 1, 3), section(2, 2, 1, 3)],
    )
    # event: [s1-buổi1, s1-buổi2, s2-buổi1, s2-buổi2]
    r = assign_rooms(p, np.array([at(1, 1), at(4, 1), at(1, 1), at(2, 1)]))
    assert r[0] == 0 and r[2] == 1
    assert r[3] == 1
