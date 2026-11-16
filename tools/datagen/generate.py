"""Sinh dữ liệu mẫu cho 3 bộ small / medium / large.

Đầu vào : tools/datagen/curriculum.yaml (viết tay)
Đầu ra  : db/seeds/<tên>.sql            nạp vào PostgreSQL (xoá dữ liệu cũ trước khi nạp)
          db/seeds/<tên>.snapshot.json  input_snapshot tương ứng, để phát triển solver khi chưa có Go

Lớp, giảng viên, phòng, sinh viên được sinh ngẫu nhiên có seed (chạy lại ra y hệt).
Số giảng viên và số phòng được tính từ nhu cầu để không quá tải:
  - tải phòng mỗi loại <= 75%
  - giảng viên trung bình khoảng 16 tiết/tuần (tối đa 16-24)
Sinh viên: mỗi lớp đúng `size` sinh viên; ~5% sinh viên học lại 1-2 môn kỳ dưới (theo chương trình ngành mình)
ở một lớp bất kỳ đang học môn đó. Phần sinh viên dùng bộ số ngẫu nhiên riêng, nên lớp, lớp-môn, giảng viên
giữ nguyên như khi chưa có sinh viên; phòng có thể thêm vì sĩ số lớp-môn tính cả sinh viên học thêm.

Cách dùng:
    python3 tools/datagen/generate.py            # sinh cả 3 bộ
    python3 tools/datagen/generate.py medium     # chỉ một bộ
"""

from __future__ import annotations

import json
import math
import random
import sys
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
CURRICULUM_PATH = Path(__file__).with_name("curriculum.yaml")
SEEDS_DIR = ROOT / "db" / "seeds"

# Phải khớp dữ liệu seed của credit_rules trong db/migrations/000001_master_data.up.sql
CREDIT_RULES = {  # tín chỉ -> (tiết/buổi, buổi/tuần)
    1: (3, 1),
    2: (3, 1),
    3: (3, 2),
    4: (4, 2),
    5: (5, 2),
}
PERIODS_PER_CREDIT = 15
PERIODS_PER_WEEK = 72          # 6 ngày x 12 tiết
ROOM_UTIL_MAX = 0.75
LECTURER_TARGET_LOAD = 16      # tiết/tuần trung bình mong muốn
LECTURER_MAX_CHOICES = [16, 20, 20, 24]
MAX_SUBJECTS_PER_LECTURER = 5
CLASSES_PER_MAJOR = (5, 8)
CLASS_SIZE = (25, 40)
ROOM_CAPACITIES = {"THEORY": [40, 50, 60], "LAB": [35, 40, 40, 45], "STUDIO": [35, 40]}
ROOM_PREFIX = {"THEORY": "P", "LAB": "L", "STUDIO": "S"}
RETAKE_RATE = 0.05             # tỉ lệ sinh viên (trên tổng số) học lại
RETAKES_PER_STUDENT = (1, 2)   # số môn học lại của một sinh viên

SEMESTER = {
    "id": 1,
    "name": "Fall 2026",
    "start_date": "2026-09-07",
    "end_date": "2027-01-09",
    "study_weeks": 15,
    "exam_weeks": 3,
    "holidays": [
        {"date": "2026-11-20", "name": "Ngày Nhà giáo Việt Nam (nghỉ theo lịch trường)"},
        {"date": "2027-01-01", "name": "Tết Dương lịch"},
    ],
}
TIME_GRID = {
    "days_per_week": 6,
    "periods_per_day": 12,
    "shifts": [
        {"code": "MORNING", "first_period": 1, "last_period": 6},
        {"code": "AFTERNOON", "first_period": 7, "last_period": 12},
    ],
}
GENERATED_AT = "2026-11-13T00:00:00+07:00"  # cố định để file sinh ra không đổi giữa các lần chạy

ALL_MAJORS = ["SE", "WEB", "MOB", "QA", "AI", "DA", "SEC", "NET", "CLD", "IOT", "UX", "GAME"]
DATASETS = {
    "small": {"majors": ["SE", "WEB"], "seed": 101},
    "medium": {"majors": ["SE", "WEB", "MOB", "AI", "DA", "UX"], "seed": 202},
    "large": {"majors": ALL_MAJORS, "seed": 303},
}

FAMILY = ["Nguyễn", "Trần", "Lê", "Phạm", "Hoàng", "Huỳnh", "Phan", "Vũ", "Võ", "Đặng", "Bùi", "Đỗ", "Hồ", "Ngô", "Dương", "Lý"]
MIDDLE = ["Văn", "Thị", "Minh", "Thanh", "Quang", "Thu", "Hoài", "Đức", "Ngọc", "Hải", "Anh", "Bảo", "Gia", "Khánh"]
GIVEN = ["An", "Bình", "Châu", "Dũng", "Giang", "Hà", "Hiếu", "Hùng", "Hương", "Khoa", "Lan", "Linh", "Long", "Mai",
         "Nam", "Nga", "Phong", "Phúc", "Quân", "Sơn", "Tâm", "Thảo", "Trang", "Trung", "Tuấn", "Uyên", "Vy", "Yến"]


# ---------------------------------------------------------------------------
# Chương trình đào tạo
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class Subject:
    code: str
    name: str
    credits: int
    room_type: str
    department: str

    @property
    def periods_per_session(self) -> int:
        return CREDIT_RULES[self.credits][0]

    @property
    def sessions_per_week(self) -> int:
        return CREDIT_RULES[self.credits][1]

    @property
    def weekly_periods(self) -> int:
        """Số tiết/tuần trong tuần mẫu của một lớp-môn."""
        return self.periods_per_session * self.sessions_per_week


class Curriculum:
    def __init__(self, path: Path):
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
        self.departments: dict[str, str] = raw["departments"]
        self.subjects: dict[str, Subject] = {}
        self.majors: dict[str, dict] = raw["majors"]
        # (ngành, kỳ) -> danh sách mã môn
        self.plan: dict[tuple[str, int], list[str]] = {}

        common = {int(t): self._load(items, None) for t, items in raw["common"].items()}
        groups = {
            g: {int(t): self._load(items, spec["department"]) for t, items in spec["terms"].items()}
            for g, spec in raw["groups"].items()
        }
        for code, spec in self.majors.items():
            own = {int(t): self._load(items, spec["department"]) for t, items in spec["terms"].items()}
            for term in range(1, 7):
                self.plan[(code, term)] = common.get(term, []) + groups[spec["group"]].get(term, []) + own.get(term, [])
        self._check()

    def _load(self, items: list, default_department: str | None) -> list[str]:
        codes = []
        for item in items:
            code, name, credits, room_type, *rest = item
            dept = rest[0] if rest else default_department
            subject = Subject(code, name, int(credits), room_type, dept)
            if code in self.subjects and self.subjects[code] != subject:
                raise ValueError(f"Môn {code} khai báo hai lần với nội dung khác nhau")
            self.subjects[code] = subject
            codes.append(code)
        return codes

    def _check(self) -> None:
        for dept in {s.department for s in self.subjects.values()}:
            if dept not in self.departments:
                raise ValueError(f"Bộ môn {dept} chưa khai báo")
        for (major, term), codes in self.plan.items():
            total = sum(self.subjects[c].credits for c in codes)
            if not 15 <= total <= 18:
                raise ValueError(f"{major} kỳ {term}: {total} TC, ngoài khoảng 15-18")


# ---------------------------------------------------------------------------
# Sinh một bộ dữ liệu
# ---------------------------------------------------------------------------

@dataclass
class Lecturer:
    id: int
    code: str
    name: str
    department: str
    max_periods_per_week: int
    subject_codes: set[str] = field(default_factory=set)
    unavailable: list[dict] = field(default_factory=list)
    preferred: list[dict] = field(default_factory=list)


class Dataset:
    def __init__(self, name: str, curriculum: Curriculum, majors: list[str], seed: int):
        self.name = name
        self.cur = curriculum
        self.rng = random.Random(seed)
        self.major_codes = majors

        self.department_ids = {code: i for i, code in enumerate(curriculum.departments, start=1)}
        self.major_ids = {code: i for i, code in enumerate(majors, start=1)}

        # Môn thuộc chương trình của các ngành được chọn (giữ thứ tự xuất hiện)
        ordered: list[str] = []
        for major in majors:
            for term in range(1, 7):
                ordered += [c for c in curriculum.plan[(major, term)] if c not in ordered]
        self.subject_ids = {code: i for i, code in enumerate(ordered, start=1)}

        self.classes = self._gen_classes()
        self.sections = self._gen_sections()
        self.lecturers = self._gen_lecturers()
        # Bộ số ngẫu nhiên riêng: thêm sinh viên không làm đổi lớp / giảng viên / phòng đã sinh trước đó
        self.students, self.extras = self._gen_students(random.Random(seed * 7919 + 1))
        extra_count: dict[int, int] = defaultdict(int)
        for sec, _ in self.extras:
            extra_count[sec["id"]] += 1
        for sec in self.sections:  # sĩ số lớp-môn = sĩ số lớp + số sinh viên học thêm
            sec["size"] = sec["class"]["size"] + extra_count[sec["id"]]
        self.rooms = self._gen_rooms()

    # -- lớp và lớp-môn -----------------------------------------------------

    def _gen_classes(self) -> list[dict]:
        classes = []
        for major in self.major_codes:
            n = self.rng.randint(*CLASSES_PER_MAJOR)
            # Kỳ 1 luôn có lớp; n < 6 thì bỏ bớt vài kỳ sau; dư thì dồn về kỳ đầu (khoá mới đông hơn)
            terms = [1] + sorted(self.rng.sample(range(2, 7), min(n, 6) - 1))
            per_term = {t: 1 for t in terms}
            for _ in range(n - len(terms)):
                per_term[self.rng.choice([1, 1, 2, 2, 3])] += 1
            for term in sorted(per_term):
                for seq in range(1, per_term[term] + 1):
                    classes.append({
                        "id": len(classes) + 1,
                        "code": f"{major}-K{term}-{seq:02d}",
                        "major": major,
                        "term_no": term,
                        "size": self.rng.randint(*CLASS_SIZE),
                    })
        return classes

    def _gen_sections(self) -> list[dict]:
        sections = []
        for cls in self.classes:
            for code in self.cur.plan[(cls["major"], cls["term_no"])]:
                sections.append({"id": len(sections) + 1, "class": cls, "subject": self.cur.subjects[code]})
        return sections

    # -- sinh viên ----------------------------------------------------------

    def _gen_students(self, rng: random.Random) -> tuple[list[dict], list[tuple[dict, dict]]]:
        """Trả về (sinh viên, [(lớp-môn học thêm, sinh viên)])."""
        students = []
        for cls in self.classes:
            for _ in range(cls["size"]):
                sid = len(students) + 1
                name = f"{rng.choice(FAMILY)} {rng.choice(MIDDLE)} {rng.choice(GIVEN)}"
                students.append({"id": sid, "code": f"SV{sid:05d}", "name": name, "class": cls})

        by_code: dict[str, list[dict]] = defaultdict(list)  # mã môn -> lớp-môn đang mở trong học kỳ
        for sec in self.sections:
            by_code[sec["subject"].code].append(sec)

        # Học lại: chỉ sinh viên từ kỳ 2 trở lên (có môn kỳ dưới), số lượng = RETAKE_RATE x tổng sinh viên
        eligible = [st for st in students if st["class"]["term_no"] >= 2]
        chosen = rng.sample(eligible, min(len(eligible), round(RETAKE_RATE * len(students))))
        extras: list[tuple[dict, dict]] = []
        for st in sorted(chosen, key=lambda x: x["id"]):
            cls = st["class"]
            current = set(self.cur.plan[(cls["major"], cls["term_no"])])
            lower = sorted({c for t in range(1, cls["term_no"]) for c in self.cur.plan[(cls["major"], t)]} - current)
            options = [c for c in lower if any(sec["class"] is not cls for sec in by_code[c])]
            if not options:
                continue
            k = min(rng.randint(*RETAKES_PER_STUDENT), len(options))
            for code in rng.sample(options, k):
                sec = rng.choice([s for s in by_code[code] if s["class"] is not cls])
                extras.append((sec, st))
        return students, extras

    def student_groups(self) -> list[dict]:
        """Gom sinh viên có cùng tập lớp-môn học thêm (cùng lớp) thành nhóm: {class_id, extra_section_ids, students}."""
        per_student: dict[int, list[int]] = defaultdict(list)
        owner: dict[int, dict] = {}
        for sec, st in self.extras:
            per_student[st["id"]].append(sec["id"])
            owner[st["id"]] = st
        count: dict[tuple[int, tuple[int, ...]], int] = defaultdict(int)
        for sid, secs in per_student.items():
            count[(owner[sid]["class"]["id"], tuple(sorted(secs)))] += 1
        return [{"class_id": cid, "extra_section_ids": list(secs), "students": n}
                for (cid, secs), n in sorted(count.items())]

    # -- giảng viên ---------------------------------------------------------

    def _gen_lecturers(self) -> list[Lecturer]:
        demand: dict[str, int] = defaultdict(int)  # mã môn -> tiết/tuần
        for sec in self.sections:
            demand[sec["subject"].code] += sec["subject"].weekly_periods

        by_dept: dict[str, list[str]] = defaultdict(list)
        for code in demand:
            by_dept[self.cur.subjects[code].department].append(code)

        lecturers: list[Lecturer] = []
        used_names: set[str] = set()
        for dept in self.cur.departments:  # thứ tự cố định
            subjects = sorted(by_dept.get(dept, []))
            if not subjects:
                continue
            total = sum(demand[c] for c in subjects)
            n = max(2, math.ceil(total / LECTURER_TARGET_LOAD),
                    math.ceil(2 * len(subjects) / MAX_SUBJECTS_PER_LECTURER))
            group = [self._new_lecturer(len(lecturers) + i + 1, dept, used_names) for i in range(n)]

            # Môn nhiều tiết cần nhiều giảng viên dạy được; mỗi môn ít nhất 2 người để GA có lựa chọn
            for code in sorted(subjects, key=lambda c: -demand[c]):
                k = min(n, max(2, math.ceil(demand[code] / 12)))
                free = [l for l in group if len(l.subject_codes) < MAX_SUBJECTS_PER_LECTURER]
                pool = sorted(free if len(free) >= k else group,
                              key=lambda l: (len(l.subject_codes), self.rng.random()))
                for lec in pool[:k]:
                    lec.subject_codes.add(code)
            # Mỗi giảng viên dạy ít nhất 2 môn (nếu bộ môn có đủ môn)
            for lec in group:
                others = [c for c in subjects if c not in lec.subject_codes]
                while len(lec.subject_codes) < min(2, len(subjects)) and others:
                    lec.subject_codes.add(others.pop(self.rng.randrange(len(others))))
            lecturers += group
        return lecturers

    def _new_lecturer(self, lid: int, dept: str, used: set[str]) -> Lecturer:
        while True:
            name = f"{self.rng.choice(FAMILY)} {self.rng.choice(MIDDLE)} {self.rng.choice(GIVEN)}"
            if name not in used:
                used.add(name)
                break
        lec = Lecturer(lid, f"GV{lid:03d}", name, dept, self.rng.choice(LECTURER_MAX_CHOICES))
        blocks = [(d, s) for d in range(1, 7) for s in TIME_GRID["shifts"]]
        self.rng.shuffle(blocks)
        # ~30% giảng viên bận 1-2 nửa ngày; ~25% có 1-2 nửa ngày ưu tiên
        if self.rng.random() < 0.30:
            lec.unavailable = [self._block(*blocks.pop()) for _ in range(self.rng.randint(1, 2))]
        if self.rng.random() < 0.25:
            lec.preferred = [self._block(*blocks.pop()) for _ in range(self.rng.randint(1, 2))]
        return lec

    @staticmethod
    def _block(day: int, shift: dict) -> dict:
        return {"day": day, "period_from": shift["first_period"], "period_to": shift["last_period"]}

    # -- phòng --------------------------------------------------------------

    def _gen_rooms(self) -> list[dict]:
        rooms: list[dict] = []
        cap_per_room = PERIODS_PER_WEEK * ROOM_UTIL_MAX
        for rtype in ("THEORY", "LAB", "STUDIO"):
            secs = [s for s in self.sections if s["subject"].room_type == rtype]
            if not secs:
                continue
            demand = sum(s["subject"].weekly_periods for s in secs)
            caps = [self.rng.choice(ROOM_CAPACITIES[rtype]) for _ in range(max(2, math.ceil(demand / cap_per_room)))]
            # Lớp-môn đông chỉ vào được phòng lớn: với mọi sĩ số s,
            # nhu cầu của các lớp-môn >= s phải vừa với các phòng sức chứa >= s.
            # Sĩ số lớp-môn vượt cả phòng lớn nhất thì thêm phòng đúng bằng sĩ số đó.
            while True:
                short = sorted(size for size in {s["size"] for s in secs}
                               if sum(x["subject"].weekly_periods for x in secs if x["size"] >= size)
                               > cap_per_room * sum(1 for c in caps if c >= size))
                if not short:
                    break
                caps.append(max(max(ROOM_CAPACITIES[rtype]), math.ceil(short[-1] / 5) * 5))
            for i, cap in enumerate(sorted(caps, reverse=True), start=1):
                rooms.append({"id": len(rooms) + 1, "code": f"{ROOM_PREFIX[rtype]}{i:03d}",
                              "room_type": rtype, "capacity": cap})
        return rooms

    # -- thống kê -----------------------------------------------------------

    def report(self) -> str:
        lines = [f"[{self.name}] {len(self.major_codes)} ngành, {len(self.classes)} lớp, "
                 f"{len(self.sections)} lớp-môn, {len({s['subject'].code for s in self.sections})} môn có lớp, "
                 f"{len(self.lecturers)} giảng viên, {len(self.rooms)} phòng"]
        for rtype in ("THEORY", "LAB", "STUDIO"):
            n = sum(1 for r in self.rooms if r["room_type"] == rtype)
            if n:
                d = sum(s["subject"].weekly_periods for s in self.sections if s["subject"].room_type == rtype)
                lines.append(f"    phòng {rtype:<6}: {n:>3} phòng, nhu cầu {d:>4} tiết/tuần, tải {d / (n * PERIODS_PER_WEEK):.0%}")
        demand = sum(s["subject"].weekly_periods for s in self.sections)
        cap = sum(l.max_periods_per_week for l in self.lecturers)
        lines.append(f"    giảng viên : nhu cầu {demand} tiết/tuần, trung bình {demand / len(self.lecturers):.1f} "
                     f"tiết/GV, tổng tối đa {cap} ({demand / cap:.0%})")
        weekly = defaultdict(int)
        for s in self.sections:
            weekly[s["class"]["id"]] += s["subject"].weekly_periods
        lines.append(f"    lớp        : {min(weekly.values())}-{max(weekly.values())} tiết/tuần (sức chứa {PERIODS_PER_WEEK})")
        retakers = {st["id"] for _, st in self.extras}
        lines.append(f"    sinh viên  : {len(self.students)}, học lại {len(retakers)} ({len(retakers) / len(self.students):.1%}), "
                     f"{len(self.extras)} lượt học thêm, {len(self.student_groups())} nhóm; "
                     f"sĩ số lớp-môn tối đa {max(s['size'] for s in self.sections)}")
        return "\n".join(lines)

    # -- xuất SQL -----------------------------------------------------------

    def to_sql(self) -> str:
        subj = {code: self.cur.subjects[code] for code in self.subject_ids}
        out = [
            f"-- Bộ dữ liệu '{self.name}': sinh tự động bởi tools/datagen/generate.py, KHÔNG sửa tay.",
            "-- Xoá toàn bộ dữ liệu cũ (trừ room_types, credit_rules) rồi nạp lại.",
            "BEGIN;",
            "TRUNCATE departments, majors, subjects, curriculum_items, rooms, lecturers, lecturer_subjects,",
            "         lecturer_slots, student_classes, students, semesters, semester_holidays, semester_classes,",
            "         course_sections, extra_enrollments, schedule_runs, run_progress, section_assignments, template_sessions,",
            "         calendar_sessions, run_violations RESTART IDENTITY CASCADE;",
            "",
        ]
        out += _insert("departments", ["id", "code", "name"],
                       [(i, c, self.cur.departments[c]) for c, i in self.department_ids.items()])
        out += _insert("majors", ["id", "code", "name"],
                       [(i, c, self.cur.majors[c]["name"]) for c, i in self.major_ids.items()])
        out += _insert("subjects", ["id", "code", "name", "credits", "room_type", "department_id"],
                       [(i, c, subj[c].name, subj[c].credits, subj[c].room_type, self.department_ids[subj[c].department])
                        for c, i in self.subject_ids.items()])
        out += _insert("curriculum_items", ["major_id", "term_no", "subject_id"],
                       [(self.major_ids[m], t, self.subject_ids[c])
                        for m in self.major_codes for t in range(1, 7) for c in self.cur.plan[(m, t)]],
                       identity=False)
        out += _insert("rooms", ["id", "code", "room_type", "capacity"],
                       [(r["id"], r["code"], r["room_type"], r["capacity"]) for r in self.rooms])
        out += _insert("lecturers", ["id", "code", "name", "department_id", "max_periods_per_week"],
                       [(l.id, l.code, l.name, self.department_ids[l.department], l.max_periods_per_week)
                        for l in self.lecturers])
        out += _insert("lecturer_subjects", ["lecturer_id", "subject_id"],
                       [(l.id, self.subject_ids[c]) for l in self.lecturers for c in sorted(l.subject_codes)],
                       identity=False)
        slots = [(l.id, b["day"], b["period_from"], b["period_to"], kind)
                 for l in self.lecturers
                 for kind, blocks in (("UNAVAILABLE", l.unavailable), ("PREFERRED", l.preferred))
                 for b in blocks]
        out += _insert("lecturer_slots", ["id", "lecturer_id", "day", "period_from", "period_to", "kind"],
                       [(i, *row) for i, row in enumerate(slots, start=1)])
        out += _insert("student_classes", ["id", "code", "major_id"],
                       [(c["id"], c["code"], self.major_ids[c["major"]]) for c in self.classes])
        out += _insert("students", ["id", "code", "name", "class_id"],
                       [(st["id"], st["code"], st["name"], st["class"]["id"]) for st in self.students])
        sem = SEMESTER
        out += _insert("semesters", ["id", "name", "start_date", "end_date", "study_weeks", "exam_weeks"],
                       [(sem["id"], sem["name"], sem["start_date"], sem["end_date"], sem["study_weeks"], sem["exam_weeks"])])
        out += _insert("semester_holidays", ["semester_id", "date", "name"],
                       [(sem["id"], h["date"], h["name"]) for h in sem["holidays"]], identity=False)
        out += _insert("semester_classes", ["semester_id", "class_id", "term_no"],
                       [(sem["id"], c["id"], c["term_no"]) for c in self.classes], identity=False)
        out += _insert("course_sections", ["id", "semester_id", "class_id", "subject_id"],
                       [(s["id"], sem["id"], s["class"]["id"], self.subject_ids[s["subject"].code]) for s in self.sections])
        out += _insert("extra_enrollments", ["section_id", "student_id"],
                       sorted((sec["id"], st["id"]) for sec, st in self.extras), identity=False)
        out.append("-- Đưa sequence của cột identity về sau id lớn nhất")
        for table in ("departments", "majors", "subjects", "rooms", "lecturers", "lecturer_slots",
                      "student_classes", "students", "semesters", "course_sections"):
            out.append(f"SELECT setval(pg_get_serial_sequence('{table}', 'id'), max(id)) FROM {table};")
        out += ["", "COMMIT;", ""]
        return "\n".join(out)

    # -- xuất snapshot ------------------------------------------------------

    def to_snapshot(self) -> dict:
        used = sorted({s["subject"].code for s in self.sections}, key=self.subject_ids.get)
        return {
            "schema_version": "2.0",
            "generated_at": GENERATED_AT,
            "semester": SEMESTER,
            "time_grid": TIME_GRID,
            "rooms": self.rooms,
            "lecturers": [{
                "id": l.id,
                "code": l.code,
                "max_periods_per_week": l.max_periods_per_week,
                "subject_ids": sorted(self.subject_ids[c] for c in l.subject_codes),
                "unavailable": l.unavailable,
                "preferred": l.preferred,
            } for l in self.lecturers],
            "subjects": [{
                "id": self.subject_ids[c],
                "code": c,
                "credits": self.cur.subjects[c].credits,
                "room_type": self.cur.subjects[c].room_type,
            } for c in used],
            "classes": [{"id": c["id"], "code": c["code"], "term_no": c["term_no"], "size": c["size"]}
                        for c in self.classes],
            "sections": [{
                "id": s["id"],
                "class_id": s["class"]["id"],
                "subject_id": self.subject_ids[s["subject"].code],
                "total_periods": PERIODS_PER_CREDIT * s["subject"].credits,
                "periods_per_session": s["subject"].periods_per_session,
                "sessions_per_week": s["subject"].sessions_per_week,
                "total_sessions": math.ceil(PERIODS_PER_CREDIT * s["subject"].credits / s["subject"].periods_per_session),
                "size": s["size"],
            } for s in self.sections],
            "student_groups": self.student_groups(),
        }


def _sql_value(v) -> str:
    if isinstance(v, int):
        return str(v)
    return "'" + str(v).replace("'", "''") + "'"


def _insert(table: str, cols: list[str], rows: list[tuple], identity: bool = True) -> list[str]:
    if not rows:
        return []
    override = " OVERRIDING SYSTEM VALUE" if identity else ""
    body = ",\n".join("    (" + ", ".join(_sql_value(v) for v in row) + ")" for row in rows)
    return [f"INSERT INTO {table} ({', '.join(cols)}){override} VALUES", body + ";", ""]


def main(argv: list[str]) -> int:
    names = argv or list(DATASETS)
    unknown = [n for n in names if n not in DATASETS]
    if unknown:
        print(f"Không có bộ dữ liệu: {', '.join(unknown)}. Chọn trong: {', '.join(DATASETS)}")
        return 2
    curriculum = Curriculum(CURRICULUM_PATH)
    SEEDS_DIR.mkdir(parents=True, exist_ok=True)
    for name in names:
        spec = DATASETS[name]
        ds = Dataset(name, curriculum, spec["majors"], spec["seed"])
        (SEEDS_DIR / f"{name}.sql").write_text(ds.to_sql(), encoding="utf-8")
        (SEEDS_DIR / f"{name}.snapshot.json").write_text(
            json.dumps(ds.to_snapshot(), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(ds.report())
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
