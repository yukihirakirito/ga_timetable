"""Dựng snapshot nhỏ bằng tay cho test. Mặc định đủ phòng, đủ giảng viên để chỉ ràng buộc đang test bị vi phạm."""

from __future__ import annotations

import math

import numpy as np

from solver.problem import Problem
from solver.schedule import Schedule

CREDIT_RULES = {1: (3, 1), 2: (3, 1), 3: (3, 2), 4: (4, 2), 5: (5, 2)}

SEMESTER = {"id": 1, "name": "Test", "start_date": "2026-09-07", "end_date": "2027-01-09",
            "study_weeks": 15, "exam_weeks": 3, "holidays": []}
TIME_GRID = {"days_per_week": 6, "periods_per_day": 12, "shifts": [
    {"code": "MORNING", "first_period": 1, "last_period": 6},
    {"code": "AFTERNOON", "first_period": 7, "last_period": 12}]}


def at(day: int, period: int) -> int:
    """Ô bắt đầu: day 1 = Thứ 2, period 1..12."""
    return (day - 1) * 12 + (period - 1)


def room(id, room_type="THEORY", capacity=50):
    return {"id": id, "code": f"R{id}", "room_type": room_type, "capacity": capacity}


def lecturer(id, subject_ids, max_periods=20, unavailable=(), preferred=()):
    return {"id": id, "code": f"GV{id}", "max_periods_per_week": max_periods, "subject_ids": list(subject_ids),
            "unavailable": [dict(zip(("day", "period_from", "period_to"), r)) for r in unavailable],
            "preferred": [dict(zip(("day", "period_from", "period_to"), r)) for r in preferred]}


def subject(id, credits=2, room_type="THEORY"):
    return {"id": id, "code": f"SUB{id}", "credits": credits, "room_type": room_type}


def klass(id, size=30):
    return {"id": id, "code": f"C{id}", "term_no": 1, "size": size}


def section(id, class_id, subject_id, credits, periods_per_session=None, sessions_per_week=None):
    pps, spw = CREDIT_RULES[credits]
    pps = periods_per_session or pps
    spw = sessions_per_week or spw
    total = 15 * credits
    return {"id": id, "class_id": class_id, "subject_id": subject_id, "total_periods": total,
            "periods_per_session": pps, "sessions_per_week": spw, "total_sessions": math.ceil(total / pps)}


def group(class_id, extra_section_ids, students=1):
    return {"class_id": class_id, "extra_section_ids": list(extra_section_ids), "students": students}


def make_problem(*, rooms, lecturers, subjects, classes, sections, student_groups=()) -> Problem:
    """Sĩ số lớp-môn (`size`) tự tính = sĩ số lớp + số sinh viên học thêm, trừ khi section đã có sẵn."""
    class_size = {c["id"]: c["size"] for c in classes}
    extra = {}
    for g in student_groups:
        for sid in g["extra_section_ids"]:
            extra[sid] = extra.get(sid, 0) + g["students"]
    sections = [{**s, "size": s.get("size", class_size.get(s["class_id"], 1) + extra.get(s["id"], 0))}
                for s in sections]
    snap = {"schema_version": "2.0", "generated_at": "2026-11-13T00:00:00+07:00",
            "semester": SEMESTER, "time_grid": TIME_GRID, "rooms": rooms, "lecturers": lecturers,
            "subjects": subjects, "classes": classes, "sections": sections,
            "student_groups": list(student_groups)}
    return Problem(snap)


def make_schedule(problem: Problem, lecturers: list[int], starts: list[int]) -> Schedule:
    """lecturers: chỉ số giảng viên của từng lớp-môn; starts: ô bắt đầu của từng buổi (theo thứ tự event)."""
    return Schedule(np.array(lecturers, dtype=np.int64), np.array(starts, dtype=np.int64))
