"""The bounded route pair search must keep the old exhaustive ordering."""
import random

from cordon2025.live04_supply import _top_route_pairs


def _routes(prefix, volumes):
    routes = [{'pk': (prefix, i), 'volume': float(v)} for i, v in enumerate(volumes)]
    return sorted(routes, key=lambda r: (-r['volume'], r['pk']))


def _exhaustive(on, off, limit):
    return sorted(((a, b) for a in on for b in off),
                  key=lambda p: (-p[0]['volume'] * p[1]['volume'], p[0]['pk'], p[1]['pk']))[:limit]


def test_top_pairs_matches_exhaustive_with_ties_and_sparse_limits():
    rng = random.Random(20261117)
    for n_on in range(1, 17):
        for n_off in range(1, 17):
            on = _routes('on', [rng.choice((0.1, 0.5, 1.0, 2.0, 4.0)) for _ in range(n_on)])
            off = _routes('off', [rng.choice((0.1, 0.5, 1.0, 2.0, 4.0)) for _ in range(n_off)])
            for limit in (0, 1, 2, 7, 128, n_on * n_off + 1):
                assert _top_route_pairs(on, off, limit) == _exhaustive(on, off, limit)


def test_top_pairs_stays_bounded_for_large_market():
    on = _routes('on', range(10000, 0, -1))
    off = _routes('off', range(10000, 0, -1))
    result = _top_route_pairs(on, off, 128)
    assert len(result) == 128
    assert result[0] == (on[0], off[0])
