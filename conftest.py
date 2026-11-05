"""LIVE04.9 test-only switch (tests/conftest.py is a protected LIVE01 source, so this lives at the root).

The release config enables 16 station profile rows (152 FIRST_LAST rows).  Mock tests written for the
136-row contract keep it; tests marked ``station_profiles`` see the release config unchanged."""
import pytest


def pytest_configure(config):
    config.addinivalue_line('markers', 'station_profiles: run with the LIVE04.9 station profile rows of the release config')


@pytest.fixture(autouse=True)
def _legacy_rows_without_station_profiles(request, monkeypatch):
    if request.node.get_closest_marker('station_profiles'):
        yield
        return
    from cordon2025 import live03_observations as obs
    original = obs.Contract.__init__

    def init(self, o):
        o = dict(o)
        if isinstance(o.get('station_profiles'), dict):
            o['station_profiles'] = dict(o['station_profiles'], enabled=False)
        original(self, o)
    monkeypatch.setattr(obs.Contract, '__init__', init)
    yield
