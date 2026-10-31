"""LIVE03 adapter = LIVE02 V24917 adapter + TD_CORDON writes + native prediction.

generation_design: the V24917 zonal fit on the survey observations (136 rows) is
the only TG design; the LIVE01 FISTA guidance (fixed to 120 pair rows and the
C17 budget scenario) is not used in LIVE03.  A fit error yields no candidate
(STEP1 ends with NO_PARAMETER_CANDIDATE, no write).
apply_td: donor vp.apply_td_candidates with readback (write policy checked).
"""
from __future__ import annotations
from pathlib import Path
from types import SimpleNamespace
from .common import require
from .io import write_json, mkdir
from .live02_adapter_v24917 import CordonV24917Adapter
from . import live02_v24917 as v17


class CordonLive03Adapter(CordonV24917Adapter):
    runtime_backend = 'CORDON_LIVE03_V24917_STEP1_NATIVE_PREDICTION_TD_CORDON'

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.native_prediction = dict((self.cfg.get('live03') or {}).get('native_prediction') or {})

    def generation_design(self, diag, folder):
        folder = Path(folder); mkdir(folder)
        self.design_count += 1
        require(diag.get('valid', True) and '_incidence' in diag, 'LIVE03_DESIGN_REQUIRES_VALID_CURRENT_DIAGNOSTIC')
        placeholder = SimpleNamespace(rows=[], family_summaries=[{'family': 'NONE', 'converged': True,
                                                                  'method': 'LIVE03_NO_PARENT_FISTA'}])
        context = {'projection': placeholder, 'method': self.evaluator.method,
                   'parent_design': 'NONE_LIVE03_ZONAL_FIT_ONLY'}
        context = v17.targeted_design(self, diag, folder, context)
        fams = list(getattr(context['projection'], 'family_summaries', []) or [])
        # Donor apply_generation/STEP1 read context['result'].converged: here it is the
        # convergence (or monotone improvement) of the V24917 zonal fit that produced the rows.
        context['result'] = SimpleNamespace(converged=bool(fams) and all(f.get('converged') for f in fams),
                                            source='LIVE03_V24917_ZONAL_FIT')
        self.v24917_counts['designs'] += 1
        if (context.get('v24917') or {}).get('status') == 'FIT_FALLBACK_PARENT_PROPOSAL':
            self.v24917_counts['fit_fallbacks'] += 1
        write_json(folder / 'LIVE03_GENERATION_DESIGN.json', {'status': (context.get('v24917') or {}).get('status'),
                   'rows': len(getattr(context['projection'], 'rows', []) or [])})
        return context
