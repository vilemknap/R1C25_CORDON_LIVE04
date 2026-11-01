"""v7 (vilemknap/R1_15A2_V24917_v7 @ 7b4c681) mechanics for the cordon calibrator (LIVE04).

Donor modules in parent/ are byte-identical copies from the v7 repository at
commit 7b4c681732080a28264c616daee87f7d23a8d643 (hash-pinned below, checked at
every run start; LIVE04.4 rebased them from 977cef4: Generation without CATCH_UP
and REFINE caps +/-5 %, measured zonal refit, SupplyMix 24/240/4, SEVRELAX3).  This module installs, for ONE cordon run only, everything the
v7 launcher installs that the cordon blocks use, and restores it on exit:

* demand_policy_v1.load_options -> the pinned cordon run options (no env vars);
* targeted_generation.patch_multiblock -> role-tagged coefficient references and
  the role envelopes P [0.5, 3.0] / A [0.5, 5.0], ZAHR [0.5, 10];
* boundary_pa.install (BDPA1) -> boundary rows inside the P/A rebalance and gate;
* long_school_generation.activate -> LONG/SCHOOL attributes in snapshot/rollback
  (SCHOOL TG stays fixed per AMDY, LONG TG is deferred, exactly as in v7);
* boundary_generation.activate on the configured crossings without an ADD/ZAHR
  actuator (cordon consistency rule kept from LIVE02);
* COMBUSY2 budget floor and message filter;
* the LONG post-TD mask hook on runtime_v1.execute_procseq (live04_long_mask).
"""
from __future__ import annotations
import copy
from contextlib import contextmanager
from pathlib import Path
from .common import ROOT, require, parent_module
from .io import write_json, sha256

SOURCE_REPOSITORY = 'vilemknap/R1_15A2_V24917_v7'
SOURCE_COMMIT = '7b4c681732080a28264c616daee87f7d23a8d643'
RUN_OPTIONS_PIN = 'provenance/v24917_v7/R1_RUN_OPTIONS_V24917_V7_7b4c681.json'
MODE = 'V7_7B4C681_TARGETED_STEP1_GENFIX2_SUPPLYMIX_SEVRELAX3'
# Options whose v7 value cannot be ported to the cordon objective (see docs/live04).
CORDON_DEVIATIONS = {
    'long_generation_enabled': False,     # needs the profile LONG cache incidence (long_cache)
    'long_composite_td_enabled': False,   # LONG TD is calibrated by the profile/FineCDF runner only
    'fa_enabled': False,                  # STEP1 always uses the full assignment (as in v7 STEP1)
}
# W/S P 0.5-3.0 / A 0.5-5.0 (user decision 2026-11-01, LIVE04.3) is the v7 default since
# e264314, so mg_min_ratio/mg_max_ratio are no longer cordon deviations.
DONOR_FILES = {
    'r1_15a2_zonal_count_fit_v24917.py': '43f49a80ebe807daf6b1c9d44e4894a7e50dbe1d100c58214f37eadb6299b08a',
    'r1_15a2_targeted_generation_v24917.py': '3d9dc53d5f33d633c3319608bdad58f7aa25a0bfa02cebfc5a5ba854bc0d778d',
    'r1_15a2_step_search_v24917.py': 'fec80cb36a507b2d1e40b4df74fbff1420db2ad2008939cd230d70c1fdb00664',
    'r1_15a2_boundary_generation_v24917.py': 'b437fcde80c8815a80911138665c3974e298d80e1c3ed4561a3862a931e32d5e',
    'r1_15a2_boundary_pa_v24917.py': 'a0a037a46570e34e0ff7ac85954959b90652e90e4f1e474a2a72d111c89a0958',
    'r1_15a2_long_school_generation_v24917.py': '3710e3aeca5ca5f39881d25b6838dcbdb44f42a3eb1dd353e0f494d054eb17b8',
    'r1_15a2_combusy2_v24917.py': 'ae63f5927b98acb6e18feeb40206de59dc5078c1085bf89a6b0dcb16c764c2b7',
    'r1_15a2_demand_policy_v1.py': '028894298d628c80f7dece561059c8619614aeeea07da41bf4aa443d75ec6b5e',
    'r1_15a2_perf_v24917.py': 'a2f08218e5e8931a4bb905599b8c6943b14a894dccb24c987a3032483d76ae2a',
    'r1_15a2_td_count_blend_v24917.py': 'b9f9756f3215b07b6e53bd544328df3a2fea479134def1b28309b231f37fedc4',
    'r1_15a2_mobility_guard_v24917.py': 'e079d63af6cafe7dc371689e769de0924d4c68d090ee08743a6e03803b2e5120',
    'r1_15a2_mobility_zone_v24917.py': '7d664e8022ba6e95c3a11a458edd046b412ee1b0b460ec9e05cfdd1f3b7372f4',
    'r1_15a2_long_post_td_mask_v24917.py': 'ea50a146233dbb5f0d1d554effbef5574a5c84091d4afc334f50f4f8a6b276cd',
    'r1_15a2_long_support_distance_v24917.py': '79765255b057b1f09345ce4b7ac9874cd4b1fe91a09d996ba20d4c63223c02e9',
    'r1_15a2_long_distance_guard_v24917.py': 'c98bcf5013eaab983ed8ac52f946d008e795f9ad05d9748918acef826c15bee6',
    'r1_15a2_long_profile_incidence_v24917.py': 'b86614ab75a8ccae40918a7028b2d7e0455b41a2aa2b9197ea550dc55d9329db',
    'r1_15a2_long_composite_diagnostic_v24917.py': '0378bfd4bbe245f4bc00e5c31f208b57632ce6ef5b26fd2b3fcbae57c1185ecb',
    'r1_15a2_generation_state_v24917.py': '27f3fdafb6f1ce595866455b5841cd78992a923dd59e5fc4e9ec29e56a1b7a93',
    'r1_15a2_parent_equivalence_v24917.py': '9714a9390169c6dce91ea4ace6254131fd49871e8331b25f14bc7d4277491332',
    'r1_15a2_supply_mix_v24917.py': 'e9b51daf800cf7d7ee3ede4384ce2c085099d700c23347798fd891daed51b50d',
    'r1_15a2_path_incidence_v24917.py': '3c4830a61fe3de9cb1a39a5ca8f203220a008585e1dd3f34d3dbd2dba787fb78',
}


def verify_donor_files():
    from .common import PARENT
    bad = [n for n, h in DONOR_FILES.items() if sha256(PARENT / n) != h]
    require(not bad, 'V7_DONOR_FILE_CHANGED:' + ','.join(bad))
    return dict(DONOR_FILES)


def pinned_run_options():
    from .common import read_json
    return read_json(ROOT / RUN_OPTIONS_PIN)


def run_options(cfg):
    dp = parent_module('r1_15a2_demand_policy_v1')
    return dp.validate(dict(cfg['v7']['run_options']))


def coefficient_envelope(cfg):
    env = cfg['v7']['coefficient_envelope']
    return {'PROD': [float(x) for x in env['PROD']], 'ATT': [float(x) for x in env['ATT']]}


def targeted_policy(cfg):
    """v7 DEFAULT_POLICY with the cordon's domestic W/S role envelope (hard = soft, as v7)."""
    tg = parent_module('r1_15a2_targeted_generation_v24917')
    policy = copy.deepcopy(tg.DEFAULT_POLICY)
    policy['catchup_until_model_obs_ratio'] = float(cfg['v7']['catchup_until_model_obs_ratio'])
    env = coefficient_envelope(cfg)
    policy['envelope']['domestic_hard_by_role'] = {r: list(v) for r, v in env.items()}
    policy['envelope']['refine_domestic_soft_by_role'] = {r: list(v) for r, v in env.items()}
    return tg.validate_policy(policy)


def mobility_options(cfg):
    """v7 MOBILITY2 options under the pinned run options (P band + W/S attraction fence)."""
    dp = parent_module('r1_15a2_demand_policy_v1')
    mg = parent_module('r1_15a2_mobility_guard_v24917')
    opts = run_options(cfg)
    old = dp.load_options
    try:
        dp.load_options = lambda root=None, environ=None: dict(opts)
        out = _ORIGINAL_MG_OPTIONS(mg)()
    finally:
        dp.load_options = old
    out['ws_attraction_coefficient_band'] = list(coefficient_envelope(cfg)['ATT'])
    return out


def _ORIGINAL_MG_OPTIONS(mg):
    return getattr(mg.options, '__live04_original__', mg.options)


# ------------------------------------------------------------------ scope
@contextmanager
def runtime_scope(cfg, guarded_visum, zones, actuatable_zones, folder):
    """Install the v7 runtime for ONE cordon run and restore everything after."""
    verify_donor_files()
    dp = parent_module('r1_15a2_demand_policy_v1')
    tg = parent_module('r1_15a2_targeted_generation_v24917')
    mb = parent_module('r1_15a2_multiblock')
    com = parent_module('r1_15a2_com_compat')
    rt = parent_module('r1_15a2_runtime_v1')
    lsgen = parent_module('r1_15a2_long_school_generation_v24917')
    bdgen = parent_module('r1_15a2_boundary_generation_v24917')
    bdpa = parent_module('r1_15a2_boundary_pa_v24917')
    step = parent_module('r1_15a2_step_search_v24917')
    cb = parent_module('r1_15a2_combusy2_v24917')
    perf = parent_module('r1_15a2_perf_v24917')
    from . import live02_v24917 as v17
    from .live04_long_mask import install_scoped
    opts = run_options(cfg)
    saved = {'load_options': dp.load_options, 'reference': mb._reference_coefficient,
             'hard': mb._multiplicative_coefficient_bounds, 'soft': mb._soft_multiplier_bounds,
             'refine': mb._signed_generation_refinement, 'design': mb.design_generation_candidates,
             'constrain': mb._constrain_generation_projection,
             'attrs': list(mb.GENERATION_ATTRS), 'attr_map': dict(mb.GENERATION_ATTR_MAP),
             'bd_state': copy.deepcopy(bdgen.STATE), 'bdpa_state': copy.deepcopy(bdpa._STATE),
             'step_state': copy.deepcopy(step._STATE), 'retry_budget': com._retry_budget,
             'perf_timing': copy.deepcopy(perf._STATE['timing']), 'execute': rt.execute_procseq,
             'mg_options': parent_module('r1_15a2_mobility_guard_v24917').options,
             'mg_attraction_band': parent_module('r1_15a2_mobility_guard_v24917').ATTRACTION_BAND}
    status = {'schema': 'LIVE04_V7_RUNTIME_V1', 'mode': MODE, 'source_repository': SOURCE_REPOSITORY,
              'source_commit': SOURCE_COMMIT, 'donor_files': verify_donor_files(),
              'run_options': {k: v for k, v in opts.items() if not k.startswith('_')},
              'cordon_deviations': dict(CORDON_DEVIATIONS)}
    filter_info = None
    restore_mask = None
    try:
        dp.load_options = lambda root=None, environ=None: dict(opts)
        status['multiblock_patch'] = tg.patch_multiblock(mb)
        status['bdpa'] = bdpa.install(print_fn=lambda *_: None)
        step._STATE.update(rho=None, rho_history=[], blocks=0, trials=0, kept=0, exhausted=0)
        perf._STATE['timing'] = {}
        status['long_school'] = lsgen.activate(guarded_visum)
        status['boundary'] = v17.activate_boundary({'v24917': {'boundary_zone_policy': cfg['v7']['boundary_zone_policy']}},
                                                   opts, guarded_visum, zones, actuatable_zones, bdgen)
        status['mobility'] = mobility_options(cfg)
        mg = parent_module('r1_15a2_mobility_guard_v24917')
        fixed_mobility = dict(status['mobility'])

        def cordon_mobility_options():
            return dict(fixed_mobility, ws_attraction_coefficient_band=list(fixed_mobility['ws_attraction_coefficient_band']))
        cordon_mobility_options.__live04_original__ = saved['mg_options']
        mg.options = cordon_mobility_options        # every donor call sees the cordon bands
        # The donor fence also compares the band with its module constant: same value, one run only.
        mg.ATTRACTION_BAND = tuple(float(x) for x in fixed_mobility['ws_attraction_coefficient_band'])
        status['coefficient_envelope'] = coefficient_envelope(cfg)
        cb.install_budget_floor(com, float(opts['cb_max_wait_seconds']))
        filter_info = cb.install_message_filter(float(opts['cb_max_wait_seconds']))
        status['combusy2'] = {'budget_floor_seconds': float(opts['cb_max_wait_seconds']),
                              'message_filter': filter_info, 'block_retries': int(opts['cb_block_retries'])}
        if cfg['v7']['long_post_td_mask']['enabled']:
            status['long_post_td_mask'], restore_mask = install_scoped(rt)
        else:
            status['long_post_td_mask'] = {'installed': False}
        status['generation_attributes'] = list(mb.GENERATION_ATTRS)
        write_json(Path(folder) / 'V7_RUNTIME_STATUS.json', status)
        print('R1 CORDON LIVE04 v7@%s: STEP1=%s catch-up=%s P=%s A=%s LSGEN=%s BNDGEN=%s LONGMASK=%s COMBUSY2 %.0fs'
              % (SOURCE_COMMIT[:7], opts['ts_enabled'], opts['tg_catchup_enabled'],
                 [status['mobility']['lo'], status['mobility']['hi']],
                 status['mobility']['ws_attraction_coefficient_band'], status['long_school'].get('active'),
                 status['boundary'].get('active'), status['long_post_td_mask'].get('installed'),
                 float(opts['cb_max_wait_seconds'])))
        yield status
    finally:
        if restore_mask is not None:
            restore_mask()
        rt.execute_procseq = saved['execute']
        parent_module('r1_15a2_mobility_guard_v24917').options = saved['mg_options']
        parent_module('r1_15a2_mobility_guard_v24917').ATTRACTION_BAND = saved['mg_attraction_band']
        dp.load_options = saved['load_options']
        mb._reference_coefficient = saved['reference']
        mb._multiplicative_coefficient_bounds = saved['hard']
        mb._soft_multiplier_bounds = saved['soft']
        mb._signed_generation_refinement = saved['refine']
        mb.design_generation_candidates = saved['design']
        mb._constrain_generation_projection = saved['constrain']
        mb.GENERATION_ATTRS[:] = saved['attrs']
        mb.GENERATION_ATTR_MAP.clear(); mb.GENERATION_ATTR_MAP.update(saved['attr_map'])
        bdgen.STATE.clear(); bdgen.STATE.update(saved['bd_state'])
        bdpa._STATE.clear(); bdpa._STATE.update(saved['bdpa_state'])
        step._STATE.clear(); step._STATE.update(saved['step_state'])
        com._retry_budget = saved['retry_budget']
        perf._STATE['timing'] = saved['perf_timing']
        if filter_info and filter_info.get('registered'):
            try:
                import pythoncom  # type: ignore
                pythoncom.CoRegisterMessageFilter(cb._STATE.get('previous_filter'))
            except Exception:
                pass
