"""Giải thuật di truyền (memetic) cho giai đoạn 1: xếp tuần mẫu.

Nhiễm sắc thể (schedule.py): lecturer[lớp-môn] + start[buổi]. Fitness = evaluate() (chỉ có điểm phạt,
càng nhỏ càng tốt). Vòng lặp mỗi thế hệ:

    elite      giữ nguyên `elite` cá thể tốt nhất
    chọn lọc   tournament: bốc ngẫu nhiên k cá thể, lấy cá thể fitness nhỏ nhất làm bố/mẹ
    lai ghép   theo khối lớp sinh viên: với mỗi lớp, con lấy toàn bộ lịch + giảng viên các môn của lớp đó
               từ bố HOẶC mẹ. Giữ nguyên cấu trúc bên trong một lớp (không tạo trùng giờ trong lớp),
               xung đột mới chỉ có thể phát sinh giữa các lớp (giảng viên, phòng)
    đột biến   1..mutation_max thao tác ngẫu nhiên: dời một buổi / đổi chỗ hai buổi cùng lớp cùng độ dài /
               đổi giảng viên của một lớp-môn
    cục bộ     (memetic) sửa xung đột bằng min-conflicts rồi cải thiện mềm `ls_steps` bước (localsearch.py)
    chấm điểm  evaluate() thật trên lịch con

Dừng khi đủ số thế hệ, hết thời gian, `stagnation` thế hệ liền không cải thiện cá thể tốt nhất,
hoặc `should_stop()` trả về True (worker: job bị huỷ / worker tắt), kiểm tra sau mỗi thế hệ.
"""

from __future__ import annotations

import time
from dataclasses import asdict, dataclass, field
from typing import Callable

import numpy as np

from .dsatur import dsatur
from .evaluate import Evaluation, Weights, evaluate
from .localsearch import Workspace, improve, repair
from .problem import Problem
from .schedule import Schedule, random_schedule


@dataclass
class GAParams:
    pop_size: int = 30
    generations: int = 200
    elite: int = 2
    tournament_k: int = 3
    crossover_rate: float = 0.8
    mutation_max: int = 3          # số thao tác đột biến tối đa mỗi con
    local_search: bool = True      # memetic: sửa xung đột + cải thiện mềm cho mỗi con
    ls_steps: int = 150            # số bước cải thiện mềm mỗi con
    repair_steps: int = 300        # số bước min-conflicts tối đa mỗi con
    init_ls_steps: int = 500       # số bước cải thiện mềm cho cá thể ban đầu
    seed_dsatur: int = 1           # số cá thể ban đầu lấy từ DSatur (còn lại: ngẫu nhiên + sửa)
    stagnation: int = 60           # dừng nếu bấy nhiêu thế hệ không cải thiện
    time_limit: float | None = None  # giây
    seed: int = 0

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class Individual:
    schedule: Schedule
    evaluation: Evaluation

    @property
    def fitness(self) -> float:
        return self.evaluation.fitness


@dataclass
class GAResult:
    best: Individual
    history: list[dict] = field(default_factory=list)   # mỗi thế hệ: generation, best, avg, hard, elapsed_ms
    generations: int = 0
    elapsed: float = 0.0
    stop_reason: str = ""


ProgressFn = Callable[[dict], None]
StopFn = Callable[[], bool]
STOPPED = "bị dừng từ bên ngoài"


class GA:
    def __init__(self, problem: Problem, params: GAParams | None = None, weights: Weights | None = None):
        self.p = problem
        self.params = params or GAParams()
        self.w = weights or Weights()
        self.rng = np.random.default_rng(self.params.seed)
        # Buổi theo lớp, dùng cho đột biến đổi chỗ
        self.class_events = [np.flatnonzero(problem.ev_class == c) for c in range(problem.n_classes)]

    # --- cá thể ------------------------------------------------------------------

    def _finish(self, schedule: Schedule, ls_steps: int) -> Individual:
        """Áp tìm kiếm cục bộ (nếu bật) rồi chấm điểm thật."""
        if self.params.local_search:
            ws = Workspace(self.p, schedule, self.w)
            repair(ws, self.rng, max_steps=self.params.repair_steps)
            if ls_steps:
                improve(ws, self.rng, steps=ls_steps)
                repair(ws, self.rng, max_steps=self.params.repair_steps)
            schedule = ws.schedule()
        return Individual(schedule, evaluate(self.p, schedule, self.w))

    def initial_population(self) -> list[Individual]:
        prm = self.params
        pop = []
        for i in range(min(prm.seed_dsatur, prm.pop_size)):
            pop.append(self._finish(dsatur(self.p, np.random.default_rng(prm.seed * 1000 + i)), prm.init_ls_steps))
        while len(pop) < prm.pop_size:
            pop.append(self._finish(random_schedule(self.p, self.rng), prm.init_ls_steps))
        return pop

    # --- toán tử -----------------------------------------------------------------

    def tournament(self, pop: list[Individual]) -> Individual:
        idx = self.rng.choice(len(pop), size=self.params.tournament_k, replace=False)
        return min((pop[i] for i in idx), key=lambda ind: ind.fitness)

    def crossover(self, a: Schedule, b: Schedule) -> Schedule:
        """Lai ghép theo khối lớp: mỗi lớp lấy nguyên lịch + giảng viên từ một trong hai bố mẹ.

        Sinh viên học lại nối lớp này với lớp khác (H10), nên ghép hai lớp từ hai bố mẹ khác nhau có thể sinh trùng
        lịch sinh viên; min-conflicts trong _finish sửa phần đó. Không gom các lớp bị nối thành một khối: trên dữ liệu
        mẫu gần như mọi lớp dính vào cùng một khối (large: 73/76 lớp), lai ghép theo khối khi đó không còn tác dụng.
        """
        from_b = self.rng.random(self.p.n_classes) < 0.5
        ev_mask, sec_mask = from_b[self.p.ev_class], from_b[self.p.sec_class]
        return Schedule(np.where(sec_mask, b.lecturer, a.lecturer), np.where(ev_mask, b.start, a.start))

    def mutate(self, s: Schedule) -> Schedule:
        p, rng = self.p, self.rng
        s = s.copy()
        for _ in range(int(rng.integers(1, self.params.mutation_max + 1))):
            op = rng.random()
            if op < 0.5:                                           # dời một buổi
                e = int(rng.integers(p.n_events))
                s.start[e] = rng.choice(p.ev_domain(e))
            elif op < 0.8:                                         # đổi chỗ hai buổi cùng lớp, cùng độ dài
                c = int(rng.integers(p.n_classes))
                evs = self.class_events[c]
                e1 = int(rng.choice(evs))
                same = evs[(p.ev_len[evs] == p.ev_len[e1]) & (evs != e1)]
                if len(same):
                    e2 = int(rng.choice(same))
                    s.start[e1], s.start[e2] = s.start[e2], s.start[e1]
            else:                                                  # đổi giảng viên
                sec = int(rng.integers(p.n_sections))
                s.lecturer[sec] = rng.choice(p.sec_candidates[sec])
        return s

    # --- vòng lặp ----------------------------------------------------------------

    def run(self, on_progress: ProgressFn | None = None, should_stop: StopFn | None = None) -> GAResult:
        prm = self.params
        t0 = time.perf_counter()
        pop = sorted(self.initial_population(), key=lambda ind: ind.fitness)
        best = pop[0]
        result = GAResult(best=best)
        since_improve = 0

        def record(gen: int) -> None:
            fits = np.array([ind.fitness for ind in pop])
            row = {"generation": gen, "best_fitness": float(best.fitness), "avg_fitness": float(fits.mean()),
                   "hard_violations": int(best.evaluation.hard_total),
                   "elapsed_ms": int((time.perf_counter() - t0) * 1000)}
            result.history.append(row)
            if on_progress:
                on_progress(row)

        record(0)
        gen = 0
        result.stop_reason = "đủ số thế hệ"
        for gen in range(1, prm.generations + 1):
            if should_stop and should_stop():
                result.stop_reason = STOPPED
                gen -= 1
                break
            children = [pop[i] for i in range(min(prm.elite, len(pop)))]
            while len(children) < prm.pop_size:
                a, b = self.tournament(pop), self.tournament(pop)
                child = (self.crossover(a.schedule, b.schedule) if self.rng.random() < prm.crossover_rate
                         else a.schedule.copy())
                children.append(self._finish(self.mutate(child), prm.ls_steps))
            pop = sorted(children, key=lambda ind: ind.fitness)

            if pop[0].fitness < best.fitness - 1e-9:
                best, since_improve = pop[0], 0
            else:
                since_improve += 1
            record(gen)

            if since_improve >= prm.stagnation:
                result.stop_reason = f"{prm.stagnation} thế hệ không cải thiện"
                break
            if prm.time_limit is not None and time.perf_counter() - t0 >= prm.time_limit:
                result.stop_reason = "hết thời gian"
                break

        result.best = best
        result.generations = gen
        result.elapsed = time.perf_counter() - t0
        return result


def run_ga(problem: Problem, params: GAParams | None = None, weights: Weights | None = None,
           on_progress: ProgressFn | None = None, should_stop: StopFn | None = None) -> GAResult:
    return GA(problem, params, weights).run(on_progress, should_stop)
