"""Chấm điểm một lời giải tuần mẫu.

    fitness = hard_weight * Σ vi phạm cứng + Σ wᵢ * vi phạm mềmᵢ        (càng nhỏ càng tốt)

Ràng buộc cứng
    H1  lớp học 2 buổi chồng tiết            số tiết bị trùng (một ô có k buổi -> k-1)
    H2  giảng viên dạy 2 buổi chồng tiết     như H1
    H3  không còn phòng phù hợp             số buổi không gán được phòng
    H4  phòng sai loại / thiếu chỗ           luôn 0 vì gán phòng đã lọc; giữ để kiểm tra chéo
    H5  dạy vào khung giờ bận                số tiết
    H6  hai buổi của một lớp-môn cùng ngày   số buổi thừa trong cùng ngày
    H7, H8 không thể vi phạm: gen chỉ lấy giá trị trong miền (schedule.domain_errors)
    H9  kiểm tra ở giai đoạn 2 (lịch thật)
    H10 sinh viên học 2 buổi chồng tiết      theo nhóm sinh viên học thêm g (lớp c + lớp-môn học thêm), mỗi ô:
                                             (k_lớp + k_thêm - 1)⁺ - (k_lớp - 1)⁺, tức chỉ phần trùng có dính
                                             lớp-môn học thêm (phần trùng trong lớp đã tính ở H1).
                                             Không nhân số sinh viên của nhóm.

Ràng buộc mềm
    S1  lịch lớp không gọn                   tiết trống kẹp giữa các buổi trong ca + số ngày phải lên trường
    S2  buổi của một môn ở hai ngày liền nhau số cặp ngày liền kề
    (S3 đã bỏ; giữ nguyên số của các mã còn lại)
    S4  số ngày giảng viên lên trường        tổng số (giảng viên, ngày) có dạy
    S5  khung ưu tiên của giảng viên bị bỏ    số tiết ưu tiên không được xếp dạy
    S6  lệch tải giữa các giảng viên          Σ |tải - tải mục tiêu|, mục tiêu tỉ lệ với tải tối đa
    S7  lớp-môn đổi phòng                    Σ (số phòng khác nhau - 1)
    S8  vượt số tiết tối đa/tuần             Σ số tiết vượt
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field

import numpy as np

from .problem import Problem
from .rooms import NO_ROOM, assign_rooms
from .schedule import Schedule

HARD_CODES = ("H1", "H2", "H3", "H4", "H5", "H6", "H10")
SOFT_CODES = ("S1", "S2", "S4", "S5", "S6", "S7", "S8")


@dataclass
class Weights:
    hard: float = 10000.0
    S1: float = 1.0
    S2: float = 5.0
    S4: float = 1.0
    S5: float = 1.0
    S6: float = 0.5
    S7: float = 1.0
    S8: float = 5.0

    def soft(self, code: str) -> float:
        return getattr(self, code)

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class Evaluation:
    fitness: float
    soft_penalty: float                   # phần mềm của fitness (đã nhân trọng số)
    hard: dict[str, int]
    soft: dict[str, float]
    room: np.ndarray = field(repr=False)  # phòng của từng buổi (NO_ROOM nếu không có)
    load: np.ndarray = field(repr=False)  # tiết/tuần của từng giảng viên

    @property
    def hard_total(self) -> int:
        return sum(self.hard.values())


def _over(counts: np.ndarray) -> int:
    """Σ max(0, c - 1): số lần vượt quá 1 trong mảng đếm."""
    return int(np.clip(counts - 1, 0, None).sum())


def extra_counts(problem: Problem, start: np.ndarray) -> np.ndarray:
    """extra_cnt[g, ô] = số buổi học thêm của nhóm g chiếm ô."""
    p, nc = problem, problem.n_cells
    cell = start[p.gx_event] + p.gx_offset
    return np.bincount(p.gx_group * nc + cell, minlength=p.n_groups * nc).reshape(p.n_groups, nc)


def h10(class_cnt_of_group: np.ndarray, extra_cnt: np.ndarray) -> int:
    """Σ (k_lớp + k_thêm - 1)⁺ - (k_lớp - 1)⁺ trên mọi (nhóm, ô)."""
    total = np.clip(class_cnt_of_group + extra_cnt - 1, 0, None) - np.clip(class_cnt_of_group - 1, 0, None)
    return int(total.sum())


def evaluate(problem: Problem, schedule: Schedule, weights: Weights | None = None) -> Evaluation:
    w = weights or Weights()
    p = problem
    nc, npd, nd = p.n_cells, p.n_periods, p.n_days
    start, lecturer = schedule.start, schedule.lecturer

    # --- Mở rộng mỗi buổi thành các ô nó chiếm ------------------------------------
    cell = start[p.cell_event] + p.cell_offset                 # ô tuyệt đối 0..n_cells-1
    cell_class = p.ev_class[p.cell_event]
    ev_lect = lecturer[p.ev_section]
    cell_lect = ev_lect[p.cell_event]

    class_cnt = np.bincount(cell_class * nc + cell, minlength=p.n_classes * nc).reshape(p.n_classes, nc)
    lect_cnt = np.bincount(cell_lect * nc + cell, minlength=p.n_lecturers * nc).reshape(p.n_lecturers, nc)
    ev_day = start // npd
    sec_day = np.bincount(p.ev_section * nd + ev_day, minlength=p.n_sections * nd).reshape(p.n_sections, nd)

    room = assign_rooms(p, start)
    has_room = room != NO_ROOM

    hard = {
        "H1": _over(class_cnt),
        "H2": _over(lect_cnt),
        "H3": int((~has_room).sum()),
        "H4": int(((p.room_type[room[has_room]] != p.ev_room_type[has_room])
                   | (p.room_cap[room[has_room]] < p.ev_size[has_room])).sum()),
        "H5": int(p.unavailable[cell_lect, cell].sum()),
        "H6": _over(sec_day),
        "H10": h10(class_cnt[p.group_class], extra_counts(p, start)),
    }

    # --- Mềm ------------------------------------------------------------------------
    class_occ = (class_cnt > 0).reshape(p.n_classes, nd, npd)
    gaps = 0
    for first, last in p.shifts:
        occ = class_occ[:, :, first: last + 1]
        n = occ.sum(axis=2)
        width = last - first + 1
        lo = occ.argmax(axis=2)
        hi = width - 1 - occ[:, :, ::-1].argmax(axis=2)
        gaps += int(np.where(n > 0, hi - lo + 1 - n, 0).sum())
    class_days = int(class_occ.any(axis=2).sum())

    sec_on_day = sec_day > 0
    lect_occ = lect_cnt > 0
    load = np.bincount(lecturer, weights=p.sec_weekly, minlength=p.n_lecturers)
    target = p.lect_max * (load.sum() / p.lect_max.sum())

    room_pairs = np.unique(p.ev_section[has_room] * max(p.n_rooms, 1) + room[has_room])
    sections_with_room = np.unique(p.ev_section[has_room])

    soft = {
        "S1": float(gaps + class_days),
        "S2": float((sec_on_day[:, :-1] & sec_on_day[:, 1:]).sum()),
        "S4": float(lect_occ.reshape(p.n_lecturers, nd, npd).any(axis=2).sum()),
        "S5": float(p.preferred.sum() - (p.preferred & lect_occ).sum()),
        "S6": float(np.abs(load - target).sum()),
        "S7": float(len(room_pairs) - len(sections_with_room)),
        "S8": float(np.clip(load - p.lect_max, 0, None).sum()),
    }

    soft_penalty = sum(w.soft(c) * v for c, v in soft.items())
    return Evaluation(w.hard * sum(hard.values()) + soft_penalty, soft_penalty, hard, soft, room, load)


def violations(problem: Problem, schedule: Schedule, evaluation: Evaluation) -> list[dict]:
    """Liệt kê vi phạm chi tiết, mỗi phần tử khớp một dòng run_violations: {code, severity, detail}.

    Vi phạm cứng: một dòng cho mỗi chỗ vi phạm. Vi phạm mềm: một dòng tổng cho mỗi mã,
    riêng S8 thêm một dòng cho mỗi giảng viên vượt tải. Không dùng trong vòng lặp GA (chậm hơn evaluate).
    """
    p, out = problem, []
    start, lecturer, room = schedule.start, schedule.lecturer, evaluation.room
    day = start // p.n_periods

    def ev_info(e: int) -> dict:
        s = int(p.ev_section[e])
        return {"section_id": int(p.sec_ids[s]), "subject": p.sec_subject_code[s],
                "class": p.class_codes[p.sec_class[s]], "lecturer": p.lect_codes[lecturer[s]],
                "day": int(day[e]) + 1, "period_from": int(start[e] % p.n_periods) + 1,
                "period_to": int(start[e] % p.n_periods + p.ev_len[e])}

    def hard(code: str, **detail):
        out.append({"code": code, "severity": "HARD", "detail": detail})

    # H1 / H2: gom các buổi cùng chủ thể theo ngày, tìm cặp chồng nhau
    for code, owner_of, names in (("H1", p.ev_class, p.class_codes),
                                  ("H2", lecturer[p.ev_section], p.lect_codes)):
        by_key: dict[tuple[int, int], list[int]] = {}
        for e in range(p.n_events):
            by_key.setdefault((int(owner_of[e]), int(day[e])), []).append(e)
        for (owner, _), evs in by_key.items():
            evs.sort(key=lambda e: start[e])
            for i, a in enumerate(evs):
                for b in evs[i + 1:]:
                    if start[b] >= start[a] + p.ev_len[a]:
                        break
                    overlap = int(min(start[a] + p.ev_len[a], start[b] + p.ev_len[b]) - start[b])
                    hard(code, owner=names[owner], periods=overlap, sessions=[ev_info(a), ev_info(b)])

    for e in np.flatnonzero(room == NO_ROOM):
        hard("H3", room_type=p.room_types[p.ev_room_type[e]], size=int(p.ev_size[e]), session=ev_info(int(e)))

    for e in range(p.n_events):
        lec = lecturer[p.ev_section[e]]
        n = int(p.unavailable[lec, start[e]: start[e] + p.ev_len[e]].sum())
        if n:
            hard("H5", periods=n, session=ev_info(e))

    for s in range(p.n_sections):
        evs = p.sec_events[s]
        days = day[evs]
        if len(set(days.tolist())) < len(days):
            hard("H6", sessions=[ev_info(int(e)) for e in evs])

    # H10: mỗi cặp buổi chồng tiết của một nhóm sinh viên, trong đó ít nhất một buổi là học thêm
    for g in range(p.n_groups):
        extra = [int(e) for s in p.group_extra[g].tolist() for e in p.sec_events[s]]
        own = np.flatnonzero(p.ev_class == p.group_class[g]).tolist()
        pairs = [(a, b) for i, a in enumerate(extra) for b in own + extra[i + 1:]]
        for a, b in pairs:
            if day[a] != day[b]:
                continue
            overlap = int(min(start[a] + p.ev_len[a], start[b] + p.ev_len[b]) - max(start[a], start[b]))
            if overlap > 0:
                hard("H10", group={"class": p.class_codes[p.group_class[g]], "students": int(p.group_students[g]),
                                   "extra_section_ids": [int(p.sec_ids[x]) for x in p.group_extra[g]]},
                     periods=overlap, sessions=[ev_info(a), ev_info(b)])

    for code in SOFT_CODES:
        if evaluation.soft[code]:
            out.append({"code": code, "severity": "SOFT", "detail": {"value": evaluation.soft[code]}})
    for l in np.flatnonzero(evaluation.load > p.lect_max):
        out.append({"code": "S8", "severity": "SOFT",
                    "detail": {"lecturer": p.lect_codes[l], "load": int(evaluation.load[l]),
                               "max": int(p.lect_max[l])}})
    return out
