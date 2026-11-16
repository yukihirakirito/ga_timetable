"""Tìm kiếm cục bộ cho GA (memetic): sửa xung đột cứng rồi cải thiện ràng buộc mềm.

`Workspace` giữ các mảng đếm của một lời giải và cập nhật **từng phần** khi dời một buổi
(đánh giá delta): dời buổi e chỉ chạm tới tối đa 5 ô của lớp, giảng viên, loại phòng, thay vì chấm lại cả lịch.

    class_cnt[c, ô]  số buổi của lớp c chiếm ô         (H1)
    lect_cnt[l, ô]   số buổi giảng viên l dạy ở ô        (H2)
    grp_cnt[g, ô]    số buổi chỉ dùng được phòng trong nhóm g ở ô (ước lượng H3 theo điều kiện Hall,
                     xem Problem.room_groups: vượt số phòng của nhóm là chắc chắn thiếu phòng)
    gx_cnt[g, ô]     số buổi học thêm của nhóm sinh viên g ở ô (H10; nhóm g = lớp group_class[g] + lớp-môn học thêm)
    sec_day[s, d]    số buổi của lớp-môn s trong ngày d   (H6, S2)
    class_day, lect_day  số buổi trong ngày              (S1, S4)
    load[l]          tiết/tuần của giảng viên l          (S6, S8)

Chi phí dùng ở đây là **ước lượng** để định hướng (phòng chỉ đếm theo loại, S1 dùng "bám mép" thay cho
tiết trống chính xác). Fitness thật luôn được tính lại bằng `evaluate()` trước khi GA so sánh cá thể.

Hai thao tác:
  * `best_move(e)`  : thử mọi vị trí bắt đầu hợp lệ của buổi e (vector hoá), dời tới vị trí rẻ nhất;
  * `best_lecturer(s)`: thử mọi giảng viên dạy được lớp-môn s, đổi sang người rẻ nhất.
`repair` là heuristic min-conflicts: lặp lại việc chọn ngẫu nhiên một buổi đang xung đột và dời nó.
"""

from __future__ import annotations

import numpy as np

from .evaluate import Weights, extra_counts
from .problem import Problem
from .schedule import Schedule


class Workspace:
    def __init__(self, problem: Problem, schedule: Schedule, weights: Weights | None = None):
        p = self.p = problem
        self.w = weights or Weights()
        self.lecturer = schedule.lecturer.copy()
        self.start = schedule.start.copy()
        nc = p.n_cells

        # Khởi tạo vector hoá (như evaluate) thay vì cộng từng buổi
        sec_group, self.group_size, self.superset = p.room_groups
        self.ev_group = sec_group[p.ev_section]
        self.supers = [np.flatnonzero(row) for row in self.superset]   # các nhóm chứa nhóm h
        n_groups = len(self.group_size)

        cell = self.start[p.cell_event] + p.cell_offset
        cl = p.ev_class[p.cell_event]
        le = self.lecturer[p.ev_section][p.cell_event]
        gr = self.ev_group[p.cell_event]
        day = self.start // p.n_periods
        self.class_cnt = np.bincount(cl * nc + cell, minlength=p.n_classes * nc).reshape(p.n_classes, nc)
        self.lect_cnt = np.bincount(le * nc + cell, minlength=p.n_lecturers * nc).reshape(p.n_lecturers, nc)
        base = np.bincount(gr * nc + cell, minlength=n_groups * nc).reshape(n_groups, nc)
        self.grp_cnt = self.superset.T.astype(np.int64) @ base     # grp_cnt[g] = Σ_{h ⊆ g} base[h]
        self.gx_cnt = extra_counts(p, self.start)
        nd = p.n_days
        self.sec_day = np.bincount(p.ev_section * nd + day, minlength=p.n_sections * nd).reshape(p.n_sections, nd)
        self.class_day = np.bincount(p.ev_class * nd + day, minlength=p.n_classes * nd).reshape(p.n_classes, nd)
        ev_lect = self.lecturer[p.ev_section]
        self.lect_day = np.bincount(ev_lect * nd + day, minlength=p.n_lecturers * nd).reshape(p.n_lecturers, nd)
        self.load = np.bincount(self.lecturer, weights=p.sec_weekly, minlength=p.n_lecturers)
        self.target_ratio = self.load.sum() / p.lect_max.sum()

    def schedule(self) -> Schedule:
        return Schedule(self.lecturer.copy(), self.start.copy())

    # --- cập nhật delta -------------------------------------------------------

    def _apply(self, e: int, sign: int) -> None:
        p = self.p
        st, L = int(self.start[e]), int(p.ev_len[e])
        s, c = int(p.ev_section[e]), int(p.ev_class[e])
        l, d = int(self.lecturer[s]), st // p.n_periods
        self.class_cnt[c, st: st + L] += sign
        self.lect_cnt[l, st: st + L] += sign
        self.grp_cnt[self.supers[self.ev_group[e]], st: st + L] += sign
        gs = p.sec_extra_groups[s]
        if len(gs):
            self.gx_cnt[gs, st: st + L] += sign
        self.sec_day[s, d] += sign
        self.class_day[c, d] += sign
        self.lect_day[l, d] += sign

    def move(self, e: int, new_start: int) -> None:
        self._apply(e, -1)
        self.start[e] = new_start
        self._apply(e, +1)

    def set_lecturer(self, s: int, l: int) -> None:
        events = self.p.sec_events[s]
        for e in events:
            self._apply(int(e), -1)
        self.load[self.lecturer[s]] -= self.p.sec_weekly[s]
        self.lecturer[s] = l
        self.load[l] += self.p.sec_weekly[s]
        for e in events:
            self._apply(int(e), +1)

    # --- xung đột hiện tại ------------------------------------------------------

    def conflicted_events(self) -> np.ndarray:
        """Các buổi đang dính ít nhất một xung đột cứng (H1, H2, H5, H6, H10 hoặc thiếu phòng theo điều kiện Hall)."""
        p = self.p
        cell = self.start[p.cell_event] + p.cell_offset
        ev_lect = self.lecturer[p.ev_section]
        cl, le, gr = p.ev_class[p.cell_event], ev_lect[p.cell_event], self.ev_group[p.cell_event]
        over = self.grp_cnt > self.group_size[:, None]                  # (nhóm phòng, ô) quá tải
        room_bad = (self.superset[gr] & over[:, cell].T).any(1)
        bad_cell = ((self.class_cnt[cl, cell] > 1) | (self.lect_cnt[le, cell] > 1)
                    | p.unavailable[le, cell] | room_bad)
        if p.n_groups:
            # H10 phía lớp: ô của lớp c trùng một buổi học thêm của nhóm thuộc lớp c
            class_extra = np.bincount(p.group_class_cell, weights=(self.gx_cnt > 0).ravel(),
                                      minlength=p.n_classes * p.n_cells).reshape(p.n_classes, p.n_cells) > 0
            bad_cell |= class_extra[cl, cell]
        # "buổi có ô xấu": bincount nhanh hơn nhiều so với np.logical_or.at (ufunc.at rất chậm)
        bad = np.bincount(p.cell_event, weights=bad_cell, minlength=p.n_events) > 0
        if p.n_groups:
            # H10 phía học thêm: buổi học thêm trùng lịch lớp của nhóm, hoặc trùng buổi học thêm khác của nhóm
            gcell = self.start[p.gx_event] + p.gx_offset
            gbad = ((self.class_cnt[p.group_class[p.gx_group], gcell] > 0)
                    | (self.gx_cnt[p.gx_group, gcell] > 1))
            bad |= np.bincount(p.gx_event, weights=gbad, minlength=p.n_events) > 0
        day = self.start // p.n_periods
        bad |= self.sec_day[p.ev_section, day] > 1
        return np.flatnonzero(bad)

    # --- chi phí theo vị trí (buổi e đã được gỡ khỏi các mảng đếm) ---------------

    def _position_costs(self, e: int) -> np.ndarray:
        p, w = self.p, self.w
        L, s, c = int(p.ev_len[e]), int(p.ev_section[e]), int(p.ev_class[e])
        l = int(self.lecturer[s])
        win, day = p.windows[L], p.window_day[L]
        left_edge, right_edge = p.window_edges[L]
        sup = self.supers[self.ev_group[e]]

        class_occ = self.class_cnt[c]
        room_full = (self.grp_cnt[sup][:, win] >= self.group_size[sup][:, None, None]).any(0)
        hard = ((class_occ[win] > 0).sum(1)
                + (self.lect_cnt[l][win] > 0).sum(1)
                + p.unavailable[l][win].sum(1)
                + room_full.sum(1)
                + 3 * (self.sec_day[s][day] > 0))
        # H10, đúng bằng mức tăng của công thức trong evaluate():
        #  - e là buổi của lớp c: tăng 1 ở ô mà lớp c đang trống và nhóm của lớp c có buổi học thêm
        #  - e là buổi học thêm của nhóm g: tăng 1 ở ô mà lớp của g hoặc buổi học thêm khác của g đang chiếm
        gs = p.class_groups[c]
        if len(gs):
            hard = hard + ((self.gx_cnt[gs][:, win] > 0) & (class_occ[win] == 0)[None]).sum((0, 2))
        gs = p.sec_extra_groups[s]
        if len(gs):
            occ = self.class_cnt[p.group_class[gs]] + self.gx_cnt[gs]
            hard = hard + (occ[:, win] > 0).sum((0, 2))

        sd = self.sec_day[s] > 0
        adjacent = (np.where(day > 0, sd[np.maximum(day - 1, 0)], False)
                    | np.where(day < p.n_days - 1, sd[np.minimum(day + 1, p.n_days - 1)], False))
        busy = class_occ > 0
        hugs = ((left_edge | busy[np.maximum(win[:, 0] - 1, 0)]).astype(float)
                + (right_edge | busy[np.minimum(win[:, -1] + 1, p.n_cells - 1)]))
        soft = (w.S2 * adjacent
                + w.S1 * ((self.class_day[c][day] == 0) + 0.5 * (2 - hugs))
                + w.S4 * (self.lect_day[l][day] == 0)
                - w.S5 * p.preferred[l][win].sum(1))
        return w.hard * hard + soft

    def best_move(self, e: int, rng: np.random.Generator, walk_prob: float = 0.0) -> float:
        """Dời buổi e tới vị trí rẻ nhất (hoà thì ngẫu nhiên). Trả về mức giảm chi phí ước lượng (>= 0).

        walk_prob: nếu không có vị trí nào rẻ hơn, với xác suất này vẫn **ép dời** sang vị trí rẻ nhất khác chỗ cũ
        (bước đi ngẫu nhiên kiểu WalkSAT) để thoát cực tiểu địa phương. Chỉ dùng khi sửa xung đột.
        """
        p = self.p
        L = int(p.ev_len[e])
        self._apply(e, -1)
        cost = self._position_costs(e)
        cur = p.start_index[L][int(self.start[e])]
        noisy = cost + rng.random(len(cost)) * 1e-6
        best = int(np.argmin(noisy))
        gain = float(cost[cur] - cost[best])
        if gain > 0:
            self.start[e] = int(p.starts_by_len[L][best])
        else:
            gain = 0.0
            if walk_prob and len(cost) > 1 and rng.random() < walk_prob:
                noisy[cur] = np.inf
                self.start[e] = int(p.starts_by_len[L][int(np.argmin(noisy))])
        self._apply(e, +1)
        return gain

    def best_lecturer(self, s: int, rng: np.random.Generator) -> float:
        """Đổi giảng viên của lớp-môn s sang người rẻ nhất. Trả về mức giảm chi phí ước lượng (>= 0)."""
        p, w = self.p, self.w
        cands = p.sec_candidates[s]
        if len(cands) < 2:
            return 0.0
        events = p.sec_events[s]
        cur = int(self.lecturer[s])
        weekly = p.sec_weekly[s]
        # Gỡ lớp-môn khỏi giảng viên hiện tại để mọi ứng viên được so trên cùng nền
        for e in events:
            self._apply(int(e), -1)
        self.load[cur] -= weekly
        costs = np.empty(len(cands))
        for i, l in enumerate(cands):
            l = int(l)
            hard = soft = 0.0
            for e in events:
                st, L = int(self.start[e]), int(p.ev_len[e])
                hard += (self.lect_cnt[l, st: st + L] > 0).sum() + p.unavailable[l, st: st + L].sum()
                soft += w.S4 * (self.lect_day[l, st // p.n_periods] == 0)
                soft -= w.S5 * p.preferred[l, st: st + L].sum()
            load = self.load[l] + weekly
            soft += w.S8 * max(0.0, load - p.lect_max[l])
            soft += w.S6 * (abs(load - p.lect_max[l] * self.target_ratio)
                            - abs(self.load[l] - p.lect_max[l] * self.target_ratio))
            costs[i] = w.hard * hard + soft
        best = int(np.argmin(costs + rng.random(len(costs)) * 1e-6))
        cur_i = int(np.flatnonzero(cands == cur)[0])
        gain = float(costs[cur_i] - costs[best])
        new = int(cands[best]) if gain > 0 else cur
        self.lecturer[s] = new
        self.load[new] += weekly
        for e in events:
            self._apply(int(e), +1)
        return max(gain, 0.0)


def repair(ws: Workspace, rng: np.random.Generator, max_steps: int = 200, lecturer_prob: float = 0.3,
           walk_prob: float = 0.5) -> int:
    """Min-conflicts: chọn ngẫu nhiên một buổi đang xung đột, dời nó (hoặc đổi giảng viên) tới chỗ rẻ nhất.
    Dừng khi hết xung đột hoặc hết bước. Trả về số buổi còn xung đột.

    walk_prob (xem Workspace.best_move): H10 nối nhiều lớp với nhau nên hay gặp thế kẹt mà không buổi nào dời một
    mình được. Đo trên `large`, 10 lịch ngẫu nhiên, 5000 bước: walk_prob 0 -> 0/10 lịch về 0 vi phạm cứng,
    0,2 -> 7/10, 0,3 -> 8/10, 0,5 -> 9/10 (và nhanh gấp đôi vì thoát sớm).
    """
    p = ws.p
    for _ in range(max_steps):
        conf = ws.conflicted_events()
        if len(conf) == 0:
            return 0
        e = int(rng.choice(conf))
        if rng.random() < lecturer_prob:
            ws.best_lecturer(int(p.ev_section[e]), rng)
        ws.best_move(e, rng, walk_prob)
    return len(ws.conflicted_events())


def improve(ws: Workspace, rng: np.random.Generator, steps: int = 50, lecturer_prob: float = 0.2) -> float:
    """Cải thiện mềm: thử dời các buổi ngẫu nhiên tới vị trí rẻ hơn. Trả về tổng mức giảm ước lượng."""
    p = ws.p
    gain = 0.0
    for e in rng.integers(0, p.n_events, size=steps):
        if rng.random() < lecturer_prob:
            gain += ws.best_lecturer(int(p.ev_section[e]), rng)
        gain += ws.best_move(int(e), rng)
    return gain
