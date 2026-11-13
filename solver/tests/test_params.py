import pytest

from solver.evaluate import Weights
from solver.ga import GAParams
from solver.params import ParamsError, params_to_dict, parse_params


def test_defaults():
    ga, w = parse_params({})
    assert ga == GAParams() and w == Weights()
    assert parse_params(None) == (GAParams(), Weights())


def test_partial_override():
    ga, w = parse_params({"ga": {"generations": 50, "time_limit": 30}, "weights": {"S2": 3}})
    assert ga.generations == 50 and ga.time_limit == 30 and ga.pop_size == GAParams().pop_size
    assert w.S2 == 3 and w.hard == Weights().hard


def test_roundtrip_full_dict():
    full = params_to_dict(GAParams(seed=7), Weights(S8=2))
    assert parse_params(full) == (GAParams(seed=7), Weights(S8=2))


@pytest.mark.parametrize("raw, needle", [
    ({"ga": {"pop": 10}}, "pop"),                         # gõ sai tên
    ({"ga": {"generations": -1}}, "generations"),
    ({"ga": {"crossover_rate": 1.5}}, "crossover_rate"),
    ({"weights": {"S3": 1}}, "S3"),                       # S3 đã bỏ
    ({"weights": {"hard": 0}}, "hard"),
    ({"ga": {"pop_size": 4, "elite": 4}}, "elite"),
    ({"ga": {"pop_size": 2, "tournament_k": 3}}, "tournament_k"),
    ({"seed": 1}, "seed"),                                # phải nằm trong "ga"
])
def test_rejects_invalid(raw, needle):
    with pytest.raises(ParamsError) as e:
        parse_params(raw)
    assert needle in str(e.value)
