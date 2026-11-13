from pathlib import Path

import numpy as np

from builders import klass, lecturer, make_problem, room, section, subject
from solver.dsatur import dsatur
from solver.evaluate import evaluate
from solver.problem import load_snapshot
from solver.schedule import domain_errors

SEEDS = Path(__file__).resolve().parents[2] / "db" / "seeds"


def test_tight_instance_packs_without_fragments():
    # 1 giảng viên, 1 phòng lab, 2 lớp x 3 môn 3 TC = 12 buổi x 3 tiết = 36 tiết.
    # Giảng viên bận Thứ 2-4 -> chỉ còn đúng 36 tiết (Thứ 5-7). Lịch hợp lệ phải kín từng tiết,
    # tức là mọi buổi phải bắt đầu ở tiết 1, 4, 7 hoặc 10 ("bám mép").
    p = make_problem(
        rooms=[room(1, "LAB", 40)],
        lecturers=[lecturer(1, [1, 2, 3], max_periods=40, unavailable=[(d, 1, 12) for d in (1, 2, 3)])],
        subjects=[subject(i, 3, "LAB") for i in (1, 2, 3)],
        classes=[klass(1), klass(2)],
        sections=[section(c * 3 + i, c + 1, i, 3) for c in range(2) for i in (1, 2, 3)],
    )
    hard = []
    for seed in range(5):
        s = dsatur(p, np.random.default_rng(seed))
        assert set((s.start % 12).tolist()) <= {0, 3, 6, 9}, "có buổi bắt đầu lệch, để lại khoảng thừa"
        hard.append(evaluate(p, s).hard_total)
    # Tham lam không quay lui: có thể kẹt ở buổi cuối (1 vi phạm H6), nhưng phải có seed tìm được lịch hợp lệ
    assert max(hard) <= 1 and min(hard) == 0, hard


def test_valid_and_complete_on_generated_data():
    p = load_snapshot(SEEDS / "medium.snapshot.json")
    s = dsatur(p, np.random.default_rng(0), room_aware=False)
    assert domain_errors(p, s) == []
    assert (s.lecturer >= 0).all() and (s.start >= 0).all()
    # Baseline phải tốt hơn hẳn ngẫu nhiên: lịch ngẫu nhiên của bộ này có hàng trăm vi phạm cứng
    assert evaluate(p, s).hard_total <= 10


def test_deterministic_for_same_seed():
    p = load_snapshot(SEEDS / "small.snapshot.json")
    a = dsatur(p, np.random.default_rng(7))
    b = dsatur(p, np.random.default_rng(7))
    assert (a.start == b.start).all() and (a.lecturer == b.lecturer).all()
