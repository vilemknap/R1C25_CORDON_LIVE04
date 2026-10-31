# LIVE01 - dokonceni po obnove z CP03 (2026-10-24)

## Rozsah
Implementace zadani R1 2025 CORDON LIVE01 FOUNDATION + WHOLE-MATRIX BASELINE.
Jde o integrovany read-only start primo v otevrenem Visumu a skutecny navrh
TG parametru. Zapis, nativni TG/TD prepocet, assignment, ACCEPT a rollback
jsou vyhradne navazujici LIVE02, nejsou soucasti teto dodavky.

## Obnova
Na Drive byly nalezeny CP00 az CP03. Obnoveny CP03 ma SHA-256
04322b22e07d86eef86bd64b61478cba7d64a281ddd2f99bff966012ea28a45b.
ZIP CRC je bez chyby. Log puvodni plne sady nebyl dokonceny a nebyl pouzit
jako dukaz PASS. Dochovane prikazy a vysledky zustavaji v recovered evidence.
Znovu byly overeny vsechny tri pozadovane zdrojove ZIPy proti pinum zadani.

## Implementace a zdrojovy kontrakt
- Samostatny CORDON_LIVE01_CONFIG.json, nikoli vypnuti ochrany OFFLINE_PROPOSAL.
- RUN_R1_2025_CORDON_LIVE_BASELINE.py a cordon_live01_bootstrap.py: pouze
  injected Visum, stejny thread, detekce aktivniho 2022/15A2 procesu,
  izolovane importy a navrat sys.path/sys.modules po uspechu i vyjimce.
- live01_observations.py: audit vsech 256 OA bunek, 16 strukturalnich
  nulovych diagonal, vsech 120 neusporadanych paru v objective, 0 VALID.
  Historicke CSV a stary offline holdout zustavaji byteove nezmenene;
  nova LIVE01 cesta je nepouziva jako filtr objective.
- Zachovana puvodni transformace BIDIRECTIONAL_SUM: vstupni bunky se nemeni;
  effective target = source_ij + source_ji a effective model = model_ij +
  model_ji. Obe reprezentace jsou vypsany v WHOLE_MATRIX_TRANSFORM_TRACE.csv.
  Kazdy par vstupuje jednou. Neni zavedeno nove prumerovani ani zmena vah.
- live01_visum.py: 681 skutecnych Zone.NO, 12 osobnich DSeg a vazby pres
  ODMatrix (9301-9306, 9401-9406); C/C_NOT, 32 smerovych SDP klicu; dalnicni
  SDP1/3/15/16 C-only; 9 TG parametru a uplne donor dependency atributy.
- Neni kopirovan TG/TD ciselny stav 2022. Vsechny hodnoty se ctou z aktualni
  instance 2025. Technicka shoda schemat 2022/2025 je predpoklad uzivatele,
  zapsany do evidence a overovany kontraktem pri startu.
- Prime pouziti pinovaneho donor audit_trip_generation_contract, TD
  read_td_parameter_state a audit_assignment_scope. Jedina adaptace TG
  auditu nahrazuje pomocne cteni osy z tvrdeho 1..681 na 681 skutecnych
  unikatnich Zone.NO; vzorce, typy UDA a dependency kontroly se nemeni.
- zone_state_rows a generation_actuator_zone_scope jsou presne vyjmute
  funkce donora; AST source text i hashe jsou nezavisle porovnany. Zadny
  donor main se nespousti. Pouzite parent knihovny se slepe neprepisuji.
- TD/procedury: TG5 typ45, TD6 typ46, 16 domacich strata, volitelne FOREIGN
  v source DSTRATSET, chrana 9116, B/C i A readback; assignment17-20 a plny
  14segmentovy scope vcetne nemenneho LNV/NV; odkazy na externi skripty.
- Aktualni 9001/9697, FOREIGN, freight a procedury se hashove dokumentuji;
  zadne historicke 2022 'opravy bunek' se neaplikuji.
- live01_baseline.py: puvodni LEGACY FIX3 capture v teto invokaci, plne
  geometrie a per-OD parita; potom obe puvodni enumeracni metody, 120 CAL,
  FISTA -> parent_projection(zone_rows) -> donor design_generation_candidates.
  Agresivni velikosti kroku jsou prevzaty z existujici hashovane policy.
- LIVE01 nedela novy solver, nevytvari zjednodusene cesty, nespousti
  FlowBundle a nepouziva starsi snapshot jako dukaz aktualniho assignmentu.
- Nenulovy kandidat je pouze navrh aktualnich TG parametru. Realizovatelnost
  cele OD zmeny zustava UNKNOWN bez plne odezvy; native efekt nebyl otestovan.
- C17 UNAPPROVED zustava bez alokace, bez per-pair zvetsovani tolerance.
- Handoff pro LIVE02 je serializovany, s fingerprintem, hashi navrhu,
  povinnosti noveho live readbacku, PRE stavu a assignmentu po kandidatu.

## Dalsi opravy po obnoveni
Ctyri nove poruchove testy reprodukovaly, ze samotny puvodni zaverecny
readback LIVE01 (nezavisly na starsim capture readbacku) nezachyti pozdni
zmenu OA matice pri stejnem souctu, prepojeni ODMatrix, zmenu site ani
prepnuti aktualniho .ver souboru. Tyto testy pred opravou skutecne selhaly.
Rozsireni verify_end_state nyni tyto stavy porovnava obsahove. Kontrola se
provadi take po offline solve, pred publikaci predavaciho kontraktu.

Selhani pri uklidu zamku po dokonceni revokuje completed priznak; sekundarni
chyba logovani ani nefunkcni str()/repr() nezakryvaji primarni vyjimku.
verify_handoff_directory overuje kompletni checkpoint a obsahovy hash kazdeho
navrhu. Ani jeho PASS neautorizuje zapis do Visumu.

## Hranice dukazu
Fingerprint zahrnuje zony, TG/TD hodnoty, readback operaci, overene odkazy na
skripty, OA/freight/chranene matice, smerove sitove identity/TSysSet a zdrojovy
.ver soubor. Neni to kompletni fingerprint vsech moznych vlastnosti nabidky.
Full capture doklada geometrie ulozenych cest v prislusnem behu. Ani shodna
matice, ani novy hash nedokazuje pozdejsi assignment epoch. Po novem assignmentu
se nesmi automaticky pouzit stara PERF01 cache. Behem baseline model nemenit.

LEGACY capture vytvari pracovni COM seznamy a nastavuje jejich sloupce/filtry;
nejde o mutaci sitovych dat, matic nebo procedur. Fake host rozlisuje tuto
pracovni list konfiguraci od zakazanych model writes.

## Testy a stav
Presne prikazy, casy, exit codes a pocty viz LIVE01_TEST_REPORT.json.
Zadny nativni Windows/PTV test v tomto prostredi neprobehl. Status native
je NOT_RUN/LIVE_PENDING. Historicka kompletni V24915 identity suite nad
kordonovym forkem musi nadale odmitnout ctyri drive zmenene moduly. Tento
znamy neprechod identity neni skryty a je oddeleny od compatibility regrese.

## Nasledny krok
LIVE02 vyuzije BASELINE_AND_PROPOSAL_CONTRACT.json a overovaci API jako
vstup pro bezpecnou transakci. Tato verze sama nezapisuje navrhy, neprovadi
SaveVersion/LoadVersion, neslouzi k obnove stavu otevreneho Visumu z logu.
