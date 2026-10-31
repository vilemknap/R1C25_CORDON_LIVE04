# Test report - STARTUP FIX1

Vsechny uvedene behy byly opravdu spusteny v tomto vyvojovem prostredi.
Zadny skutecny PTV Visum server ani model 2025 nebyl spusten/zmenen.

| Sada | Vysledek |
|---|---|
| Original cordon aggressive V1 | 253 passed |
| Original supplied profile aggressive FIX1 | 961 passed, 4 skipped |
| New adversarial contract tests BEFORE fixes | 17 failed (dukaz mezer) |
| Final cordon including bridge/bootstrap | 338 passed, 0 failed |
| Full inherited parent | 879 passed, 4 skipped, 1 failed (historical identity) |
| Parent compatibility (explicit deselection of that identity test) | 879 passed, 4 skipped, 1 deselected |
| Original-vs-patched aggressive demo | 84 NPZ fields exactly equal |

## 85 pridanych pripadu

17 kontraktovych regresi; testy startup setting, pole GetMultiAttValues,
neplatne/kratke seznamy, mandatory scope, model 2022, chybne/nesaved version,
COM rejected a unprintable exceptions, read-only trap, hierarchy across
pages, full shared-geometry proof, per-OD distribuce pri stejnem celku,
matice/path drift, raw vs final snapshots, exact zero-volume counts,
disk budgets, STOP/thread identity, cleanup failures, external matrix
hash/scope/path guards, old modules and sys.path restoration, busy host,
chybejici NumPy nebo injektovany Visum, chybejici manifest, wrong cwd,
script bez __file__, opakovane spusteni, bez SystemExit/sys.argv parseru,
a startup bez offline-only openpyxl/scipy/pandas.

## Historicke neuspesne behy nejsou skryty

17 adversarial failures pred opravou: new_adversarial_before.log.
Prvni bridge testy odhalily chyby v test fixture (odstraneni pomoci
pop(0) odstranilo pomocnou hranu, ne SDP) a nesoulad ocekavaneho textu
resource-gate chyby. Ty byly opraveny, ne ignorovany.
Prvni rodicovska regrese mela dva fails: historicka byte-identity plus
nesynchronizovana vlozena COM kopie. Kopie byla opravena a tento test
nyni prochazi; jediny zbyvajici fail je zamerna puvodni identity ochrana.
Nekolik synchronnich testovacich volani bylo preruseno limitem nastroje.
Nasledny plny beh dokoncil 328/328, po dalsich doplncich 338/338; diagnostika
stacku neprokazala deadlock. Nedokoncene logy se nevydavaji za PASS.

Prokazany originalni COM problem: original_cordon -> ValueError po 1 volani
(str() prekryl puvodni vyjimku); patched -> puvodni Unprintable po 3
povolenych pokusech. Viz UNPRINTABLE_COM_BEFORE_AFTER.json.

Ciste rozbalena dodavka ma byt overena znovu. Jeji vysledky jsou v externim
FINAL_VERIFICATION.json; nelze je tvrdit pouze na zaklade teto tabulky.
