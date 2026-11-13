"""Dòng lệnh của solver.

    solver info SNAPSHOT                       thống kê bài toán
    solver evaluate SNAPSHOT [--seed N]        chấm điểm một lời giải ngẫu nhiên (kiểm tra evaluator)
    solver dsatur SNAPSHOT [--seeds N]         baseline tham lam DSatur
    solver ga SNAPSHOT [--generations N ...]   giải thuật di truyền (memetic) + trải ra lịch thật
    solver calendar SNAPSHOT --schedule F      trải một lịch tuần mẫu đã lưu ra lịch thật (thử ngày lễ)
    solver enqueue SNAPSHOT [--params JSON]    tạo run PENDING trong DB (thay cho web Go khi chạy thử)
    solver worker [--once]                     lấy job từ DB, chạy GA, ghi kết quả
"""

from __future__ import annotations

import argparse
import json
import logging
import signal
import sys
import time
from collections import Counter
from datetime import date, timedelta
from pathlib import Path

import numpy as np

from .calendar import CalendarResult, calendar_violations, expand_calendar, sessions_as_rows
from .dsatur import dsatur
from .evaluate import HARD_CODES, SOFT_CODES, Evaluation, Weights, evaluate, violations
from .ga import GAParams, run_ga
from .problem import SnapshotError, load_snapshot
from .schedule import Schedule, domain_errors, random_schedule

DAY_NAMES = ["Thứ 2", "Thứ 3", "Thứ 4", "Thứ 5", "Thứ 6", "Thứ 7"]

LABELS = {
    "H1": "Lớp trùng tiết", "H2": "Giảng viên trùng tiết", "H3": "Không còn phòng",
    "H4": "Phòng sai loại/thiếu chỗ", "H5": "Dạy giờ bận", "H6": "Hai buổi cùng ngày",
    "S1": "Lịch lớp không gọn", "S2": "Buổi môn ở ngày liền kề",
    "S4": "Ngày GV lên trường", "S5": "Bỏ trống giờ ưu tiên", "S6": "Lệch tải GV",
    "S7": "Lớp-môn đổi phòng", "S8": "Vượt tải tối đa",
}


def print_evaluation(title: str, ev: Evaluation, w: Weights) -> None:
    print(f"{title}: fitness = {ev.fitness:,.1f}  (cứng {ev.hard_total} x {w.hard:g} + mềm {ev.soft_penalty:,.1f})")
    print(f"{'mã':<4}{'ràng buộc':<28}{'giá trị':>10}{'trọng số':>10}{'đóng góp':>12}")
    for c in HARD_CODES:
        print(f"{c:<4}{LABELS[c]:<28}{ev.hard[c]:>10}{w.hard:>10g}{w.hard * ev.hard[c]:>12,.1f}")
    for c in SOFT_CODES:
        print(f"{c:<4}{LABELS[c]:<28}{ev.soft[c]:>10,.1f}{w.soft(c):>10g}{w.soft(c) * ev.soft[c]:>12,.1f}")


def cmd_dsatur(args) -> int:
    p = load_snapshot(args.snapshot)
    w = Weights()
    print(p.summary())
    results = []
    for seed in range(args.seed, args.seed + args.seeds):
        t0 = time.perf_counter()
        s = dsatur(p, np.random.default_rng(seed), room_aware=not args.fast)
        secs = time.perf_counter() - t0
        assert not domain_errors(p, s)
        ev = evaluate(p, s, w)
        results.append((seed, ev, secs))
        print(f"seed {seed}: cứng {ev.hard_total:>3} {({k: v for k, v in ev.hard.items() if v})!s:<24} "
              f"mềm {ev.soft_penalty:>9,.1f}   {secs:.2f}s")
    if args.seeds > 1:
        hard = [ev.hard_total for _, ev, _ in results]
        soft = [ev.soft_penalty for _, ev, _ in results]
        print(f"trung bình: cứng {np.mean(hard):.1f} ± {np.std(hard):.1f}, mềm {np.mean(soft):,.1f} ± {np.std(soft):,.1f}, "
              f"{sum(h == 0 for h in hard)}/{len(hard)} lịch hợp lệ")
    best_seed, best, _ = min(results, key=lambda r: r[1].fitness)
    print()
    print_evaluation(f"Tốt nhất (seed {best_seed})", best, w)
    return 0


def cmd_ga(args) -> int:
    p = load_snapshot(args.snapshot)
    w = Weights()
    params = GAParams(pop_size=args.pop, generations=args.generations, seed=args.seed,
                      local_search=not args.no_local_search, ls_steps=args.ls_steps,
                      seed_dsatur=args.seed_dsatur, stagnation=args.stagnation, time_limit=args.time_limit)
    print(p.summary())
    print(f"tham số: {params.to_dict()}")

    def progress(row: dict) -> None:
        if row["generation"] % args.log_every == 0:
            print(f"thế hệ {row['generation']:>4}  tốt nhất {row['best_fitness']:>10,.1f}  "
                  f"trung bình {row['avg_fitness']:>10,.1f}  cứng {row['hard_violations']:>3}  "
                  f"{row['elapsed_ms'] / 1000:>6.1f}s", flush=True)

    res = run_ga(p, params, w, on_progress=progress)
    best = res.best
    assert not domain_errors(p, best.schedule)
    print(f"Dừng sau {res.generations} thế hệ, {res.elapsed:.1f}s ({res.stop_reason})")
    print()
    print_evaluation("Lịch tốt nhất", best.evaluation, w)
    cal = expand_calendar(p, best.schedule, best.evaluation.room)
    print()
    print_calendar_summary(p, cal)
    if args.out:
        out = {"params": params.to_dict(), "weights": w.to_dict(), "generations": res.generations,
               "elapsed_s": res.elapsed, "stop_reason": res.stop_reason,
               "fitness": best.fitness, "hard": best.evaluation.hard, "soft": best.evaluation.soft,
               "history": res.history,
               "schedule": {"lecturer": best.schedule.lecturer.tolist(), "start": best.schedule.start.tolist()},
               "violations": violations(p, best.schedule, best.evaluation) + calendar_violations(p, cal),
               "calendar_sessions": sessions_as_rows(p, cal)}
        Path(args.out).write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"Đã ghi {args.out}")
    return 0


def print_calendar_summary(p, cal: CalendarResult) -> None:
    need = int(p.sec_total_sessions.sum())
    print(f"Lịch thật: {len(cal.sessions)}/{need} buổi, kết thúc muộn nhất {max(cal.last_date.values())}")
    print(f"  buổi rơi vào ngày lễ: {sum(cal.holidays_hit.values())} "
          f"({len(cal.holidays_hit)} lớp-môn); học lùi sang tuần sau: {len(cal.shifted)} lớp-môn; "
          f"học bù: {sum(cal.makeups.values())} buổi; H9 (thiếu buổi): {cal.h9}")


def print_class_week(p, cal: CalendarResult, class_code: str, week: int) -> None:
    c = p.class_codes.index(class_code)
    monday = date.fromisoformat(p.snapshot["semester"]["start_date"]) + timedelta(days=7 * (week - 1))
    print(f"Lớp {class_code}, tuần {week} ({monday:%d/%m} - {monday + timedelta(days=5):%d/%m}):")
    rows = [x for x in cal.sessions if p.sec_class[x.section] == c and 0 <= (x.date - monday).days < 6]
    if not rows:
        print("  (không có buổi học)")
    for x in rows:
        room = p.room_codes[x.room] if x.room >= 0 else "?"
        tag = "  [học bù]" if x.is_makeup else ""
        print(f"  {DAY_NAMES[x.date.weekday()]} {x.date:%d/%m}  tiết {x.start_period:>2}-{x.start_period + x.length - 1:<2} "
              f"{p.sec_subject_code[x.section]:<8} {p.lect_codes[x.lecturer]:<7} phòng {room:<5} buổi {x.seq_no}{tag}")


def cmd_calendar(args) -> int:
    p = load_snapshot(args.snapshot)
    data = json.loads(Path(args.schedule).read_text(encoding="utf-8"))["schedule"]
    s = Schedule(np.array(data["lecturer"]), np.array(data["start"]))
    errors = domain_errors(p, s)
    if errors:
        print("Lịch không khớp snapshot:\n  " + "\n  ".join(errors[:5]), file=sys.stderr)
        return 1
    ev = evaluate(p, s)
    extra = [date.fromisoformat(d) for d in args.holiday]
    cal = expand_calendar(p, s, ev.room, extra)
    if extra:
        print(f"Thêm ngày lễ để thử: {', '.join(d.isoformat() for d in extra)}")
    print_calendar_summary(p, cal)
    for v in calendar_violations(p, cal):
        print(f"  H9: {v['detail']}")
    if args.show_class:
        print()
        print_class_week(p, cal, args.show_class, args.week)
    return 0


def cmd_info(args) -> int:
    p = load_snapshot(args.snapshot)
    print(p.summary())
    print(f"vị trí bắt đầu hợp lệ theo độ dài buổi: {({k: len(v) for k, v in p.starts_by_len.items()})}")
    sizes = [len(c) for c in p.sec_candidates]
    print(f"giảng viên dạy được mỗi lớp-môn: {min(sizes)}-{max(sizes)} (trung bình {np.mean(sizes):.1f})")
    return 0


def cmd_evaluate(args) -> int:
    p = load_snapshot(args.snapshot)
    s = random_schedule(p, np.random.default_rng(args.seed))
    assert not domain_errors(p, s)
    w = Weights()
    ev = evaluate(p, s, w)

    t0 = time.perf_counter()
    for _ in range(args.repeat):
        evaluate(p, s, w)
    ms = (time.perf_counter() - t0) / args.repeat * 1000

    print(p.summary())
    print_evaluation(f"Lời giải ngẫu nhiên (seed {args.seed})", ev, w)
    print(f"evaluate: {ms:.2f} ms/lần (trung bình {args.repeat} lần)")

    rows = violations(p, s, ev)
    print(f"violations(): {len(rows)} dòng {dict(Counter(r['code'] for r in rows))}")
    if args.show:
        for r in rows[: args.show]:
            print(json.dumps(r, ensure_ascii=False))
    return 0


def cmd_enqueue(args) -> int:
    import psycopg

    from .params import ParamsError
    from .worker import database_url, enqueue

    snapshot = json.loads(Path(args.snapshot).read_text(encoding="utf-8"))
    try:
        params = json.loads(args.params)
    except json.JSONDecodeError as e:
        print(f"--params không phải JSON: {e}", file=sys.stderr)
        return 1
    try:
        with psycopg.connect(args.database_url or database_url(), autocommit=True) as conn:
            for i in range(args.count):
                if args.count > 1:            # mỗi run một seed khác nhau
                    params = {**params, "ga": {**params.get("ga", {}), "seed": args.first_seed + i}}
                run_id = enqueue(conn, snapshot, params)
                print(f"Đã tạo run {run_id} (PENDING), params: {json.dumps(params, ensure_ascii=False)}")
    except ParamsError as e:
        print(e, file=sys.stderr)
        return 1
    return 0


def cmd_worker(args) -> int:
    from .worker import Worker, WorkerConfig, database_url, default_worker_id

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)-7s %(message)s", datefmt="%H:%M:%S")
    worker = Worker(WorkerConfig(dsn=args.database_url or database_url(),
                                 worker_id=args.worker_id or default_worker_id(),
                                 poll_interval=args.poll, heartbeat_interval=args.heartbeat,
                                 stale_after=args.stale_after))

    def on_signal(signum, frame):
        if worker.shutdown.is_set():            # lần thứ hai: thoát ngay
            raise KeyboardInterrupt
        logging.getLogger("solver.worker").warning(
            "nhận %s: dừng sau thế hệ hiện tại (nhấn lần nữa để thoát ngay)", signal.Signals(signum).name)
        worker.shutdown.set()

    signal.signal(signal.SIGINT, on_signal)
    signal.signal(signal.SIGTERM, on_signal)
    worker.run(once=args.once, max_jobs=args.max_jobs)
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="solver", description="GA timetabling solver")
    sub = parser.add_subparsers(dest="command", required=True)

    p_info = sub.add_parser("info", help="thống kê bài toán")
    p_info.add_argument("snapshot")
    p_info.set_defaults(func=cmd_info)

    p_eval = sub.add_parser("evaluate", help="chấm điểm một lời giải ngẫu nhiên")
    p_eval.add_argument("snapshot")
    p_eval.add_argument("--seed", type=int, default=0)
    p_eval.add_argument("--repeat", type=int, default=200, help="số lần chấm để đo thời gian")
    p_eval.add_argument("--show", type=int, default=0, help="in N dòng vi phạm chi tiết")
    p_eval.set_defaults(func=cmd_evaluate)

    p_ds = sub.add_parser("dsatur", help="baseline tham lam DSatur")
    p_ds.add_argument("snapshot")
    p_ds.add_argument("--seed", type=int, default=0, help="seed đầu tiên")
    p_ds.add_argument("--seeds", type=int, default=1, help="số seed chạy liên tiếp")
    p_ds.add_argument("--fast", action="store_true", help="không tính phòng khi đếm lựa chọn (nhanh ~8 lần, kém hơn)")
    p_ds.set_defaults(func=cmd_dsatur)

    d = GAParams()
    p_ga = sub.add_parser("ga", help="giải thuật di truyền (memetic)")
    p_ga.add_argument("snapshot")
    p_ga.add_argument("--generations", type=int, default=d.generations)
    p_ga.add_argument("--pop", type=int, default=d.pop_size, help="kích thước quần thể")
    p_ga.add_argument("--seed", type=int, default=d.seed)
    p_ga.add_argument("--ls-steps", type=int, default=d.ls_steps, help="số bước cải thiện mềm mỗi con")
    p_ga.add_argument("--no-local-search", action="store_true", help="GA thuần, không tìm kiếm cục bộ")
    p_ga.add_argument("--seed-dsatur", type=int, default=d.seed_dsatur, help="số cá thể ban đầu từ DSatur")
    p_ga.add_argument("--stagnation", type=int, default=d.stagnation)
    p_ga.add_argument("--time-limit", type=float, default=None, help="giây")
    p_ga.add_argument("--log-every", type=int, default=10)
    p_ga.add_argument("--out", help="ghi kết quả (lịch, lịch sử hội tụ) ra file JSON")
    p_ga.set_defaults(func=cmd_ga)

    p_cal = sub.add_parser("calendar", help="trải lịch tuần mẫu đã lưu ra lịch thật")
    p_cal.add_argument("snapshot")
    p_cal.add_argument("--schedule", required=True, help="file JSON do 'solver ga --out' ghi ra")
    p_cal.add_argument("--holiday", action="append", default=[], help="thêm ngày lễ YYYY-MM-DD (lặp lại được)")
    p_cal.add_argument("--show-class", help="in thời khoá biểu của lớp (mã lớp)")
    p_cal.add_argument("--week", type=int, default=1)
    p_cal.set_defaults(func=cmd_calendar)

    p_enq = sub.add_parser("enqueue", help="tạo run PENDING trong DB")
    p_enq.add_argument("snapshot")
    p_enq.add_argument("--params", default="{}", help='JSON, ví dụ \'{"ga": {"generations": 100}}\'')
    p_enq.add_argument("--count", type=int, default=1, help="tạo N run, seed lần lượt từ --first-seed")
    p_enq.add_argument("--first-seed", type=int, default=0)
    p_enq.add_argument("--database-url", help="mặc định: DATABASE_URL hoặc ghép từ .env")
    p_enq.set_defaults(func=cmd_enqueue)

    p_wk = sub.add_parser("worker", help="lấy job từ DB, chạy GA, ghi kết quả")
    p_wk.add_argument("--once", action="store_true", help="thoát khi hàng đợi rỗng")
    p_wk.add_argument("--max-jobs", type=int, help="thoát sau N job")
    p_wk.add_argument("--worker-id", help="mặc định: hostname:pid")
    p_wk.add_argument("--poll", type=float, default=2.0, help="giây chờ khi hàng đợi rỗng")
    p_wk.add_argument("--heartbeat", type=float, default=10.0, help="chu kỳ heartbeat, giây")
    p_wk.add_argument("--stale-after", type=float, default=60.0, help="heartbeat quá hạn bấy nhiêu giây = worker chết")
    p_wk.add_argument("--database-url", help="mặc định: DATABASE_URL hoặc ghép từ .env")
    p_wk.set_defaults(func=cmd_worker)

    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except SnapshotError as e:
        print(e, file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
