"""Kiểm tra một input_snapshot: cấu trúc (JSON Schema) + ràng buộc chéo giữa các phần.

JSON Schema chỉ kiểm tra được từng object riêng lẻ. Những gì cần nhìn nhiều object cùng lúc
(id tham chiếu tồn tại, giá trị suy ra khớp tín chỉ...) được kiểm tra ở đây.

Cách dùng:
    python3 contracts/validate.py contracts/examples/input_snapshot.tiny.json
"""

from __future__ import annotations

import json
import math
import sys
from datetime import date, timedelta
from pathlib import Path

from jsonschema import Draft202012Validator, FormatChecker

SCHEMA_PATH = Path(__file__).with_name("input_snapshot.schema.json")
PERIODS_PER_CREDIT = 15


def schema_errors(snapshot: dict) -> list[str]:
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    validator = Draft202012Validator(schema, format_checker=FormatChecker())
    return [
        f"schema: /{'/'.join(map(str, e.absolute_path))}: {e.message}"
        for e in sorted(validator.iter_errors(snapshot), key=lambda e: list(e.absolute_path))
    ]


def _index(items: list[dict], name: str, errors: list[str]) -> dict[int, dict]:
    out: dict[int, dict] = {}
    for item in items:
        if item["id"] in out:
            errors.append(f"{name}: trùng id {item['id']}")
        out[item["id"]] = item
    codes = [item["code"] for item in items if "code" in item]
    if len(codes) != len(set(codes)):
        errors.append(f"{name}: trùng code")
    return out


def semantic_errors(s: dict) -> list[str]:
    errors: list[str] = []

    # Học kỳ
    sem = s["semester"]
    start, end = date.fromisoformat(sem["start_date"]), date.fromisoformat(sem["end_date"])
    if start.isoweekday() != 1:
        errors.append("semester: start_date phải là Thứ 2")
    min_end = start + timedelta(days=(sem["study_weeks"] + sem["exam_weeks"]) * 7 - 2)
    if end < min_end:
        errors.append(f"semester: end_date phải >= {min_end}")
    for h in sem["holidays"]:
        if not start <= date.fromisoformat(h["date"]) <= end:
            errors.append(f"semester: ngày lễ {h['date']} nằm ngoài học kỳ")

    # Lưới thời gian: ca hợp lệ, không chồng nhau
    shifts = sorted(s["time_grid"]["shifts"], key=lambda x: x["first_period"])
    for a, b in zip(shifts, shifts[1:]):
        if a["last_period"] >= b["first_period"]:
            errors.append(f"time_grid: ca {a['code']} chồng ca {b['code']}")
    for sh in shifts:
        if sh["first_period"] > sh["last_period"]:
            errors.append(f"time_grid: ca {sh['code']} có first_period > last_period")
    max_shift_len = max(sh["last_period"] - sh["first_period"] + 1 for sh in shifts)

    rooms = _index(s["rooms"], "rooms", errors)
    lecturers = _index(s["lecturers"], "lecturers", errors)
    subjects = _index(s["subjects"], "subjects", errors)
    classes = _index(s["classes"], "classes", errors)
    sections = _index(s["sections"], "sections", errors)

    # Giảng viên
    for lec in lecturers.values():
        for sid in lec["subject_ids"]:
            if sid not in subjects:
                errors.append(f"lecturer {lec['code']}: subject_id {sid} không tồn tại")
        for kind in ("unavailable", "preferred"):
            for r in lec[kind]:
                if r["period_from"] > r["period_to"]:
                    errors.append(f"lecturer {lec['code']}: {kind} có period_from > period_to")

    # Lớp-môn
    seen_pairs: set[tuple[int, int]] = set()
    for sec in sections.values():
        tag = f"section {sec['id']}"
        cls, sub = classes.get(sec["class_id"]), subjects.get(sec["subject_id"])
        if cls is None:
            errors.append(f"{tag}: class_id {sec['class_id']} không tồn tại")
        if sub is None:
            errors.append(f"{tag}: subject_id {sec['subject_id']} không tồn tại")
        pair = (sec["class_id"], sec["subject_id"])
        if pair in seen_pairs:
            errors.append(f"{tag}: lớp {pair[0]} học môn {pair[1]} hai lần")
        seen_pairs.add(pair)
        if sub is None:
            continue

        # Giá trị suy ra phải khớp tín chỉ
        pps, total = sec["periods_per_session"], sec["total_periods"]
        if total != PERIODS_PER_CREDIT * sub["credits"]:
            errors.append(f"{tag}: total_periods {total} != 15 x {sub['credits']} TC")
        if sec["total_sessions"] != math.ceil(total / pps):
            errors.append(f"{tag}: total_sessions phải = ceil({total}/{pps})")
        last = total - (sec["total_sessions"] - 1) * pps
        if last < 2:
            errors.append(f"{tag}: buổi cuối chỉ còn {last} tiết (< 2)")
        if sub["credits"] >= 4 and pps < 3:
            errors.append(f"{tag}: môn >= 4 TC phải có >= 3 tiết/buổi")
        if pps > max_shift_len:
            errors.append(f"{tag}: buổi {pps} tiết dài hơn ca dài nhất")
        weeks = math.ceil(sec["total_sessions"] / sec["sessions_per_week"])
        if weeks > sem["study_weeks"]:
            errors.append(f"{tag}: cần {weeks} tuần > {sem['study_weeks']} tuần học (H9)")

        # Phải có ít nhất một giảng viên và một phòng phù hợp, không thì vô nghiệm ngay
        if not any(sub["id"] in lec["subject_ids"] for lec in lecturers.values()):
            errors.append(f"{tag}: không giảng viên nào dạy được môn {sub['code']}")
        if cls is not None and not any(
            r["room_type"] == sub["room_type"] and r["capacity"] >= cls["size"] for r in rooms.values()
        ):
            errors.append(f"{tag}: không có phòng {sub['room_type']} chứa được {cls['size']} SV")

    return errors


def validate(snapshot: dict) -> list[str]:
    errors = schema_errors(snapshot)
    if errors:  # cấu trúc sai thì kiểm tra chéo dễ ném KeyError, dừng ở đây
        return errors
    return semantic_errors(snapshot)


def main() -> int:
    if len(sys.argv) != 2:
        print(__doc__)
        return 2
    snapshot = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
    errors = validate(snapshot)
    for e in errors:
        print(f"  ✗ {e}")
    print(f"{'HỢP LỆ' if not errors else f'{len(errors)} LỖI'}: {sys.argv[1]}")
    return 0 if not errors else 1


if __name__ == "__main__":
    sys.exit(main())
