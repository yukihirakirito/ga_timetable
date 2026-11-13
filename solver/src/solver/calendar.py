"""Giai đoạn 2: trải tuần mẫu ra lịch thật theo ngày, xử lý ngày lễ, kiểm tra H9.

Đầu vào: lời giải tuần mẫu (giảng viên, ô bắt đầu, phòng của từng buổi). Với mỗi lớp-môn:

  1. **Trải theo pattern (Cách A).** Đi lần lượt tuần 1, 2, ... và các buổi trong tuần theo thứ tự
     trong tuần mẫu, sinh buổi học có ngày cụ thể cho tới khi đủ `total_sessions` buổi.
     Buổi rơi vào **ngày lễ** bị bỏ qua và không tính; pattern cứ thế chạy tiếp sang tuần sau
     ("lùi" buổi học), không cần tìm chỗ mới vì tuần mẫu đã đảm bảo không xung đột.
     Buổi cuối dài `total_periods - (total_sessions - 1) * periods_per_session` tiết.
  2. **Học bù.** Nếu tới hết tuần học cuối (study_weeks) vẫn chưa đủ buổi, tìm chỗ bù cho phần thiếu:
     ngày học không phải ngày lễ, trong các tuần học, lớp-môn chưa có buổi trong ngày đó (như H6),
     lớp và giảng viên rảnh, giảng viên không bận (H5), còn phòng phù hợp rảnh, buổi nằm trọn trong ca (H8).
     Ưu tiên ngày sớm nhất, cùng tiết bắt đầu và cùng phòng như tuần mẫu. Lớp-môn có ít chỗ bù nhất
     được xếp trước (cùng ý tưởng DSatur). Tham lam, không quay lui.
  3. **H9.** Lớp-môn vẫn thiếu buổi sau khi bù là vi phạm H9.

Mọi kiểm tra rảnh/bận dùng bitmask 12 bit cho mỗi (ngày học, lớp / giảng viên / phòng).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta

import numpy as np

from .problem import Problem
from .rooms import NO_ROOM
from .schedule import Schedule


@dataclass
class Session:
    section: int          # chỉ số lớp-môn
    seq_no: int           # buổi thứ mấy trong cả kỳ, từ 1
    date: date
    start_period: int     # 1..12
    length: int
    room: int             # chỉ số phòng, NO_ROOM nếu không có
    lecturer: int
    is_makeup: bool = False


@dataclass
class CalendarResult:
    sessions: list[Session]
    holidays_hit: dict[int, int] = field(default_factory=dict)   # lớp-môn -> số buổi rơi vào ngày lễ
    shifted: list[int] = field(default_factory=list)             # lớp-môn học lùi sang tuần sau, không cần bù
    makeups: dict[int, int] = field(default_factory=dict)        # lớp-môn -> số buổi học bù
    missing: dict[int, int] = field(default_factory=dict)        # H9: lớp-môn -> số buổi còn thiếu
    last_date: dict[int, date] = field(default_factory=dict)     # lớp-môn -> ngày học cuối

    @property
    def h9(self) -> int:
        return sum(self.missing.values())


def _bit(first: int, length: int) -> int:
    """Bitmask các tiết first..first+length-1 (0-based)."""
    return ((1 << length) - 1) << first


def expand_calendar(problem: Problem, schedule: Schedule, room: np.ndarray,
                    extra_holidays: list[date] | None = None) -> CalendarResult:
    p = problem
    sem = p.snapshot["semester"]
    start_date = date.fromisoformat(sem["start_date"])
    weeks = int(sem["study_weeks"])
    holidays = {date.fromisoformat(h["date"]) for h in sem["holidays"]} | set(extra_holidays or [])

    n_dates = weeks * p.n_days
    dates = [start_date + timedelta(days=7 * w + d) for w in range(weeks) for d in range(p.n_days)]
    is_holiday = [d in holidays for d in dates]

    class_busy = [[0] * p.n_classes for _ in range(n_dates)]
    lect_busy = [[0] * p.n_lecturers for _ in range(n_dates)]
    room_busy = [[0] * p.n_rooms for _ in range(n_dates)]
    sec_dates: list[set[int]] = [set() for _ in range(p.n_sections)]

    result = CalendarResult(sessions=[])
    counts = [0] * p.n_sections

    def length_of(s: int, seq_no: int) -> int:
        """Độ dài buổi thứ seq_no; buổi cuối có thể ngắn hơn."""
        if seq_no == int(p.sec_total_sessions[s]):
            return int(p.sec_total_periods[s] - (p.sec_total_sessions[s] - 1) * p.sec_len[s])
        return int(p.sec_len[s])

    def book(s: int, di: int, first: int, length: int, r: int, lec: int, makeup: bool) -> None:
        m = _bit(first, length)
        class_busy[di][p.sec_class[s]] |= m
        lect_busy[di][lec] |= m
        if r != NO_ROOM:
            room_busy[di][r] |= m
        sec_dates[s].add(di)
        counts[s] += 1
        result.sessions.append(Session(s, counts[s], dates[di], first + 1, length, r, lec, makeup))
        result.last_date[s] = max(result.last_date.get(s, dates[di]), dates[di])

    # --- 1. trải theo pattern ------------------------------------------------------
    for s in range(p.n_sections):
        lec = int(schedule.lecturer[s])
        pattern = sorted(p.sec_events[s].tolist(), key=lambda e: int(schedule.start[e]))
        total = int(p.sec_total_sessions[s])
        for w in range(weeks):
            for e in pattern:
                if counts[s] >= total:
                    break
                day, first = divmod(int(schedule.start[e]), p.n_periods)
                di = w * p.n_days + day
                if is_holiday[di]:
                    result.holidays_hit[s] = result.holidays_hit.get(s, 0) + 1
                    continue
                book(s, di, first, length_of(s, counts[s] + 1), int(room[e]), lec, False)
            if counts[s] >= total:
                break
        if s in result.holidays_hit and counts[s] >= total:
            result.shifted.append(s)

    # --- 2. học bù ---------------------------------------------------------------
    def makeup_options(s: int, length: int) -> list[tuple[int, int, int]]:
        """Các chỗ bù hợp lệ (ngày, tiết đầu, phòng), đã sắp theo thứ tự ưu tiên."""
        lec, c = int(schedule.lecturer[s]), int(p.sec_class[s])
        template = [int(schedule.start[e]) % p.n_periods for e in p.sec_events[s]]
        template_rooms = {int(room[e]) for e in p.sec_events[s]}
        rooms = p.sec_usable_rooms_list[s]
        out = []
        for di in range(n_dates):
            if is_holiday[di] or di in sec_dates[s]:
                continue
            day = di % p.n_days
            for first, last in p.shifts:
                for f in range(first, last - length + 2):
                    m = _bit(f, length)
                    cells = slice(day * p.n_periods + f, day * p.n_periods + f + length)
                    if class_busy[di][c] & m or lect_busy[di][lec] & m or p.unavailable[lec, cells].any():
                        continue
                    free = [r for r in rooms if not room_busy[di][r] & m]
                    if not free:
                        continue
                    r = next((r for r in free if r in template_rooms), free[0])
                    out.append((di, f, r, f not in template))
        out.sort(key=lambda x: (x[0], x[3]))          # ngày sớm nhất, rồi cùng tiết như tuần mẫu
        return [(di, f, r) for di, f, r, _ in out]

    pending = {s: int(p.sec_total_sessions[s]) - counts[s]
               for s in range(p.n_sections) if counts[s] < int(p.sec_total_sessions[s])}
    while pending:
        # Lớp-môn ít chỗ bù nhất trước
        options = {s: makeup_options(s, length_of(s, counts[s] + 1)) for s in pending}
        s = min(pending, key=lambda x: (len(options[x]), x))
        if not options[s]:
            result.missing[s] = pending.pop(s)
            continue
        di, f, r = options[s][0]
        book(s, di, f, length_of(s, counts[s] + 1), r, int(schedule.lecturer[s]), True)
        result.makeups[s] = result.makeups.get(s, 0) + 1
        pending[s] -= 1
        if pending[s] == 0:
            del pending[s]

    result.sessions.sort(key=lambda x: (x.date, x.start_period, x.section))
    return result


def sessions_as_rows(problem: Problem, result: CalendarResult) -> list[dict]:
    """Dạng dòng khớp bảng calendar_sessions (id gốc trong DB)."""
    p = problem
    return [{"section_id": int(p.sec_ids[x.section]), "seq_no": x.seq_no, "date": x.date.isoformat(),
             "start_period": x.start_period, "length": x.length,
             "room_id": int(p.room_ids[x.room]) if x.room != NO_ROOM else None,
             "lecturer_id": int(p.lect_ids[x.lecturer]), "is_makeup": x.is_makeup}
            for x in result.sessions]


def calendar_violations(problem: Problem, result: CalendarResult) -> list[dict]:
    p = problem
    return [{"code": "H9", "severity": "HARD",
             "detail": {"section_id": int(p.sec_ids[s]), "subject": p.sec_subject_code[s],
                        "class": p.class_codes[p.sec_class[s]], "missing_sessions": n}}
            for s, n in sorted(result.missing.items())]
