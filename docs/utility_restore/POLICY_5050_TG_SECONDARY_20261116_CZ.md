# GENERATION: sekundární limit 2 %; TD: váhy 50/50

Základ: `f79566170d2dc15f909621f194cc588ec05a794b`, včetně opravy přesné
kontroly TD vůči okamžitému nativnímu readbacku a dřívější opravy refitu.

## Nové nastavení

V `CORDON_LIVE04_CONFIG.json` a jeho vydané výchozí kopii:

```json
"acceptance": {
  "secondary_max_relative_degradation": 0.0,
  "generation_secondary_max_relative_degradation": 0.02
},
"td_cordon": {
  "idp_objective_weight": 0.5
}
```

Samostatný limit GENERATION platí pro predikční brány i plný živý pokus.
EXACT_TWO_HITS se smí zhoršit nejvýše o 2 % oproti bezprostřednímu rodiči.
Předchozí naměřený případ 26631,0091 → 27145,0171 (+1,9301 %) tak splní
tuto konkrétní kontrolu. Výsledek celého nového pokusu dál závisí na
hlavním cíli, GEH/severity, mobilitě, LONG a ostatních stávajících branách.

Limit má vlastní klíč, aby se změna vztahovala jen na GENERATION.
SupplyMix dál používá původní nulové povolené zhoršení sekundární metody.
TD si zachovává samostatnou hranici 1 % pro zhoršení hlavního i sekundárního
kordónového cíle při směsné akceptaci. Starší uživatelská konfigurace bez
nového klíče zachovává svou původní společnou hranici.

Pro TD se stejná nová váha používá při vnitřním hledání i finální akceptaci:

`F = 0,50 × Q_po / Q_rodič + 0,50 × J_IDP_po / J_IDP_rodič`.

Q je dosavadní hlavní kordónové kritérium: vážená kvadratická chyba intenzit
po započtení tolerančního pásma. GEH se dál počítá a kontroluje ve stávajících
profilových a severity pojistkách. J_IDP je součet komponentních FineCDF
ztrát `RMSE² + 0,25 × relativní chyba průměrné délky²`.
Poměry vnější akceptace se vztahují k rodiči TD bloku. Vnitřní postup
vyhodnocuje jednotlivé kroky vůči svému aktuálnímu středu hledání a dál
hlídá celkové povolené zhoršení vůči začátku bloku.

Požadované zlepšení F zůstává alespoň 0,1 %, tedy `F ≤ 0,999`.
Native IDP guard, GEH/severity, mobilita, LONG, readback a rollback zůstávají
aktivní. Změna vah ani sekundárního limitu nemění koeficienty otevřeného
modelu sama o sobě.

## Ověření a použití

Testy v `tests/test_live04_acceptance_5050.py` ověřují konkrétní dříve
odmítnutý případ, inkluzivní hranici 2 %, odmítnutí překročení limitu,
zachování ostatních bloků a bran, validaci konfigurace, její předání adaptéru
a shodu normalizovaného cíle 50/50 při hledání a akceptaci.
Aktualizované stávající TD testy ověřují stejné nové váhy v komponentním
vyhledávání. Výsledky jsou v `evidence/policy_5050_20261116/`.

Použít celý nový balík pro další běh. Aktivní `CORDON_LIVE04_CONFIG.json`
musí pocházet z tohoto balíku. Ve Visumu spustit obvyklý
`RUN_R1_2025_CORDON_LIVE04_V7_TG_TD_CYCLE.py` po restartu hostitele.
Živý Visum zde nebyl spuštěn; offline testy jsou syntetické.
