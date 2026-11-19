"""LIVE04.14 unit-base receipt + structural zero zones (review cc3c3c4 N2/N3).
Synthetic mock tests only; native PTV Visum validation pending."""
import json
import shutil
import sys
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fake_live04 import Live04Visum                                   # noqa: E402
from cordon2025 import live04_base_receipt as br                      # noqa: E402
from cordon2025 import live04_generation_structure as gs              # noqa: E402
from cordon2025.common import read_json                               # noqa: E402

OPT = {'min_free_disk_gib': 0, 'com_retry_initial_delay_seconds': 0., 'com_retry_max_delay_seconds': 0.}


@pytest.fixture(scope='module')
def model(tmp_path_factory):
    return Live04Visum(tmp_path_factory.mktemp('rc') / 'model')


def zones(v):
    return [int(r['NO']) for r in v.Net.Zones.rows]


def test_receipt_verifies_the_recomputed_base(model):
    out = br.verify(model, zones(model), br.read_ws(model, zones(model)))
    assert out['status'] == 'VERIFIED_RECOMPUTED_BASE' and out['receipt'].endswith(br.SUFFIX)


def test_reset_after_recompute_is_refused(model):
    """Coefficients set to 1 AFTER the recompute (step 3 skipped): stale demand would pass the unit check."""
    ws = br.read_ws(model, zones(model))
    z = next(iter(ws['ADD_ATT_W']))
    ws['ADD_ATT_W'][z] = ws['ADD_ATT_W'][z] + 0.5
    with pytest.raises(Exception, match='COEFFICIENTS_CHANGED_AFTER_RECOMPUTE'):
        br.verify(model, zones(model), ws)


def test_other_person_demand_is_refused(model):
    m = model.component[9103]
    old = np.array(m.values, copy=True)
    try:
        m.values = old + 1e-6
        with pytest.raises(Exception, match='PERSON_DEMAND_DIFFERS_FROM_RECOMPUTE:\\[9103\\]'):
            br.verify(model, zones(model), br.read_ws(model, zones(model)))
    finally:
        m.values = old


def test_receipt_is_bound_to_the_opened_file(tmp_path, model):
    src = Path(model.source)
    rec = br.path_for(src)
    # a renamed byte-identical copy finds the receipt in its folder
    copy = tmp_path / 'R1_2025_RENAMED_COPY.ver'; shutil.copy(src, copy)
    shutil.copy(rec, tmp_path / rec.name)
    model.IO.CurrentVersionFile = str(copy)
    try:
        assert br.verify(model, zones(model), br.read_ws(model, zones(model)))['status'] == 'VERIFIED_RECOMPUTED_BASE'
        copy.write_bytes(copy.read_bytes() + b'X')                  # re-saved / other model
        with pytest.raises(Exception, match='RECEIPT_MISSING_FOR_OPENED_VERSION'):
            br.verify(model, zones(model), br.read_ws(model, zones(model)))
        copy.write_bytes(src.read_bytes())
        body = json.loads((tmp_path / rec.name).read_text())
        body['person_od_matrices'][0]['sha256_float64_le'] = '0' * 64          # edited receipt
        (tmp_path / rec.name).write_text(json.dumps(body))
        with pytest.raises(Exception, match='SEAL_BROKEN'):
            br.verify(model, zones(model), br.read_ws(model, zones(model)))
    finally:
        model.IO.CurrentVersionFile = str(src)


def test_run_without_receipt_stops_before_the_reference(tmp_path):
    from cordon2025.live04_cycle import run
    v = Live04Visum(tmp_path / 'model', base_receipt=False)
    over = {'blocks_per_cycle': ['GENERATION'], 'td_cordon': {'enabled': False},
            'write_policy': {'td_parameter_writes': False}, 'max_cycles': 1}
    with pytest.raises(Exception, match='LIVE04_BASE_RECEIPT_MISSING_FOR_OPENED_VERSION'):
        run(v, output_root=tmp_path / 'runs', options=OPT, config_overrides=over)
    assert not list((tmp_path / 'runs').glob('LIVE04_TGTD_*/GENSTRUCT1_REFERENCE.json'))


def test_structural_zero_zones_are_exempt_and_keep_target_zero():
    zs = [1, 2, 3, 646]
    one = np.ones(4); coef = {k: one.copy() for k in gs.GROUPS}
    for k in gs.GROUPS:
        coef[k][3] = 0.0
    pop = np.array([10., 20., 0., 0.]); fp = {f: np.array([5., 5., 0., 0.]) for f in gs.FAMILIES}
    struct = gs.structural_zero_mask(pop, fp, coef)
    assert list(struct) == [False, False, False, True]
    dom = np.ones(4, dtype=bool)
    ok = gs.unit_start_check(zs, coef, zs, dom, 'REQUIRE_UNIT_WS_ON_ACTUATABLE_DOMESTIC_ZONES', structural=struct)
    assert ok['status'] == 'PROVEN_UNIT_BASE' and ok['structural_zero_zones'] == [646] and ok['checked_zones'] == 3
    # 0 with a generation base is NOT structural -> still a failure
    pop[3] = 5.0
    with pytest.raises(Exception, match='NOT_A_UNIT_BASE'):
        gs.unit_start_check(zs, coef, zs, dom, 'REQUIRE_UNIT_WS_ON_ACTUATABLE_DOMESTIC_ZONES',
                            structural=gs.structural_zero_mask(pop, fp, coef))
