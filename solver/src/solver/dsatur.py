"""Baseline: xếp lịch tham lam theo DSatur (Brélaz, 1979).

DSatur gốc tô màu đồ thị: ở mỗi bước chọn đỉnh **bão hoà nhất** (còn ít màu hợp lệ nhất) để tô trước,
vì đỉnh đó dễ hết lựa chọn nhất nếu để sau. Ở đây:

    đỉnh   = một buổi học (event)
    màu    = (giảng viên, ô bắt đầu); khi lớp-môn đã có giảng viên thì chỉ còn chọn ô bắt đầu
    hợp lệ = không trùng lớp (H1), không trùng giảng viên (H2), không vào giờ bận (H5),
             không cùng ngày với buổi khác của lớp-môn (H6), không trùng lịch sinh viên học thêm (H10);
             vị trí bắt đầu đã đúng ca (H8)

Mỗi bước:
  1. chọn buổi chưa xếp có ít lựa chọn hợp lệ nhất (hoà thì ưu tiên buổi dài hơn);
  2. trong các lựa chọn hợp lệ còn phòng trống (H3), lấy lựa chọn có chi phí mềm ước lượng thấp nhất;
     nếu không còn lựa chọn hợp lệ, lấy lựa chọn ít vi phạm cứng nhất và đi tiếp;
  3. cập nhật lại số lựa chọn của các buổi bị ảnh hưởng (cùng lớp, hoặc có thể dùng chung giảng viên).

Phòng còn trống được tính vào số lựa chọn (room_aware, mặc định bật), để buổi của lớp đông, vốn chỉ vừa
vài phòng lớn, được xếp sớm. Lịch trả về là `Schedule`; phòng chính thức được gán lại khi chấm điểm (rooms.py).
"""

from __future__ import annotations

import numpy as np

from .problem import Problem
from .schedule import Schedule


class _State:
    def __init__(self, p: Problem):
        self.p = p
        self.class_busy = np.zeros((p.n_classes, p.n_cells), dtype=bool)
        self.extra_busy = np.zeros((p.n_groups, p.n_cells), dtype=bool)   # ô có buổi học thêm của nhóm (H10)
        self.lect_busy = np.zeros((p.n_lecturers, p.n_cells), dtype=bool)
        self.room_busy = np.zeros((p.n_rooms, p.n_cells), dtype=bool)
        self.sec_days = np.zeros((p.n_sections, p.n_days), dtype=bool)
        self.class_days = np.zeros((p.n_classes, p.n_days), dtype=bool)
        self.lect_days = np.zeros((p.n_lecturers, p.n_days), dtype=bool)
        self.lect_load = np.zeros(p.n_lecturers)              # tiết/tuần đã nhận (cả lớp-môn)
        self.sec_lect = np.full(p.n_sections, -1, dtype=np.int64)
        self.start = np.full(p.n_events, -1, dtype=np.int64)

        # Cửa sổ ô của từng vị trí bắt đầu: win[L][i] = các ô của buổi dài L bắt đầu ở starts_by_len[L][i]
        self.win = {L: s[:, None] + np.arange(L) for L, s in p.starts_by_len.items()}
        self.start_day = {L: s // p.n_periods for L, s in p.starts_by_len.items()}
        # Buổi có chạm mép trái / phải của ca không (dùng cho chi phí "bám mép")
        shift_first = np.array([p.shifts[i][0] for i in p.shift_of_period])
        shift_last = np.array([p.shifts[i][1] for i in p.shift_of_period])
        self.at_left = {L: (s % p.n_periods) == shift_first[s % p.n_periods] for L, s in p.starts_by_len.items()}
        self.at_right = {L: (s % p.n_periods + L - 1) == shift_last[s % p.n_periods] for L, s in p.starts_by_len.items()}
        # Phòng dùng được cho từng lớp-môn, tăng dần theo sức chứa (best-fit)
        self.sec_rooms = p.sec_usable_rooms
        # Lớp-môn nào có thể dùng giảng viên l / phòng r
        self.lect_sections: list[list[int]] = [[] for _ in range(p.n_lecturers)]
        for s, cands in enumerate(p.sec_candidates):
            for l in cands:
                self.lect_sections[int(l)].append(s)
        self.room_sections: list[list[int]] = [[] for _ in range(p.n_rooms)]
        for s, rooms in enumerate(self.sec_rooms):
            for r in rooms:
                self.room_sections[int(r)].append(s)

    def lecturers_of(self, s: int) -> np.ndarray:
        l = self.sec_lect[s]
        return np.array([l]) if l >= 0 else self.p.sec_candidates[s]

    def group_busy(self, e: int) -> np.ndarray:
        """Mặt nạ (ô) bận theo H10 của buổi e: buổi học thêm của các nhóm thuộc lớp e, và nếu e là buổi học
        thêm thì cả lịch lớp lẫn buổi học thêm khác của các nhóm đó."""
        p = self.p
        s, c = int(self.p.ev_section[e]), int(self.p.ev_class[e])
        busy = np.zeros(p.n_cells, dtype=bool)
        gs = p.class_groups[c]
        if len(gs):
            busy |= self.extra_busy[gs].any(0)
        gs = p.sec_extra_groups[s]
        if len(gs):
            busy |= self.class_busy[p.group_class[gs]].any(0) | self.extra_busy[gs].any(0)
        return busy

    def students_blocked(self, e: int) -> np.ndarray:
        """Mặt nạ trên starts_by_len[L]: vị trí trùng lịch lớp (H1) hoặc lịch sinh viên học thêm (H10).
        Không phụ thuộc giảng viên, nên tính một lần cho mọi giảng viên ứng viên."""
        p = self.p
        c = int(p.ev_class[e])
        busy = self.class_busy[c] | self.group_busy(e)
        return busy[self.win[int(p.ev_len[e])]].any(1)

    def feasible(self, e: int, l: int, students_blocked: np.ndarray | None = None) -> np.ndarray:
        """Mặt nạ trên starts_by_len[L]: vị trí không vi phạm H1, H2, H5, H6, H10 nếu giảng viên l dạy buổi e."""
        p = self.p
        L, s = int(p.ev_len[e]), int(p.ev_section[e])
        w = self.win[L]
        if students_blocked is None:
            students_blocked = self.students_blocked(e)
        blocked = students_blocked | self.lect_busy[l][w].any(1) | p.unavailable[l][w].any(1)
        return ~blocked & ~self.sec_days[s][self.start_day[L]]

    def n_options(self, e: int, room_aware: bool) -> int:
        room_ok = self.room_free(e) if room_aware else True
        sb = self.students_blocked(e)
        return int(sum((self.feasible(e, int(l), sb) & room_ok).sum()
                       for l in self.lecturers_of(int(self.p.ev_section[e]))))

    def room_free(self, e: int) -> np.ndarray:
        """Mặt nạ trên starts_by_len[L]: còn ít nhất một phòng phù hợp rảnh suốt buổi."""
        rooms = self.sec_rooms[int(self.p.ev_section[e])]
        w = self.win[int(self.p.ev_len[e])]
        return (~self.room_busy[rooms][:, w].any(2)).any(0)

    def _hugs(self, busy_row: np.ndarray, L: int) -> np.ndarray:
        """Số đầu (0-2) của buổi chạm mép ca hoặc chạm ô đã bận trong busy_row."""
        p, w = self.p, self.win[L]
        before = busy_row[np.maximum(w[:, 0] - 1, 0)]
        after = busy_row[np.minimum(w[:, -1] + 1, p.n_cells - 1)]
        return (self.at_left[L] | before).astype(float) + (self.at_right[L] | after)

    def soft_cost(self, e: int, l: int) -> np.ndarray:
        """Chi phí cho từng vị trí bắt đầu: ước lượng S1, S2, S4, S5, S6, S8 + "bám mép".

        Bám mép (least-constraining value): ưu tiên vị trí mà hai đầu buổi chạm mép ca hoặc chạm buổi
        đã xếp của lớp / giảng viên, để không để lại khoảng trống lẻ không vừa buổi nào. Ví dụ buổi 3 tiết
        đặt ở tiết 2-4 làm ca sáng chỉ còn chứa được 1 buổi 3 tiết thay vì 2.
        """
        p = self.p
        L, s, c = int(p.ev_len[e]), int(p.ev_section[e]), int(p.ev_class[e])
        day, w = self.start_day[L], self.win[L]
        days = self.sec_days[s]
        left = np.where(day > 0, days[np.maximum(day - 1, 0)], False)
        right = np.where(day < p.n_days - 1, days[np.minimum(day + 1, p.n_days - 1)], False)
        cost = 5.0 * (left | right)                                    # S2
        cost += ~self.class_days[c][day]                               # S1: thêm một ngày lên trường
        cost += 0.5 * (2 - self._hugs(self.class_busy[c], L))          # S1 + bám mép theo lớp
        cost += 0.5 * (2 - self._hugs(self.lect_busy[l] | p.unavailable[l], L))  # bám mép theo giảng viên
        cost += ~self.lect_days[l][day]                                # S4
        if p.preferred[l].any():
            cost += L - p.preferred[l][w].sum(1)                       # S5
        load = self.lect_load[l] + (p.sec_weekly[s] if self.sec_lect[s] < 0 else 0)
        cost += 5.0 * max(0.0, load - p.lect_max[l]) + 2.0 * load / p.lect_max[l]   # S8, S6
        return cost

    def hard_cost(self, e: int, l: int) -> np.ndarray:
        """Số vi phạm cứng nếu buộc phải xếp (dùng khi không còn lựa chọn hợp lệ)."""
        p = self.p
        L, s, c = int(p.ev_len[e]), int(p.ev_section[e]), int(p.ev_class[e])
        w = self.win[L]
        return (self.class_busy[c][w].sum(1) + self.lect_busy[l][w].sum(1) + p.unavailable[l][w].sum(1)
                + self.group_busy(e)[w].sum(1)
                + self.sec_days[s][self.start_day[L]] + ~self.room_free(e))

    def place(self, e: int, l: int, st: int) -> int:
        """Ghi nhận buổi e; trả về phòng đã giữ chỗ (-1 nếu hết phòng)."""
        p = self.p
        L, s, c = int(p.ev_len[e]), int(p.ev_section[e]), int(p.ev_class[e])
        cells = np.arange(st, st + L)
        day = st // p.n_periods
        if self.sec_lect[s] < 0:
            self.sec_lect[s] = l
            self.lect_load[l] += p.sec_weekly[s]
        self.start[e] = st
        self.class_busy[c, cells] = True
        gs = p.sec_extra_groups[s]
        if len(gs):
            self.extra_busy[np.ix_(gs, cells)] = True
        self.lect_busy[l, cells] = True
        self.sec_days[s, day] = True
        self.class_days[c, day] = True
        self.lect_days[l, day] = True
        for r in self.sec_rooms[s]:            # best-fit: phòng nhỏ nhất còn rảnh
            if not self.room_busy[r, cells].any():
                self.room_busy[r, cells] = True
                return int(r)
        return -1


def dsatur(problem: Problem, rng: np.random.Generator | None = None, room_aware: bool = True) -> Schedule:
    """room_aware: số lựa chọn tính cả phòng còn trống.

    Đo 5 seed x 3 bộ dữ liệu: bật -> tổng 14 vi phạm cứng, tắt -> 33; phạt mềm tương đương;
    nhưng chậm hơn ~8 lần (large: 7,8 s so với 0,8 s) vì mỗi lần giữ phòng phải đếm lại mọi buổi dùng được phòng đó.
    """
    p = problem
    rng = rng or np.random.default_rng(0)
    st = _State(p)
    noise = rng.random(p.n_events) * 1e-3                      # phá thế hoà ngẫu nhiên nhưng tái lập được
    sat = np.array([st.n_options(e, room_aware) for e in range(p.n_events)], dtype=float)
    placed = np.zeros(p.n_events, dtype=bool)

    for _ in range(p.n_events):
        key = np.where(placed, np.inf, sat - 0.01 * p.ev_len + noise)
        e = int(np.argmin(key))
        s = int(p.ev_section[e])
        starts = p.starts_by_len[int(p.ev_len[e])]

        best = None  # (chi phí, giảng viên, ô bắt đầu)
        room_ok = st.room_free(e)
        sb = st.students_blocked(e)
        for l in st.lecturers_of(s):
            l = int(l)
            ok = st.feasible(e, l, sb) & room_ok
            if ok.any():
                cost = np.where(ok, st.soft_cost(e, l), np.inf) + rng.random(len(starts)) * 1e-6
                i = int(np.argmin(cost))
                if best is None or cost[i] < best[0]:
                    best = (cost[i], l, int(starts[i]))
        if best is None:   # hết lựa chọn hợp lệ: chấp nhận vi phạm ít nhất, chi phí mềm để phân định
            for l in st.lecturers_of(s):
                l = int(l)
                cost = st.hard_cost(e, l) * 1e6 + st.soft_cost(e, l) + rng.random(len(starts)) * 1e-6
                i = int(np.argmin(cost))
                if best is None or cost[i] < best[0]:
                    best = (cost[i], l, int(starts[i]))

        _, l, start = best
        r = st.place(e, l, start)
        placed[e] = True

        # Cập nhật số lựa chọn của các buổi bị ảnh hưởng: cùng lớp, nối qua nhóm sinh viên (H10),
        # có thể dùng giảng viên l, có thể dùng phòng r
        affected = set(np.flatnonzero(p.ev_class == p.ev_class[e]).tolist())
        for s2 in p.sec_linked[s].tolist():
            affected.update(p.sec_events[s2].tolist())
        for s2 in st.lect_sections[l]:
            if st.sec_lect[s2] in (-1, l):
                affected.update(p.sec_events[s2].tolist())
        if room_aware and r >= 0:
            for s2 in st.room_sections[r]:
                affected.update(p.sec_events[s2].tolist())
        for e2 in affected:
            if not placed[e2]:
                sat[e2] = st.n_options(e2, room_aware)

    return Schedule(st.sec_lect.copy(), st.start.copy())
