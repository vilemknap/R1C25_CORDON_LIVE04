# V2.4.9.16 – audit FlowBundle/skim donoru a návrh integrace

## Identita

- parent: `R1_15A2_V2_4_9_15_COM_BUSY_RETRY_SAFE_FINALIZER_20261019`
- parent ZIP SHA-256: `5ba9c2baec1c433534c9aac49d92cb8f450f12f8a78d1f9f1db82cc5987ba716`
- donor: `R1_15A2_V2_4_9_DEMAND_EVIDENCE_COEFFICIENT_ROLLBACK_20261017`
- donor ZIP SHA-256: `d5107cb7814a903f8001d36aca903701a164885d7bf225d778678f878486184a`
- navržený release: `R1_15A2_V2_4_9_16_FLOWBUNDLE_SKIM_TARGETING_REBASE_20261019`

Donor V2.4.9 není merge parent. Přenášejí se pouze jednotlivé ověřené principy a moduly na současný strom V2.4.9.15.

## Verdikt auditu

V2.4.9 správně implementuje jádro demand-evidence targetingu:

- path incidence zůstává numerickou autoritou;
- FlowBundle je targeting/evidence;
- přesné DIRECTED a BOTH scope;
- CAL-only underload WORK/SERVICE driver selection;
- NATIVE-only TG targeting;
- DIST_KM/11D TD targeting;
- candidate-induced unsupported OD znamená reject + rollback bez okamžité enumerace;
- full TG+TD coefficient ledger rollback;
- Supply zůstává beze změny.

Není však úplným přenosem historického řetězce 15A/15C/15D. Chybí nebo jsou jen částečné:

- skutečná EXOG_EE diagnostická extrakce;
- OD-level FlowBundle/path parity;
- skim suite TT0/TTC/IMP/DIS/DID/AD1/VP0/VPC;
- 15D supply/block classifier;
- shortest-IMP path-epoch validity oracle;
- retry-safe a bezchybový produkční FlowBundle COM kontrakt;
- kompatibilita target damping se signed Generation V24915;
- live Visum certifikace.

## Zásadní rebase pravidlo

Nekopírovat:

- starý `r1_15a2_overnight_controller_v249.py`;
- starý `r1_15a2_finecdf_bridge_v249.py`;
- starý launcher ani safety gate.

Ty vycházejí z V2489/V18 a přepsaly by pozdější V2490, V24912, V24914 a V24915 změny.

## Navržené moduly

1. `r1_15a2_flowbundle_v24916.py`
   - zapečetěná COM signatura;
   - transient-only retry;
   - přesný směrový scope;
   - per-profile fallback;
   - NATIVE targeting a volitelná EXOG diagnostika.

2. `r1_15a2_skim_v24916.py`
   - povinný `R1_OSRM_DIST_KM`;
   - volitelné read-only TT0/TTC/IMP/DIS/DID/AD1/VP0/VPC;
   - žádné automatické počítání skimů;
   - chybějící volitelné skimy nejsou fatal.

3. `r1_15a2_demand_evidence_v24916.py`
   - total parity;
   - OD-distribution parity;
   - signed-safe TG targeting;
   - WORK/SERVICE TD mask;
   - state-bound manifest.

4. `r1_15a2_trial_adapter_v24916.py`
   - subclass současného V243;
   - evidence se staví jednou pro accepted state;
   - path incidence a acceptance se nemění.

5. `r1_15a2_finecdf_bridge_v24916.py`
   - vznikne ze současného bridge V242/V19;
   - přenese pouze active-component mask hook;
   - všechny globální 11D metriky zůstávají aktivní.

6. `r1_15a2_overnight_controller_v24916.py`
   - vznikne ze současného V24915 controlleru;
   - pouze explicitní hooky `td_target_plan` a `candidate_support_risk`;
   - žádný monkey-patch starého helper modulu.

7. `r1_15a2_coefficient_ledger_v24916.py` a `r1_15a2_inplace_transaction_v24916.py`
   - celý TG+TD vektor;
   - současná zone index cache, COM retry a readback tolerance;
   - Supply rollback delegován současnému V239.

8. launcher/config/safety/runtime manifest pro V24916.

## FlowBundle COM kontrakt

Produkční runtime nebude zkoušet desítky overloadů. Předem se live ověří a poté se zapečetí:

```python
fb.Clear()
fb.DemandSegments = dseg_code
fb.CreateCondition(link, None, False, False, 0, 0)
fb.ExecuteCurrentConditions()
matrix = fb.GetOrCreateFlowBundleMatrix(dseg_object)
values = matrix.GetValues()
```

Každé volání bude přes současný transient-only COM retry. Type/signature chyba se neopakuje a zůstává fail-closed nebo profile-local fallback podle fáze.

## Parity

V24916 použije dva samostatné gate:

1. `profile x DSeg` total parity;
2. `profile x DSeg x OD` distribution parity.

OD parity bude pracovat s retained FlowBundle supportem a explicitním tail bucketem, aby zkrácený export nebyl zaměněn za nesoulad.

## Signed-safe Generation

FlowBundle pochází z underload profilů. Proto:

- kladný krok na target zóně: faktor 1;
- kladný krok mimo target: tlumení;
- záporný krok: bez tlumení ve V24916;
- znaménko se nikdy nemění;
- po targetingu stále proběhne současná signed refinement, coefficient envelope, bound-constrained projection a P/A rebalance.

## Skimy

V24916 aktivně používá jen DIST_KM pro TD targeting. Ostatní skimy budou shadow diagnostika:

- TTC/TT0/IMP pro cost context;
- DIS/DID pro délkový kontext;
- AD1 pro supply context;
- VP0/VPC pro rychlostní kontext.

Nebudou součástí scalar objective ani hard acceptance. Skim výpočet se automaticky nepřidává do Procedure Sequence.

## Enumerace

V24916 zachová dnešní politiku:

- baseline support gap -> enumerace;
- candidate-induced unsupported OD -> reject + rollback bez okamžité enumerace;
- plateau proof -> fresh enumerace.

Cached IMP vs live shortest IMP oracle zůstane pouze diagnostický. Hard trigger a targeted augmentation patří až do následné verze po live ověření.

## Live gate

Před produkčním V24916 během musí read-only preflight potvrdit:

- COM contract bez očekávaných chyb v Messages;
- kladné NATIVE FlowBundle matice;
- DIRECTED i BOTH;
- total parity;
- OD parity;
- DIST_KM hash a zone order;
- volitelné skim inventory;
- snapshot a demand-matrix binding beze změny;
- externí Procedure Sequence script manifest/hash.

## Regrese

Mechanicky ověřeno:

- donor V2.4.9: `669 passed`;
- parent V2.4.9.15: `783 passed, 4 skipped`;
- compileall obou stromů: PASS.

V24916 musí navíc obsahovat testy pro:

- deterministic no-probe COM contract;
- transient reject retry;
- BOTH sum;
- EXOG diagnostic-only;
- total-pass/OD-fail fallback;
- negative signed TG row unchanged;
- optional skim missing fallback;
- V19 TD mask;
- no supply delta;
- external script hash gate;
- feature-off semantic equivalence s V24915.

## Provozní omezení

V24916 se nesmí hot-swapovat do právě běžícího procesu V24915. Vytvoří se jako nový release a poprvé se spustí z čistého accepted checkpointu po ukončení současného běhu.
