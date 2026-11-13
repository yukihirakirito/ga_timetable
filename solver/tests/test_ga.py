from pathlib import Path

import numpy as np
import pytest

from solver.ga import GA, GAParams, run_ga
from solver.problem import load_snapshot
from solver.schedule import domain_errors, random_schedule

SEEDS = Path(__file__).resolve().parents[2] / "db" / "seeds"
FAST = dict(pop_size=6, generations=4, ls_steps=30, init_ls_steps=100, seed_dsatur=1)


@pytest.fixture(scope="module")
def small():
    return load_snapshot(SEEDS / "small.snapshot.json")


def test_crossover_keeps_whole_classes(small):
    p = small
    ga = GA(p, GAParams(seed=0))
    a, b = random_schedule(p, np.random.default_rng(1)), random_schedule(p, np.random.default_rng(2))
    child = ga.crossover(a, b)
    for c in range(p.n_classes):
        ev = p.ev_class == c
        sec = p.sec_class == c
        from_a = np.array_equal(child.start[ev], a.start[ev]) and np.array_equal(child.lecturer[sec], a.lecturer[sec])
        from_b = np.array_equal(child.start[ev], b.start[ev]) and np.array_equal(child.lecturer[sec], b.lecturer[sec])
        assert from_a or from_b, f"lớp {c} bị trộn giữa hai bố mẹ"


def test_mutation_stays_in_domain(small):
    ga = GA(small, GAParams(seed=0, mutation_max=5))
    s = random_schedule(small, np.random.default_rng(0))
    for _ in range(100):
        s = ga.mutate(s)
    assert domain_errors(small, s) == []


def test_ga_result_is_valid_and_best_never_gets_worse(small):
    res = run_ga(small, GAParams(seed=0, **FAST))
    assert domain_errors(small, res.best.schedule) == []
    assert res.best.evaluation.hard_total == 0
    best = [row["best_fitness"] for row in res.history]
    assert all(x >= y for x, y in zip(best, best[1:])), "elitism: cá thể tốt nhất không được tệ đi"
    assert [row["generation"] for row in res.history] == list(range(res.generations + 1))


def test_ga_is_deterministic_for_same_seed(small):
    a = run_ga(small, GAParams(seed=5, **FAST))
    b = run_ga(small, GAParams(seed=5, **FAST))
    assert a.best.fitness == b.best.fitness
    assert np.array_equal(a.best.schedule.start, b.best.schedule.start)


def test_pure_ga_without_local_search_runs(small):
    res = run_ga(small, GAParams(seed=0, local_search=False, pop_size=8, generations=5, seed_dsatur=0))
    assert domain_errors(small, res.best.schedule) == []
    assert res.generations == 5


def test_stops_on_stagnation(small):
    res = run_ga(small, GAParams(seed=0, pop_size=4, generations=500, ls_steps=0, init_ls_steps=0,
                                 seed_dsatur=0, stagnation=3, local_search=False))
    assert res.generations < 500
    assert "không cải thiện" in res.stop_reason
