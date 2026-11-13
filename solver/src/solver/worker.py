"""Worker: lấy job xếp lịch từ bảng schedule_runs (PostgreSQL làm hàng đợi), chạy GA, ghi kết quả.

Vòng đời một run:

    PENDING ──claim──► RUNNING ──► DONE        kết quả ghi trong MỘT transaction
                          │   ├──► FAILED      snapshot/params lỗi, exception, worker bị tắt,
                          │   │                hoặc heartbeat quá hạn (worker chết)
                          │   └──► CANCELLED   admin đổi status; worker thấy qua heartbeat, dừng GA
                          └─ heartbeat_at cập nhật mỗi `heartbeat_interval` giây (luồng riêng)

- **Claim**: `UPDATE ... WHERE id = (SELECT ... FOR UPDATE SKIP LOCKED LIMIT 1)`. Nhiều worker chạy
  song song không lấy trùng job, không chờ khoá của nhau.
- **Job mồ côi**: mỗi vòng lặp, worker đánh FAILED các job RUNNING có heartbeat quá `stale_after`
  giây (worker giữ job đã chết). Không tự chạy lại: job lỗi có thể làm worker chết lặp vô hạn;
  admin tạo run mới nếu muốn.
- **Mọi UPDATE trạng thái** đều kèm `status = 'RUNNING' AND worker_id = <mình>`: nếu job đã bị huỷ
  hoặc bị đánh FAILED trong lúc chạy, worker không ghi đè, và transaction ghi kết quả bị rollback.
"""

from __future__ import annotations

import json
import logging
import os
import socket
import threading
import traceback
from dataclasses import dataclass

import psycopg
from psycopg.types.json import Jsonb

from .calendar import CalendarResult, calendar_violations, expand_calendar, sessions_as_rows
from .evaluate import Weights, violations
from .ga import STOPPED, GAResult, run_ga
from .params import ParamsError, params_to_dict, parse_params
from .problem import REPO_ROOT, Problem, SnapshotError
from .rooms import NO_ROOM

log = logging.getLogger("solver.worker")


# --- cấu hình ------------------------------------------------------------------

def _read_dotenv(path) -> dict[str, str]:
    out: dict[str, str] = {}
    if path.exists():
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                out[k.strip()] = v.strip().strip('"').strip("'")
    return out


def database_url(dbname: str | None = None) -> str:
    """DATABASE_URL nếu có; nếu không, ghép từ DB_* (biến môi trường, rồi tới file .env ở gốc repo)."""
    if os.environ.get("DATABASE_URL") and dbname is None:
        return os.environ["DATABASE_URL"]
    env = {**_read_dotenv(REPO_ROOT / ".env"), **os.environ}
    return (f"postgresql://{env.get('DB_USER', 'timetable')}:{env.get('DB_PASSWORD', 'timetable')}"
            f"@{env.get('DB_HOST', 'localhost')}:{env.get('DB_PORT', '5432')}/"
            f"{dbname or env.get('DB_NAME', 'timetable')}")


def default_worker_id() -> str:
    return f"{socket.gethostname()}:{os.getpid()}"


# --- hàng đợi ------------------------------------------------------------------

@dataclass
class Job:
    id: int
    semester_id: int
    params: dict
    snapshot: dict


class JobError(Exception):
    """Job không chạy được vì dữ liệu đầu vào; ghi FAILED kèm thông báo."""


class JobLost(Exception):
    """Job không còn RUNNING của worker này (bị huỷ / bị đánh FAILED / bị xoá)."""


def enqueue(conn: psycopg.Connection, snapshot: dict, params: dict | None = None) -> int:
    """Tạo run PENDING. Kiểm tra snapshot + params trước để báo lỗi ngay (worker vẫn kiểm tra lại).

    params được lưu ở dạng đầy đủ (đã điền mặc định) để sau này đổi mặc định không đổi nghĩa run cũ.
    """
    Problem(snapshot)
    full = params_to_dict(*parse_params(params))
    row = conn.execute(
        "INSERT INTO schedule_runs (semester_id, params, input_snapshot) VALUES (%s, %s, %s) RETURNING id",
        (snapshot["semester"]["id"], Jsonb(full), Jsonb(snapshot))).fetchone()
    return int(row[0])


def claim(conn: psycopg.Connection, worker_id: str) -> Job | None:
    with conn.transaction():
        row = conn.execute(
            """
            UPDATE schedule_runs
               SET status = 'RUNNING', worker_id = %s, started_at = now(), heartbeat_at = now()
             WHERE id = (SELECT id FROM schedule_runs
                          WHERE status = 'PENDING'
                          ORDER BY created_at, id
                          FOR UPDATE SKIP LOCKED
                          LIMIT 1)
            RETURNING id, semester_id, params, input_snapshot
            """, (worker_id,)).fetchone()
    return Job(int(row[0]), int(row[1]), row[2] or {}, row[3]) if row else None


def fail_stale(conn: psycopg.Connection, stale_after: float) -> list[int]:
    """Đánh FAILED các job RUNNING có heartbeat quá hạn (worker giữ job đã chết)."""
    rows = conn.execute(
        """
        UPDATE schedule_runs
           SET status = 'FAILED', finished_at = now(),
               error = format('worker %%s mất heartbeat từ %%s (quá %%s giây)',
                              worker_id, heartbeat_at, %s::int)
         WHERE status = 'RUNNING' AND heartbeat_at < now() - make_interval(secs => %s)
        RETURNING id
        """, (round(stale_after), stale_after)).fetchall()
    return [int(r[0]) for r in rows]


def mark_failed(conn: psycopg.Connection, job_id: int, worker_id: str, error: str) -> bool:
    cur = conn.execute(
        """
        UPDATE schedule_runs SET status = 'FAILED', finished_at = now(), error = %s
         WHERE id = %s AND status = 'RUNNING' AND worker_id = %s
        """, (error, job_id, worker_id))
    return cur.rowcount == 1


def mark_cancelled_finished(conn: psycopg.Connection, job_id: int) -> bool:
    cur = conn.execute(
        "UPDATE schedule_runs SET finished_at = now() WHERE id = %s AND status = 'CANCELLED'", (job_id,))
    return cur.rowcount == 1


# --- ghi kết quả ---------------------------------------------------------------

def save_result(conn: psycopg.Connection, job: Job, worker_id: str, problem: Problem, res: GAResult,
                cal: CalendarResult, weights: Weights) -> None:
    """Ghi toàn bộ kết quả + chuyển DONE trong một transaction; job không còn của mình thì rollback."""
    p, best = problem, res.best
    sched, ev = best.schedule, best.evaluation
    run_id = job.id
    hard_total = ev.hard_total + cal.h9
    fitness = ev.fitness + weights.hard * cal.h9          # H9 chỉ biết sau giai đoạn 2

    with conn.transaction(), conn.cursor() as cur:
        with cur.copy("COPY section_assignments (run_id, section_id, lecturer_id) FROM STDIN") as cp:
            for s in range(p.n_sections):
                cp.write_row((run_id, int(p.sec_ids[s]), int(p.lect_ids[sched.lecturer[s]])))

        with cur.copy("COPY template_sessions (run_id, section_id, idx, day, start_period, length, room_id) "
                      "FROM STDIN") as cp:
            for e in range(p.n_events):
                day, period = divmod(int(sched.start[e]), p.n_periods)
                r = int(ev.room[e])
                cp.write_row((run_id, int(p.sec_ids[p.ev_section[e]]), int(p.ev_k[e]), day + 1, period + 1,
                              int(p.ev_len[e]), int(p.room_ids[r]) if r != NO_ROOM else None))

        with cur.copy("COPY calendar_sessions (run_id, section_id, seq_no, date, start_period, length, "
                      "room_id, lecturer_id, is_makeup) FROM STDIN") as cp:
            for x in sessions_as_rows(p, cal):
                cp.write_row((run_id, x["section_id"], x["seq_no"], x["date"], x["start_period"], x["length"],
                              x["room_id"], x["lecturer_id"], x["is_makeup"]))

        with cur.copy("COPY run_violations (run_id, code, severity, detail) FROM STDIN") as cp:
            for v in violations(p, sched, ev) + calendar_violations(p, cal):
                cp.write_row((run_id, v["code"], v["severity"], json.dumps(v["detail"], ensure_ascii=False)))

        cur.execute(
            """
            UPDATE schedule_runs
               SET status = 'DONE', finished_at = now(), heartbeat_at = now(),
                   best_fitness = %s, hard_violations = %s, soft_penalty = %s
             WHERE id = %s AND status = 'RUNNING' AND worker_id = %s
            """, (float(fitness), int(hard_total), float(ev.soft_penalty), run_id, worker_id))
        if cur.rowcount != 1:
            raise JobLost(f"run {run_id} không còn RUNNING của {worker_id}, huỷ ghi kết quả")


# --- heartbeat -----------------------------------------------------------------

class Heartbeat(threading.Thread):
    """Luồng riêng (kết nối riêng) cập nhật heartbeat_at; phát hiện job bị huỷ / bị lấy mất."""

    def __init__(self, dsn: str, job_id: int, worker_id: str, interval: float):
        super().__init__(name=f"heartbeat-{job_id}", daemon=True)
        self.dsn, self.job_id, self.worker_id, self.interval = dsn, job_id, worker_id, interval
        self.lost = threading.Event()        # job không còn RUNNING của mình
        self._done = threading.Event()

    def run(self) -> None:
        try:
            with psycopg.connect(self.dsn, autocommit=True) as conn:
                while not self._done.wait(self.interval):
                    try:
                        cur = conn.execute(
                            "UPDATE schedule_runs SET heartbeat_at = now() "
                            "WHERE id = %s AND status = 'RUNNING' AND worker_id = %s",
                            (self.job_id, self.worker_id))
                    except psycopg.Error as e:          # mất kết nối: để job thành mồ côi, worker khác dọn
                        log.warning("heartbeat run %s lỗi: %s", self.job_id, e)
                        return
                    if cur.rowcount == 0:
                        self.lost.set()
                        return
        except psycopg.Error as e:
            log.warning("heartbeat run %s không kết nối được: %s", self.job_id, e)

    def stop(self) -> None:
        self._done.set()
        self.join()


# --- worker --------------------------------------------------------------------

@dataclass
class WorkerConfig:
    dsn: str
    worker_id: str
    poll_interval: float = 2.0          # giây chờ giữa hai lần hỏi khi hàng đợi rỗng
    heartbeat_interval: float = 10.0
    stale_after: float = 60.0           # heartbeat quá hạn bấy nhiêu giây thì coi worker đã chết

    def __post_init__(self):
        if self.stale_after <= 2 * self.heartbeat_interval:
            raise ValueError("stale_after phải lớn hơn 2 x heartbeat_interval")


class Worker:
    def __init__(self, config: WorkerConfig):
        self.cfg = config
        self.shutdown = threading.Event()     # set từ signal handler hoặc test

    def run(self, once: bool = False, max_jobs: int | None = None) -> int:
        """Vòng lặp chính. `once`: thoát khi hàng đợi rỗng. Trả về số job đã xử lý."""
        cfg, done = self.cfg, 0
        log.info("worker %s bắt đầu", cfg.worker_id)
        with psycopg.connect(cfg.dsn, autocommit=True) as conn:
            while not self.shutdown.is_set():
                for run_id in fail_stale(conn, cfg.stale_after):
                    log.warning("run %s: worker giữ job mất heartbeat, đánh FAILED", run_id)
                job = claim(conn, cfg.worker_id)
                if job is None:
                    if once:
                        break
                    self.shutdown.wait(cfg.poll_interval)
                    continue
                self.process(conn, job)
                done += 1
                if max_jobs is not None and done >= max_jobs:
                    break
        log.info("worker %s dừng, đã xử lý %d job", cfg.worker_id, done)
        return done

    def process(self, conn: psycopg.Connection, job: Job) -> str:
        """Chạy một job, trả về trạng thái cuối nhìn từ worker này (DONE / FAILED / CANCELLED / LOST)."""
        cfg = self.cfg
        log.info("run %s: nhận job (học kỳ %s)", job.id, job.semester_id)
        hb = Heartbeat(cfg.dsn, job.id, cfg.worker_id, cfg.heartbeat_interval)
        hb.start()
        try:
            try:
                problem = Problem(job.snapshot)
                ga_params, weights = parse_params(job.params)
                if job.snapshot["semester"]["id"] != job.semester_id:
                    raise JobError(f"snapshot thuộc học kỳ {job.snapshot['semester']['id']}, "
                                   f"run thuộc học kỳ {job.semester_id}")
            except (SnapshotError, ParamsError, JobError) as e:
                return self._fail(conn, job, str(e))

            log.info("run %s: %s", job.id, problem.summary().replace("\n", "; "))

            def on_progress(row: dict) -> None:
                conn.execute(
                    "INSERT INTO run_progress (run_id, generation, best_fitness, avg_fitness, hard_violations, "
                    "elapsed_ms) VALUES (%s, %s, %s, %s, %s, %s)",
                    (job.id, row["generation"], row["best_fitness"], row["avg_fitness"],
                     row["hard_violations"], row["elapsed_ms"]))
                if row["generation"] % 10 == 0:
                    log.info("run %s: thế hệ %d, tốt nhất %.1f, cứng %d", job.id, row["generation"],
                             row["best_fitness"], row["hard_violations"])

            res = run_ga(problem, ga_params, weights, on_progress,
                         should_stop=lambda: hb.lost.is_set() or self.shutdown.is_set())

            if res.stop_reason == STOPPED:
                if hb.lost.is_set():
                    if mark_cancelled_finished(conn, job.id):
                        log.info("run %s: bị huỷ, dừng sau %d thế hệ", job.id, res.generations)
                        return "CANCELLED"
                    log.warning("run %s: job không còn của worker này, bỏ kết quả", job.id)
                    return "LOST"
                return self._fail(conn, job, f"worker {cfg.worker_id} bị tắt khi đang chạy "
                                             f"(sau {res.generations} thế hệ)")

            cal = expand_calendar(problem, res.best.schedule, res.best.evaluation.room)
            save_result(conn, job, cfg.worker_id, problem, res, cal, weights)
            log.info("run %s: DONE sau %d thế hệ, %.1fs (%s), fitness %.1f, cứng %d, %d buổi",
                     job.id, res.generations, res.elapsed, res.stop_reason,
                     res.best.fitness, res.best.evaluation.hard_total + cal.h9, len(cal.sessions))
            return "DONE"
        except JobLost as e:
            log.warning("run %s: %s", job.id, e)
            return "LOST"
        except Exception:
            return self._fail(conn, job, traceback.format_exc()[-4000:])
        finally:
            hb.stop()

    def _fail(self, conn: psycopg.Connection, job: Job, error: str) -> str:
        if mark_failed(conn, job.id, self.cfg.worker_id, error):
            log.error("run %s: FAILED: %s", job.id, error.strip().splitlines()[-1])
            return "FAILED"
        return "LOST"
