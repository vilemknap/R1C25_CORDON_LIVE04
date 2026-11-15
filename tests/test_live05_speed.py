"""LIVE05.6 speed-ups (TD skip, flow-bundle probe; pipelined geometry = tests/test_live04_pipeline.py). Synthetic mock only - not native PTV Visum evidence."""
from pathlib import Path

from fake_live04 import Live04Visum
from cordon2025.common import read_json
from cordon2025 import live04_cycle
from cordon2025.live04_config import load_config

OPT = {'min_free_disk_gib': 0, 'com_retry_initial_delay_seconds': 0., 'com_retry_max_delay_seconds': 0.}


def _fake(name, calls, changed_in=()):
    def make(tx, cfg):
        def block(adapter, cfg_, bdir, ctl, state, diag, anchors, reference, policy, outer_cycle=None):
            Path(bdir).mkdir(parents=True, exist_ok=True)
            calls.append((outer_cycle, name))
            return False, state, diag, None, {'status': 'NO_TD_CANDIDATE' if name == 'TD_CORDON' else 'EXHAUSTED'}
        return block
    return make


def test_td_is_skipped_for_one_cycle_after_an_unchanged_td(tmp_path, monkeypatch):
    assert load_config()['td_cordon']['skip_cycles_after_unchanged'] == 1
    calls = []
    monkeypatch.setattr(live04_cycle, 'make_generation_block', _fake('GENERATION', calls))
    monkeypatch.setattr(live04_cycle, 'make_td_block', _fake('TD_CORDON', calls))
    monkeypatch.setattr(live04_cycle, 'make_supply_block', _fake('SUPPLY_ADDVAL1', calls))
    v = Live04Visum(tmp_path / 'model')
    live04_cycle.run(v, output_root=tmp_path / 'runs', options=OPT,
                     config_overrides={'max_cycles': 5, 'stop_after_cycle_without_change': False})
    td = [o for o, n in calls if n == 'TD_CORDON']
    assert td == [1, 3, 5]
    prog = read_json(next((tmp_path / 'runs').glob('LIVE04_TGTD_*')) / 'CYCLE_PROGRESS.json')
    assert [c.get('skipped_blocks', [{}])[0].get('block') for c in prog['cycles']] == [None, 'TD_CORDON', None,
                                                                                     'TD_CORDON', None]


def test_stop_rule_still_waits_for_a_skipped_td(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(live04_cycle, 'make_generation_block', _fake('GENERATION', calls))
    monkeypatch.setattr(live04_cycle, 'make_td_block', _fake('TD_CORDON', calls))
    monkeypatch.setattr(live04_cycle, 'make_supply_block', _fake('SUPPLY_ADDVAL1', calls))
    v = Live04Visum(tmp_path / 'model')
    live04_cycle.run(v, output_root=tmp_path / 'runs', options=OPT, config_overrides={'max_cycles': 6})
    prog = read_json(next((tmp_path / 'runs').glob('LIVE04_TGTD_*')) / 'CYCLE_PROGRESS.json')
    assert prog['stop_reason'] == 'NO_CHANGE_IN_ANY_BLOCK_SINCE_LAST_ACCEPTED_CHANGE'
    assert set(prog['unchanged_since_last_change']) == {'GENERATION', 'TD_CORDON', 'SUPPLY_ADDVAL1'}


def test_skip_can_be_switched_off():
    cfg = load_config(overrides={'td_cordon': {'skip_cycles_after_unchanged': 0}})
    assert cfg['td_cordon']['skip_cycles_after_unchanged'] == 0


def test_flowbundle_probe_helpers():
    import importlib.util
    from cordon2025.common import ROOT
    spec = importlib.util.spec_from_file_location('fbprobe', ROOT / 'RUN_R1_2025_FLOWBUNDLE_PROBE.py')
    m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
    obs = m._observed_links()
    assert sum(1 for k in obs.values() if k == 'STATION') == 32 and 32 < len(obs) <= 32 + 120   # K arms may be station links
    rows = [(1.0, 2.0, 1.0, '', '', '', ''), ('', '', '', 1.0, 5.0, 10.0, 11.0), ('', '', '', 2.0, 6.0, 11.0, 12.0),
            (3.0, 4.0, 2.0, '', '', '', ''), ('', '', '', 1.0, 6.0, 11.0, 12.0)]
    assert m._routes(rows) == {(1, 2, 1): [(5, 10, 11), (6, 11, 12)], (3, 4, 2): [(6, 11, 12)]}
