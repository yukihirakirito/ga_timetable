"""Lời giải của giai đoạn 1 (tuần mẫu) = nhiễm sắc thể 2 phần.

    lecturer[s] : chỉ số giảng viên dạy lớp-môn s       (gen phần 1, miền: sec_candidates[s] -> H7)
    start[e]    : ô bắt đầu của buổi học e              (gen phần 2, miền: starts_by_len[len] -> H8)

Phòng không nằm trong nhiễm sắc thể: được gán khi chấm điểm (xem rooms.py).
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from .problem import Problem


@dataclass
class Schedule:
    lecturer: np.ndarray  # shape (n_sections,)
    start: np.ndarray     # shape (n_events,)

    def copy(self) -> "Schedule":
        return Schedule(self.lecturer.copy(), self.start.copy())


def random_schedule(problem: Problem, rng: np.random.Generator) -> Schedule:
    lecturer = np.array([rng.choice(c) for c in problem.sec_candidates], dtype=np.int64)
    start = np.empty(problem.n_events, dtype=np.int64)
    for length, starts in problem.starts_by_len.items():
        idx = np.flatnonzero(problem.ev_len == length)
        start[idx] = rng.choice(starts, size=len(idx))
    return Schedule(lecturer, start)


def domain_errors(problem: Problem, schedule: Schedule) -> list[str]:
    """Kiểm tra gen nằm trong miền giá trị (H7, H8). Lời giải do solver tạo ra luôn phải trả về []."""
    errors = []
    if schedule.lecturer.shape != (problem.n_sections,):
        errors.append(f"lecturer có shape {schedule.lecturer.shape}, cần ({problem.n_sections},)")
    if schedule.start.shape != (problem.n_events,):
        errors.append(f"start có shape {schedule.start.shape}, cần ({problem.n_events},)")
    if errors:
        return errors
    for s, lec in enumerate(schedule.lecturer):
        if lec not in problem.sec_candidates[s]:
            errors.append(f"H7: lớp-môn {problem.sec_ids[s]} gán giảng viên không dạy được môn")
    for e, st in enumerate(schedule.start):
        if st not in problem.ev_domain(e):
            errors.append(f"H8: buổi {e} bắt đầu ở ô {st} không hợp lệ cho buổi {problem.ev_len[e]} tiết")
    return errors
