# Vypnuti / navrat

Originalni RUN_CORDON_2025_CAPTURE.py, cordon_visum_bootstrap.py a visum_startup.py
nebyly zmeneny. Spusteni originalniho skriptu aktivuje puvodni export, ne FAST.
Scoped overlay je instalovan jen po novem explicitnim launcheru a obnoven v
finally i pri chybe. Neni potreba znovu instalovat profilovy model 2022.

PATCH installer pouze vytvari novou vystupni slozku s exaktnim base guardem.
Nic neprepise in-place. Rollback znamena znovu pouzit puvodni slozku PERF01.
Selhava-li FAST kvuli datum, nesmi se to obejit prohlasenim LEGACY PASS.
Pri technicke nekompatibilite PTV lze provest novy LEGACY beh do nove slozky
pro dukaz a srovnani. Stary partial p.sqlite nikdy neadoptovat.
