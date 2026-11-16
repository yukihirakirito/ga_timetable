"""Mô hình bài toán: chuyển input_snapshot thành các mảng chỉ số để tính toán nhanh.

Quy ước thời gian trong tuần mẫu: một **ô** (cell) = một tiết của một ngày,
đánh số 0-based `cell = day * periods_per_day + period`, với day 0 = Thứ 2, period 0 = tiết 1.
Một buổi học dài L tiết bắt đầu ở ô `start` chiếm các ô `start .. start + L - 1`
(luôn cùng ngày, cùng ca nhờ miền giá trị đã lọc theo H8).

Mọi thực thể được đánh lại chỉ số 0..n-1 theo thứ tự trong snapshot; `*_ids` giữ id gốc trong DB.
"""

from __future__ import annotations

import importlib.util
import json
from functools import cached_property
from pathlib import Path

import numpy as np

REPO_ROOT = Path(__file__).resolve().parents[3]
VALIDATOR_PATH = REPO_ROOT / "contracts" / "validate.py"
SUPPORTED_SCHEMA_VERSIONS = {"2.0"}


class SnapshotError(ValueError):
    """Snapshot không hợp lệ; `errors` là danh sách lỗi chi tiết."""

    def __init__(self, errors: list[str]):
        super().__init__(f"{len(errors)} lỗi trong snapshot:\n  " + "\n  ".join(errors))
        self.errors = errors


def _validator():
    spec = importlib.util.spec_from_file_location("contracts_validate", VALIDATOR_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def load_snapshot(path: str | Path, validate: bool = True) -> "Problem":
    snapshot = json.loads(Path(path).read_text(encoding="utf-8"))
    return Problem(snapshot, validate=validate)


class Problem:
    def __init__(self, snapshot: dict, validate: bool = True):
        version = snapshot.get("schema_version")
        if version not in SUPPORTED_SCHEMA_VERSIONS:
            raise SnapshotError([f"schema_version {version!r} không được hỗ trợ"])
        if validate:
            errors = _validator().validate(snapshot)
            if errors:
                raise SnapshotError(errors)
        self.snapshot = snapshot

        # --- Lưới thời gian -------------------------------------------------
        grid = snapshot["time_grid"]
        self.n_days: int = grid["days_per_week"]
        self.n_periods: int = grid["periods_per_day"]
        self.n_cells: int = self.n_days * self.n_periods
        # Ca: (tiết đầu, tiết cuối) 0-based, gồm cả hai đầu
        self.shifts: list[tuple[int, int]] = sorted(
            (s["first_period"] - 1, s["last_period"] - 1) for s in grid["shifts"]
        )
        self.shift_codes: list[str] = [s["code"] for s in sorted(grid["shifts"], key=lambda s: s["first_period"])]

        # --- Phòng ------------------------------------------------------------
        rooms = snapshot["rooms"]
        self.room_types: list[str] = sorted({r["room_type"] for r in rooms} |
                                            {s["room_type"] for s in snapshot["subjects"]})
        rtype = {code: i for i, code in enumerate(self.room_types)}
        self.room_ids = np.array([r["id"] for r in rooms])
        self.room_codes = [r["code"] for r in rooms]
        self.room_type = np.array([rtype[r["room_type"]] for r in rooms])
        self.room_cap = np.array([r["capacity"] for r in rooms])

        # --- Giảng viên -------------------------------------------------------
        lecturers = snapshot["lecturers"]
        self.lect_ids = np.array([l["id"] for l in lecturers])
        self.lect_codes = [l["code"] for l in lecturers]
        self.lect_max = np.array([l["max_periods_per_week"] for l in lecturers])
        self.unavailable = np.zeros((len(lecturers), self.n_cells), dtype=bool)  # H5
        self.preferred = np.zeros((len(lecturers), self.n_cells), dtype=bool)    # S5
        for i, lec in enumerate(lecturers):
            for kind, mask in (("unavailable", self.unavailable), ("preferred", self.preferred)):
                for r in lec[kind]:
                    base = (r["day"] - 1) * self.n_periods
                    mask[i, base + r["period_from"] - 1: base + r["period_to"]] = True

        # --- Lớp sinh viên ----------------------------------------------------
        classes = snapshot["classes"]
        self.class_ids = np.array([c["id"] for c in classes])
        self.class_codes = [c["code"] for c in classes]
        self.class_size = np.array([c["size"] for c in classes])
        class_idx = {c["id"]: i for i, c in enumerate(classes)}

        # --- Môn học ----------------------------------------------------------
        subjects = {s["id"]: s for s in snapshot["subjects"]}

        # --- Lớp-môn (section) ------------------------------------------------
        sections = snapshot["sections"]
        self.sec_ids = np.array([s["id"] for s in sections])
        self.sec_class = np.array([class_idx[s["class_id"]] for s in sections])
        self.sec_subject_code = [subjects[s["subject_id"]]["code"] for s in sections]
        self.sec_len = np.array([s["periods_per_session"] for s in sections])
        self.sec_spw = np.array([s["sessions_per_week"] for s in sections])
        self.sec_total_periods = np.array([s["total_periods"] for s in sections])
        self.sec_total_sessions = np.array([s["total_sessions"] for s in sections])
        self.sec_room_type = np.array([rtype[subjects[s["subject_id"]]["room_type"]] for s in sections])
        self.sec_size = np.array([s["size"] for s in sections])  # sĩ số lớp-môn, tính cả sinh viên học thêm
        self.sec_weekly = self.sec_len * self.sec_spw  # tiết/tuần trong tuần mẫu

        # --- Nhóm sinh viên học thêm (H10) --------------------------------------
        # Nhóm g: group_students[g] sinh viên của lớp group_class[g], học mọi lớp-môn của lớp đó
        # cộng các lớp-môn group_extra[g] (chỉ số lớp-môn, thuộc lớp khác).
        sec_idx = {s["id"]: i for i, s in enumerate(sections)}
        groups = snapshot["student_groups"]
        self.group_class = np.array([class_idx[g["class_id"]] for g in groups], dtype=np.int64)
        self.group_students = np.array([g["students"] for g in groups], dtype=np.int64)
        self.group_extra: list[np.ndarray] = [
            np.array([sec_idx[x] for x in g["extra_section_ids"]], dtype=np.int64) for g in groups]

        # Giảng viên dạy được (H7): miền giá trị của gen giảng viên
        teaches: dict[int, list[int]] = {}
        for i, lec in enumerate(lecturers):
            for sid in lec["subject_ids"]:
                teaches.setdefault(sid, []).append(i)
        self.sec_candidates: list[np.ndarray] = [
            np.array(teaches.get(s["subject_id"], []), dtype=np.int64) for s in sections
        ]

        # --- Buổi học (event) trong tuần mẫu --------------------------------------
        # Lớp-môn có sessions_per_week buổi; event e thuộc lớp-môn ev_section[e], là buổi thứ ev_k[e]
        self.ev_section = np.repeat(np.arange(len(sections)), self.sec_spw)
        self.ev_k = np.concatenate([np.arange(n) for n in self.sec_spw]) if len(sections) else np.array([], int)
        self.ev_len = self.sec_len[self.ev_section]
        self.ev_class = self.sec_class[self.ev_section]
        self.ev_room_type = self.sec_room_type[self.ev_section]
        self.ev_size = self.sec_size[self.ev_section]
        # Các event của từng lớp-môn: sec_events[s] = [e0, e1, ...]
        offsets = np.concatenate([[0], np.cumsum(self.sec_spw)])
        self.sec_events: list[np.ndarray] = [np.arange(offsets[s], offsets[s + 1]) for s in range(len(sections))]

        # Vị trí bắt đầu hợp lệ theo độ dài buổi (H8): buổi nằm trọn trong một ca
        self.starts_by_len: dict[int, np.ndarray] = {}
        for length in sorted(set(self.sec_len.tolist())):
            starts = [day * self.n_periods + p
                      for day in range(self.n_days)
                      for first, last in self.shifts
                      for p in range(first, last - length + 2)]
            self.starts_by_len[length] = np.array(starts, dtype=np.int64)

        # Mở rộng event thành các ô nó chiếm: ô thứ j thuộc event cell_event[j],
        # nằm ở start[cell_event[j]] + cell_offset[j]. Tính sẵn một lần, dùng cho mọi lần chấm điểm.
        self.cell_event = np.repeat(np.arange(self.n_events), self.ev_len)
        self.cell_offset = (np.concatenate([np.arange(n) for n in self.ev_len])
                            if self.n_events else np.array([], int))

        # --- Quan hệ nhóm sinh viên <-> lớp / lớp-môn (H10) ---------------------------
        # class_groups[c]       : các nhóm thuộc lớp c (buổi của lớp c không được trùng buổi học thêm của nhóm)
        # sec_extra_groups[s]   : các nhóm học thêm lớp-môn s
        # sec_linked[s]         : lớp-môn của lớp khác mà vị trí của s ảnh hưởng tới qua H10
        self.class_groups: list[np.ndarray] = [np.flatnonzero(self.group_class == c) for c in range(self.n_classes)]
        # Chỉ số phẳng (lớp của nhóm g, ô) cho mọi (g, ô): gộp mảng (nhóm, ô) theo lớp bằng một lần bincount
        self.group_class_cell = (self.group_class[:, None] * self.n_cells + np.arange(self.n_cells)).ravel()
        sec_groups: list[list[int]] = [[] for _ in range(self.n_sections)]
        for g, extra in enumerate(self.group_extra):
            for s in extra.tolist():
                sec_groups[s].append(g)
        self.sec_extra_groups: list[np.ndarray] = [np.array(x, dtype=np.int64) for x in sec_groups]
        class_secs = [np.flatnonzero(self.sec_class == c) for c in range(self.n_classes)]
        linked: list[set[int]] = [set() for _ in range(self.n_sections)]
        for g, extra in enumerate(self.group_extra):
            members = set(class_secs[self.group_class[g]].tolist()) | set(extra.tolist())
            for s in extra.tolist():
                linked[s] |= members
            for s in class_secs[self.group_class[g]].tolist():
                linked[s] |= set(extra.tolist())
        self.sec_linked: list[np.ndarray] = [
            np.array(sorted(x - {s}), dtype=np.int64) for s, x in enumerate(linked)]
        # Các ô của buổi học thêm theo từng nhóm: (gx_group[j], gx_event[j], gx_offset[j]) như cell_event
        pair_g = [g for g, extra in enumerate(self.group_extra) for s in extra.tolist() for _ in self.sec_events[s]]
        pair_e = [int(e) for extra in self.group_extra for s in extra.tolist() for e in self.sec_events[s]]
        pair_g = np.array(pair_g, dtype=np.int64)
        pair_e = np.array(pair_e, dtype=np.int64)
        lens = self.ev_len[pair_e] if len(pair_e) else np.array([], dtype=np.int64)
        self.gx_group = np.repeat(pair_g, lens)
        self.gx_event = np.repeat(pair_e, lens)
        self.gx_offset = (np.concatenate([np.arange(n) for n in lens]) if len(lens) else np.array([], dtype=np.int64))

    # --- Kích thước -----------------------------------------------------------

    @property
    def n_rooms(self) -> int:
        return len(self.room_ids)

    @property
    def n_lecturers(self) -> int:
        return len(self.lect_ids)

    @property
    def n_classes(self) -> int:
        return len(self.class_ids)

    @property
    def n_sections(self) -> int:
        return len(self.sec_ids)

    @property
    def n_groups(self) -> int:
        return len(self.group_class)

    @property
    def n_events(self) -> int:
        return len(self.ev_section)

    def ev_domain(self, e: int) -> np.ndarray:
        """Các ô bắt đầu hợp lệ của event e."""
        return self.starts_by_len[int(self.ev_len[e])]

    @cached_property
    def windows(self) -> dict[int, np.ndarray]:
        """windows[L][i] = các ô của buổi dài L bắt đầu ở starts_by_len[L][i], shape (số vị trí, L)."""
        return {L: s[:, None] + np.arange(L) for L, s in self.starts_by_len.items()}

    @cached_property
    def window_day(self) -> dict[int, np.ndarray]:
        return {L: s // self.n_periods for L, s in self.starts_by_len.items()}

    @cached_property
    def window_edges(self) -> dict[int, tuple[np.ndarray, np.ndarray]]:
        """(chạm mép trái ca, chạm mép phải ca) của từng vị trí bắt đầu."""
        first = np.array([self.shifts[i][0] for i in self.shift_of_period])
        last = np.array([self.shifts[i][1] for i in self.shift_of_period])
        out = {}
        for L, s in self.starts_by_len.items():
            period = s % self.n_periods
            out[L] = (period == first[period], period + L - 1 == last[period])
        return out

    @cached_property
    def start_index(self) -> dict[int, dict[int, int]]:
        """start_index[L][ô bắt đầu] = vị trí trong starts_by_len[L]."""
        return {L: {int(x): i for i, x in enumerate(s)} for L, s in self.starts_by_len.items()}

    @cached_property
    def room_groups(self) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
        """Nhóm lớp-môn theo tập phòng dùng được (đúng loại, đủ sức chứa).

        Trả về (sec_group[s], group_size[g], superset[h, g]) với superset[h, g] = tập phòng của nhóm h
        nằm trong tập của nhóm g. Các tập cùng loại phòng lồng nhau theo sức chứa, nên điều kiện Hall
        "với mọi nhóm g, số buổi cùng lúc chỉ dùng được phòng trong g <= số phòng của g" là cách ước lượng
        thiếu phòng (H3) theo từng ô mà không phải gán phòng thật.
        """
        keys: dict[tuple[int, ...], int] = {}
        sec_group = np.empty(self.n_sections, dtype=np.int64)
        for s, rooms in enumerate(self.sec_usable_rooms):
            sec_group[s] = keys.setdefault(tuple(rooms.tolist()), len(keys))
        sets = [set(k) for k in keys]
        size = np.array([len(k) for k in keys])
        superset = np.array([[sets[h] <= sets[g] for g in range(len(sets))] for h in range(len(sets))], dtype=bool)
        return sec_group, size, superset.reshape(len(sets), len(sets))

    @cached_property
    def sec_usable_rooms(self) -> list[np.ndarray]:
        """Phòng dùng được (đúng loại, đủ sức chứa) của từng lớp-môn, sắp tăng dần theo sức chứa."""
        out = []
        for s in range(self.n_sections):
            ok = np.flatnonzero((self.room_type == self.sec_room_type[s]) & (self.room_cap >= self.sec_size[s]))
            out.append(ok[np.argsort(self.room_cap[ok], kind="stable")])
        return out

    @cached_property
    def sec_usable_rooms_list(self) -> list[list[int]]:
        """Như sec_usable_rooms nhưng dạng list Python, cho các vòng lặp nóng."""
        return [r.tolist() for r in self.sec_usable_rooms]

    @cached_property
    def shift_of_period(self) -> np.ndarray:
        """Chỉ số ca của từng tiết trong ngày."""
        out = np.full(self.n_periods, -1)
        for i, (first, last) in enumerate(self.shifts):
            out[first: last + 1] = i
        return out

    # --- Hiển thị ---------------------------------------------------------------

    def cell_label(self, cell: int) -> str:
        day, period = divmod(int(cell), self.n_periods)
        return f"T{day + 2} tiết {period + 1}"

    def summary(self) -> str:
        per_type = {t: int((self.room_type == i).sum()) for i, t in enumerate(self.room_types)}
        return (f"{self.n_classes} lớp, {self.n_sections} lớp-môn, {self.n_events} buổi/tuần, "
                f"{self.n_lecturers} giảng viên, {self.n_rooms} phòng {per_type}, "
                f"{int(self.sec_weekly.sum())} tiết/tuần, {self.n_groups} nhóm SV học thêm "
                f"({int(self.group_students.sum())} SV)")
