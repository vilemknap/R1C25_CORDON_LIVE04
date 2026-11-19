"""LIVE04.10.6: overnight defaults - max_cycles 100 and a stop rule that waits for SupplyMix.
Synthetic mock only - not native PTV Visum evidence."""
from fake_live04 import Live04Visum
from cordon2025.common import ROOT, read_json
from cordon2025.live04_config import load_config
from cordon2025.live04_cycle import run, planned_blocks

OPT = {'min_free_disk_gib': 0, 'com_retry_initial_delay_seconds': 0., 'com_retry_max_delay_seconds': 0.}


def test_release_default_runs_100_cycles():
    cfg = load_config()
    assert cfg['max_cycles'] == 100 and cfg['stop_after_cycle_without_change'] is True
    assert read_json(ROOT / 'provenance/live04_user_config/CORDON_LIVE04_CONFIG.RELEASE_DEFAULT.json')['max_cycles'] == 100


def test_supplymix_is_due_every_fourth_cycle():
    """User decision 2026-11-19: SupplyMix in cycles 4, 8, 12 ... (v7 default: every 2nd from 2)."""
    cfg = load_config()
    due = [o for o in range(1, 14) if 'SUPPLY_ADDVAL1' in planned_blocks(cfg, o)]
    assert due == [4, 8, 12]
    import pytest
    from cordon2025.common import ContractError
    with pytest.raises(ContractError, match='LIVE04_V7_SUPPLYMIX_CADENCE:sp_every_n_cycles'):
        load_config(overrides={'v7': {'run_options': {'sp_every_n_cycles': 2}}})


def _reject_everything(monkeypatch):
    from cordon2025.live03_evaluation import Live03Evaluator
    orig = Live03Evaluator.block_gate

    def gate(self, blk, before, after, rows):
        d = orig(self, blk, before, after, rows)
        d['accepted'] = False; d.setdefault('reasons', []).append('TEST_FORCED_REJECTION')
        return d
    monkeypatch.setattr(Live03Evaluator, 'block_gate', gate)


def test_unchanged_cycle_without_supplymix_does_not_stop_the_run(tmp_path, monkeypatch):
    """Cycles without SupplyMix due and without a change do not end the run; it goes on
    until SupplyMix has also run without a change (cycle 4 since 2026-11-19), then stops."""
    _reject_everything(monkeypatch)
    v = Live04Visum(tmp_path / 'model')
    r = run(v, output_root=tmp_path / 'runs', options=OPT,
            config_overrides={'max_cycles': 6, 'blocks_per_cycle': ['GENERATION'], 'td_cordon': {'enabled': False},
                              'write_policy': {'td_parameter_writes': False},
                              'generation_search': {'max_trials': 1}})
    f = list((tmp_path / 'runs').glob('LIVE04_TGTD_*'))[0]
    prog = read_json(f / 'CYCLE_PROGRESS.json')
    names = [[b['block'] for b in c['blocks']] for c in prog['cycles']]
    assert names == [['GENERATION'], ['GENERATION'], ['GENERATION'], ['GENERATION', 'SUPPLY_ADDVAL1']]
    assert prog['stop_reason'] == 'NO_CHANGE_IN_ANY_BLOCK_SINCE_LAST_ACCEPTED_CHANGE'
    assert prog['unchanged_since_last_change'] == ['GENERATION', 'SUPPLY_ADDVAL1']
    assert r['accepted_by_block'] == {}
