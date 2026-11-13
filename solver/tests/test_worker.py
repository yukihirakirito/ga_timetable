"""Test tích hợp worker với PostgreSQL thật.

Dùng database riêng `timetable_test` trong cùng container (tạo lại mỗi lần chạy, nạp migration +
bộ dữ liệu small), không đụng vào database `timetable` đang xem trong Navicat.
Tự bỏ qua khi không kết nối được PostgreSQL.
"""

import copy
import json
import threading
import time
from pathlib import Path

import numpy as np
import psycopg
import pytest
from psycopg.types.json import Jsonb

from solver.calendar import expand_calendar
from solver.ga import GAParams, run_ga
from solver.params import parse_params
from solver.problem import Problem
from solver.worker import (Job, JobLost, Worker, WorkerConfig, claim, database_url, enqueue, fail_stale,
                           save_result)

ROOT = Path(__file__).resolve().parents[2]
TEST_DB = "timetable_test"
SNAPSHOT = json.loads((ROOT / "db" / "seeds" / "small.snapshot.json").read_text(encoding="utf-8"))
FAST = {"ga": {"pop_size": 4, "generations": 3, "elite": 1, "tournament_k": 2,
               "init_ls_steps": 50, "ls_steps": 20}}


@pytest.fixture(scope="module")
def dsn():
    try:
        admin = psycopg.connect(database_url(), autocommit=True, connect_timeout=3)
    except psycopg.OperationalError:
        pytest.skip("không kết nối được PostgreSQL (docker compose up -d db)")
    with admin:
        admin.execute(f"DROP DATABASE IF EXISTS {TEST_DB} WITH (FORCE)")
        admin.execute(f"CREATE DATABASE {TEST_DB}")
    url = database_url(TEST_DB)
    with psycopg.connect(url, autocommit=True) as conn:
        for f in sorted((ROOT / "db" / "migrations").glob("*.up.sql")):
            conn.execute(f.read_text(encoding="utf-8"))
        conn.execute((ROOT / "db" / "seeds" / "small.sql").read_text(encoding="utf-8"))
    return url


@pytest.fixture
def conn(dsn):
    with psycopg.connect(dsn, autocommit=True) as c:
        # Không dùng TRUNCATE ... CASCADE: semesters có FK published_run_id -> schedule_runs nên
        # CASCADE sẽ xoá luôn semesters (và course_sections...). DELETE chỉ cascade xuống bảng kết quả.
        c.execute("DELETE FROM schedule_runs")
        c.execute("ALTER TABLE schedule_runs ALTER COLUMN id RESTART")
        yield c


def make_worker(dsn, name="w-test", heartbeat=0.2):
    return Worker(WorkerConfig(dsn=dsn, worker_id=name, poll_interval=0.1,
                               heartbeat_interval=heartbeat, stale_after=60))


def run_row(conn, run_id):
    cur = conn.execute("SELECT * FROM schedule_runs WHERE id = %s", (run_id,))
    cols = [d.name for d in cur.description]
    return dict(zip(cols, cur.fetchone()))


def count(conn, table, run_id):
    return conn.execute(f"SELECT count(*) FROM {table} WHERE run_id = %s", (run_id,)).fetchone()[0]


def insert_raw(conn, snapshot, params):
    """Như Go chèn trực tiếp, không qua enqueue() (không kiểm tra trước)."""
    return conn.execute("INSERT INTO schedule_runs (semester_id, params, input_snapshot) "
                        "VALUES (%s, %s, %s) RETURNING id",
                        (SNAPSHOT["semester"]["id"], Jsonb(params), Jsonb(snapshot))).fetchone()[0]


def wait_for(predicate, timeout=60.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.1)
    return False


# --- luồng thành công -------------------------------------------------------------

def test_job_done_and_results_written(conn, dsn):
    run_id = enqueue(conn, SNAPSHOT, FAST)
    stored = run_row(conn, run_id)
    assert stored["status"] == "PENDING"
    assert stored["params"]["ga"]["generations"] == 3 and "S8" in stored["params"]["weights"]   # đã điền mặc định

    assert make_worker(dsn).run(once=True) == 1

    r = run_row(conn, run_id)
    assert r["status"] == "DONE" and r["worker_id"] == "w-test" and r["error"] is None
    assert r["started_at"] <= r["finished_at"] and r["best_fitness"] is not None
    p = Problem(SNAPSHOT)
    assert count(conn, "run_progress", run_id) == 4                       # thế hệ 0..3
    assert count(conn, "section_assignments", run_id) == p.n_sections
    assert count(conn, "template_sessions", run_id) == p.n_events
    n_cal = count(conn, "calendar_sessions", run_id)
    if r["hard_violations"] == 0:
        assert n_cal == int(p.sec_total_sessions.sum())
        # Không thiếu buổi (H9) thì tổng tiết mỗi lớp-môn trong lịch thật bằng đúng 15 x TC
        rows = conn.execute("""SELECT c.section_id, sum(c.length) AS periods, max(sj.credits) * 15 AS expected
                                 FROM calendar_sessions c
                                 JOIN course_sections cs ON cs.id = c.section_id
                                 JOIN subjects sj ON sj.id = cs.subject_id
                                WHERE c.run_id = %s
                                GROUP BY c.section_id""", (run_id,)).fetchall()
        assert len(rows) == p.n_sections
        assert all(periods == expected for _, periods, expected in rows)
    soft_rows = conn.execute("SELECT count(*) FROM run_violations WHERE run_id = %s AND severity = 'SOFT'",
                             (run_id,)).fetchone()[0]
    assert soft_rows > 0


def test_worker_takes_jobs_in_fifo_order(conn, dsn):
    a = enqueue(conn, SNAPSHOT, FAST)
    b = enqueue(conn, SNAPSHOT, FAST)
    assert make_worker(dsn).run(once=True, max_jobs=1) == 1
    assert run_row(conn, a)["status"] == "DONE" and run_row(conn, b)["status"] == "PENDING"


# --- hàng đợi --------------------------------------------------------------------

def test_skip_locked_two_workers_get_different_jobs(conn, dsn):
    ids = {enqueue(conn, SNAPSHOT, FAST) for _ in range(2)}
    with psycopg.connect(dsn, autocommit=True) as c1, psycopg.connect(dsn, autocommit=True) as c2:
        with c1.transaction():                      # worker 1 nhận job nhưng chưa commit (còn giữ khoá)
            j1 = claim(c1, "w1")
            j2 = claim(c2, "w2")                    # không chờ khoá, lấy job kế tiếp
            assert j1 and j2 and j1.id != j2.id and {j1.id, j2.id} == ids
            assert claim(c2, "w2") is None          # hết job
    assert {run_row(conn, i)["worker_id"] for i in ids} == {"w1", "w2"}


def test_stale_running_job_is_failed(conn):
    run_id = enqueue(conn, SNAPSHOT, FAST)
    claim(conn, "dead-worker")
    conn.execute("UPDATE schedule_runs SET heartbeat_at = now() - interval '5 minutes' WHERE id = %s", (run_id,))
    fresh = enqueue(conn, SNAPSHOT, FAST)
    claim(conn, "alive-worker")                     # heartbeat mới, không bị đụng tới

    assert fail_stale(conn, 60) == [run_id]
    r = run_row(conn, run_id)
    assert r["status"] == "FAILED" and r["finished_at"] is not None and "dead-worker" in r["error"]
    assert run_row(conn, fresh)["status"] == "RUNNING"


# --- lỗi đầu vào -----------------------------------------------------------------

def test_invalid_params_fail(conn, dsn):
    run_id = insert_raw(conn, SNAPSHOT, {"ga": {"pop": 10}})
    make_worker(dsn).run(once=True)
    r = run_row(conn, run_id)
    assert r["status"] == "FAILED" and "pop" in r["error"] and r["finished_at"] is not None


@pytest.mark.parametrize("breaker, needle", [
    (lambda s: s.update(schema_version="9.9"), "schema_version"),
    (lambda s: s["sections"][0].update(subject_id=99999), "subject"),
    (lambda s: s["semester"].update(id=777), "học kỳ"),
])
def test_invalid_snapshot_fail(conn, dsn, breaker, needle):
    snap = copy.deepcopy(SNAPSHOT)
    breaker(snap)
    run_id = insert_raw(conn, snap, FAST)
    make_worker(dsn).run(once=True)
    r = run_row(conn, run_id)
    assert r["status"] == "FAILED" and needle in r["error"]
    assert count(conn, "calendar_sessions", run_id) == 0


# --- dừng giữa chừng -------------------------------------------------------------

def _start_long_job(conn, dsn):
    run_id = enqueue(conn, SNAPSHOT, {"ga": {**FAST["ga"], "generations": 100000, "stagnation": 100000}})
    worker = make_worker(dsn)
    t = threading.Thread(target=worker.run, kwargs={"once": True})
    t.start()
    assert wait_for(lambda: count(conn, "run_progress", run_id) >= 3), "worker không ghi tiến độ"
    return run_id, worker, t


def test_cancel_stops_running_job(conn, dsn):
    run_id, _, t = _start_long_job(conn, dsn)
    conn.execute("UPDATE schedule_runs SET status = 'CANCELLED' WHERE id = %s", (run_id,))
    t.join(timeout=30)
    assert not t.is_alive()
    r = run_row(conn, run_id)
    assert r["status"] == "CANCELLED" and r["finished_at"] is not None
    assert count(conn, "section_assignments", run_id) == 0 and count(conn, "calendar_sessions", run_id) == 0


def test_shutdown_marks_job_failed(conn, dsn):
    run_id, worker, t = _start_long_job(conn, dsn)
    worker.shutdown.set()                           # như nhận SIGTERM
    t.join(timeout=30)
    assert not t.is_alive()
    r = run_row(conn, run_id)
    assert r["status"] == "FAILED" and "bị tắt" in r["error"]


def test_results_rolled_back_if_job_no_longer_ours(conn):
    run_id = enqueue(conn, SNAPSHOT, FAST)
    job = claim(conn, "w-test")
    p = Problem(job.snapshot)
    ga, w = parse_params(job.params)
    res = run_ga(p, ga, w)
    cal = expand_calendar(p, res.best.schedule, res.best.evaluation.room)
    conn.execute("UPDATE schedule_runs SET status = 'CANCELLED' WHERE id = %s", (run_id,))   # huỷ ngay trước khi ghi
    with pytest.raises(JobLost):
        save_result(conn, job, "w-test", p, res, cal, w)
    assert run_row(conn, run_id)["status"] == "CANCELLED"
    for table in ("section_assignments", "template_sessions", "calendar_sessions", "run_violations"):
        assert count(conn, table, run_id) == 0
