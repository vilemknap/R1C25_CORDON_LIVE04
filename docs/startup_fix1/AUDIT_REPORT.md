# Detailni audit: cordon aggressive vs dodany profile aggressive 24915

## Metoda a skutecny rozsah

Prohledany a hashovany skutecne archivy. Nezamenovano uzivatelovo oznaceni
"funkcni" za nativni test provedeny zde. Referencni balik znovu otestovan
961 passed / 4 skipped. Puvodni kordonovy source: 253 passed.

V porovnani stejnojmennych knihovnich modulu bylo 153 shodnych,
4 odlisne a 30 pouze v kordonovem parent stromu. Dve puvodni odlisnosti
jsou zamerne kordonove hooky (core deadband, two-mode incidence); dve
jsou rozsirene IO/path a telemetry helpery. Kordonove dlouhe cesty/UNC
podpora se nesmi prepsat kratsi profilovou implementaci. Neproveden
blind rebase ani kopie PROFILE488 count autority do kordonu.

## Prokazane nalezy a konkretni upravy

### S01 - MISSING_INTEGRATION
Originalni spoustec odmital objekt Visum.

Novy oddeleny vstup pro PREFLIGHT a CAPTURE, nikdy profilovy CSD spoustec. Stav: `IMPLEMENTED_MOCK_TESTED`.

### S02 - INHERITED_DATA_BUG
Importer ignoroval skutecne auditni pole path_rows; nulovy radek mohl zmizet bez zmeny sumy.

Nativni row-count a kolize count autorit kontrolovany. Stav: `FIXED_TESTED`.

### S03 - INHERITED_DATA_BUG
Agregace mohla skryt rozdeleni opacnych smeru CAL/VALID.

Role se kontroluji pred agregaci. Stav: `FIXED_TESTED`.

### S04 - INHERITED_DATA_BUG
NaN/Inf/zaporne/bool survey hodnoty a neplatne solver parametry neodmitnuty vcas.

Kontrola vsech targets, parametru a sparse vstupu pred solverem. Stav: `FIXED_TESTED`.

### S05 - INHERITED_COM_BUG
Neprintovatelna COM vyjimka nahradila puvodni hresult chybu ValueError.

Bezpecny text chyby zachova puvodni vyjimku a retry. Stav: `FIXED_TESTED`.

### S06 - RUNTIME_RISK
Predchozi importy jineho 15A2 v trvalem Pythonu Visumu.

Izolace modulu a sys.path s obnovou po uspechu i chybe, busy guard. Stav: `IMPLEMENTED_MOCK_TESTED`.

### S07 - RUNTIME_RISK
GUI filtr aktivnich objektu / neoverena signatura / hierarchie pres davku.

Pouze OnlyActive=False a overeny bounded exporter 15A2. Stav: `IMPLEMENTED_MOCK_TESTED`.

### S08 - RUNTIME_RISK
Spravny celkovy soucet skryje presun objemu mezi OD bunkami.

Nezavisla per-OD parita proti zive matici a opakovane NPZ overeni. Stav: `IMPLEMENTED_MOCK_TESTED`.

### S09 - RUNTIME_RISK
Predpoklad shodne geometrie uvnitr modu bez dukazu.

Plne porovnani sekvenci, zmena => STOP; nikoli zamena C/C_noT. Stav: `IMPLEMENTED_MOCK_TESTED`.

### S10 - RUNTIME_RISK
Zmena matic/tras/sitove struktury behem capture.

Konecny readback + kontrolni hashe a zadny completed snapshot pri chybe. Stav: `IMPLEMENTED_MOCK_TESTED`.

### S11 - STARTUP_DEPENDENCY
Openpyxl se nacital i pri cteni CSV mapovani.

Lazy import pouze pri explicitnim auditu seitu; test bez openpyxl/scipy/pandas. Stav: `FIXED_TESTED`.

### S12 - RUNTIME_RISK
Uklid nebo telemetrie prekryje primarni chybu.

Noncritical progress a primary-preserving cleanup; kriticke vysledky fail closed. Stav: `IMPLEMENTED_MOCK_TESTED`.

### S13 - KNOWN_LIMIT
Zive TG/TD/assignment/ACCEPT/ROLLBACK kordonove vetve chybi.

Nevydavat read-only capture za kalibraci; samostatny live adapter je dalsi nutna implementace. Stav: `NOT_IMPLEMENTED`.

### S14 - KNOWN_LIMIT
Metodicke a nativni 2025 autority nejsou overene.

Ponechany blokace semantics/year/C17/real native session. Stav: `BLOCKED`.

## Zmeny rodicovskeho kodu

Ctyri explicitne popsane soubory proti puvodnimu cordon aggressive V1:
- r1_15a2_com_compat.py: bezpecny text COM chyby; eligibility a retry matematika nemeneny.
- r1_15a2_supply.py: explicitni geometry_only inicializace; prazdna profilova autorita nadale zakazana v normalnim rezimu.
- r1_15a2_two_mode_v238.py: stejne geometrii-only API a zakaz profiloveho objective v tomto rezimu.
- R1_15A2_VISUM_COM_PREFLIGHT_V2_3_6_INLINE.py: synchronizovana vlozena kopie COM hranice, nikoli zmena konfigurace CSD.

Pouziti prazdne profilove autority bylo odhaleno pri implementaci noveho
bridge; jde o novy integracni problem opraveny pred dodanim, nikoli skryty
problem puvodniho profiloveho controlleru. Nevytvorili jsme falesne scteci
profily s nulovymi merene hodnotami jen k obejiti kontraktu.

Vsechny patche, hashe pred/po a duvody jsou v REVIEWED_PARENT_CHANGES.json
plus *.startup.patch. Historicky V24915 manifest se nemeni. Puvodni testy
identity 2022 nadale fork odmitnou. Vlastni testy zachovani V2 byly rozsireny
o explicitni ctyr-souborovy allowlist s presnymi before/after SHA; puvodni
testy jsou ulozeny v provenance/startup_base, nikoli smazany.

## Zachovana cisla

C17 limity, rozdeleni CAL/VALID, uzavirky/frozen DSeg a agresivni faze
nebyly uvolneny. Numericky demo porovnano v oddelenych procesech pred/po:
84 poli v NPZ je presne shodnych. Generovano z oznacenych syntetickych
scenaru, nikoli z nedodane site 2025.

## Co nelze dovodit z tohoto auditu

Mock neoveruje marshalling skutecneho nainstalovaneho Visum COM serveru,
prava Windows, aktualnost jeho assignmentu ani spravnost smerove autority.
Ani 338/338 testu tak neprokazuje uplnou kalibraci modelu. Full shared
geometry proof muze na konkretni siti pravem selhat; fallback na domyslene
cesty nebo falesnou rovnost segmentu neexistuje. Nejde o chybu, kterou
bychom meli potichu vypnout.
