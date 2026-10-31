# Agresivni kordonova vetev - audit A00

Vychozi kordon V2 je oddeleny od profiloveho spoustece. Srovnani knihoven je v PARENT_COMPARISON.json. Parent kod kordonu se neprepisuje.

Zdroj profilove politiky: R1_15A2_AGGRESSIVE_TUNING_V1.json, SHA-256 c41e28c1ecbaa3bbdef43b259458f6407bfbef6af240d9312282e47e6b83e10f.

Prenos: faze 1-6 (+/-20 % OD, +/-0.12 ADD log), 7-18 (+/-14 %, +/-0.08), 19-100 (+/-8 %, +/-0.05); 6 TG a 7 TD backtracking meritek; TG prah 1e-5, TD prah 5e-4. Salary/family limity preneseny do explicitniho TG/TD kontraktu.

Neprenasi se 488 profilova autorita, vsechny role CAL, GEH20/30 severity uvolneni, live globalni monkeypatch nebo FRESH100 Visum spoustec. Kordonove CAL/VALID rozdeleni, nezmenene C17 ucty, regularizace a presnost nativniho IPF zustavaji.

A00 skutecne testy: kordonova V2 170 passed; zdrojove agresivni policy/runtime testy 34 passed. Zadny zivy Visum nebyl spusten.

Cil teto dodavky je funkcni agresivni OFFLINE_PROPOSAL varianta, nikoliv implicitni odemceni APPLY. Vyssi pozadovane OD korekce se nesmi vydavat za skutecnou TG/TD realizaci.
