# Aggressive OFFLINE API

Standard `solve`, `build_from_snapshot`, `aggregate_observations` and
`parent_projection` APIs remain available. Parent bytecode sources are unchanged.

```python
from pathlib import Path
from cordon2025.common import ROOT, read_config
from cordon2025.aggressive import propose, td_trial_plan, incidence_state_hash
cfg = read_config(ROOT / "CORDON_2025_AGGRESSIVE_CONFIG.json", outer_cycle=1)
proposal = propose(incidence, cfg, budget=None, basis=None, zone_rows=None,
                   allow_unapproved_scenario=True)
proposal.save(Path("NEW_RUN"), incidence)
```

`incidence` must come from the existing validated SQLite reader, with explicit
mutable/fixed metadata. Real data require deliberate scenario authorization.
`basis=None` leaves actual realizability unverified, never certified.

An `ActuatorBasis` uses the existing `cordon2025.feasibility` contract and must
cover the full OD universe, including collateral/frozen rows. Zero influence
on all frozen rows is mandatory. Add `state_hash=incidence_state_hash(incidence)`
and a source SHA256 to its evidence. A supplied exact-synthetic response is not
a real-model Jacobian. Allowed columns remain WORK/SERVICE TG_PARAMETER or
TD_PARAMETER. TG columns also require `step_kind`: ADD_LOG, FAMILY_GLOBAL_LOG,
or SALARY_ABSOLUTE. Stage limits INTERSECT supplied hard bounds, never widen them.

Optional `zone_rows` is an explicit export of zone attributes, with zone_no,
NOT_ZAHR and, where relevant, ADD_PROD_W, ADD_ATT_W, ADD_PROD_S, ADD_ATT_S,
ADD_SALARY, AV_INCOME and reference columns used by the parent design routine.
Do not fill missing real attributes with fabricated ones. CSV input is provided
through --zone-parameters. It is provenance-hashed and never read from live COM.
Parent design diagnostics may retain legacy labels for live coefficient
sources; the wrapper explicitly labels this as EXPLICIT_ZONE_SNAPSHOT_NOT_LIVE_VISUM.
A parameter design is not proof of full OD realization.

`td_trial_plan(incidence, cfg, basis, parameter_direction, component_losses=None)`
requires a TD-only, state-matched local response. It evaluates seven scaled
parameter trials. `component_losses` maps each scale to before/after dictionaries
and a selected component list. Missing native losses/IPF proof never yields
native acceptance. This API neither runs IPF nor writes any parameter.

`effective_config` seals derived stage fields and checks their source identities.
To choose a different stage, resolve the original raw config again. Do not edit
a sealed effective config or reuse a checkpoint under another stage identity.

Standard V2 IO/session APIs are retained. The aggressive run adds the pinned
source-policy/design hashes and an objective-scenario hash including C17 budgets.
