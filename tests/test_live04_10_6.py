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


def test_supplymix_is_due_only_every_second_cycle():
    cfg = load_config()
    plans = {o: planned_blocks(cfg, o) for o in (1, 2, 3, 4)}
    assert 'SUPPLY_ADDVAL1' not in plans[1] and 'SUPPLY_ADDVAL1' in plans[2]
    assert 'SUPPLY_ADDVAL1' not in plans[3] and 'SUPPLY_ADDVAL1' in plans[4]


def _reject_everything(monkeypatch):
    from cordon2025.live03_evaluation import Live03Evaluator
    orig = Live03Evaluator.block_gate

    def gate(self, blk, before, after, rows):
        d = orig(self, blk, before, after, rows)
        d['accepted'] = False; d.setdefault('reasons', []).append('TEST_FORCED_REJECTION')
        return d
    monkeypatch.setattr(Live03Evaluator, 'block_gate', gate)


def test_unchanged_cycle_without_supplymix_does_not_stop_the_run(tmp_path, monkeypatch):
    """Cycle 1 (no SupplyMix due) without a change used to end the run; now the run goes on
    until SupplyMix has also run without a change (cycle 2), then stops."""
    _reject_everything(monkeypatch)
    v = Live04Visum(tmp_path / 'model')
    r = run(v, output_root=tmp_path / 'runs', options=OPT,
            config_overrides={'max_cycles': 6, 'blocks_per_cycle': ['GENERATION'], 'td_cordon': {'enabled': False},
                              'write_policy': {'td_parameter_writes': False},
                              'generation_search': {'max_trials': 1}})
    f = list((tmp_path / 'runs').glob('LIVE04_TGTD_*'))[0]
    prog = read_json(f / 'CYCLE_PROGRESS.json')
    names = [[b['block'] for b in c['blocks']] for c in prog['cycles']]
    assert names == [['GENERATION'], ['GENERATION', 'SUPPLY_ADDVAL1']]
    assert prog['stop_reason'] == 'NO_CHANGE_IN_ANY_BLOCK_SINCE_LAST_ACCEPTED_CHANGE'
    assert prog['unchanged_since_last_change'] == ['GENERATION', 'SUPPLY_ADDVAL1']
    assert r['accepted_by_block'] == {}
