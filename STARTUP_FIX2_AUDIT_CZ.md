# Obnova a zapracovani hotfixu 24915 - STARTUP FIX2

## Odkud byla prace obnovena

Ulozena Drive slozka STARTUP_DEEP_AUDIT obsahovala vice nez viditelne prerusene hlaseni: B00-B03 a kompletni STARTUP_FIX1. Obnoven byl tento finalni archiv, nikoli starsi offline AGGRESSIVE V1. Jeho SHA souhlasi s ulozenym ukazatelem a vsech 1298 souboru manifestu proslo.

Obnoveny kod jiz mel samostatny Execute Script bootstrap, preflight, davkovy read-only capture, native path_rows paritu, markery dokonceni, plne porovnani geometrie segmentu a konecne cteni objemu/matic. Nemel plnou zivou kalibracni smycku; tato vlastnost se portem retry nezmenila.

## Delta dodaneho hotfixu

Proti PROFILE488 AGGRESSIVE FIX1 IOFIX4 je hotfix aditivni: 5 novych souboru, zadny zmeneny nebo odstraneny puvodni soubor. Jeho podstatou je knihovna r1_15a2_com_busy_snapshot_hotfix_v1.py. Byla prevzata byte-identicky, SHA256 2488191e97c17a072fd161c5645e17fa1fe0ac8c35412b92282d9737f0f76366.

Puvodni knihovna obaluje read_links, snapshot a optimalizovany single_pass_exact_snapshot, vcetne aliasu importovaneho hodnotou v trial adapteru. Pouhe zkopirovani knihovny ale neochrani vlastni kordonovy startup, ktery nepouziva profilovy snapshot. Proto byl doplnen cordon2025/com_busy.py a zmenen pouze kordonovy visum_startup.py.

## Implementace

- Puvodni hotfix se aktivuje bez profiloveho launcheru, pouze v docasnem prostoru modulu 2025. Vsechny ctyri reference a flag _ACTIVE se obnovi i pri castecne chybe aktivace.
- Opakovani cteni pouziva puvodni COM classifier/backoff 15A2. Nemenime matematicke jadro ani zdrojovy profilovy retry helper.
- Scope zahrnuje vytazeni Net/Procedures/IO/Workbench, Zones/Links/DemandSegments, GetMultiAttValues, ODMatrix/GetValues/AttValue, skutecne TypeInfo a bounded pages.
- Vnorene transakce sdili jeden retry rozpocet. Stranka pouziva presne puvodni parent bounded_rows a originalni FirstObject/LastObject; zadny druhy exporter ani cela opakovana rozpracovana SQLite.
- Vychozi retry: 64 pokusu, zacatek 0.15 s, faktor 1.5, maximum pauzy 1.5 s a 75 s na neuspesne cteni. Neni to globalni casovy limit behu ani preruseni zavisleho nativniho volani.
- STOP a COM thread se kontroluji i pred opakovanym Invoke po cekani/message pump.
- Ne-tranzientni chyby a schema/parity chyby se nemaskuji. Pri trvale zaneprazdnenem COM se vraci puvodni vyjimka, vcetne nefunkcniho str/repr.
- Telemetrie ma limit 1000 podrobnych retry udalosti a souhrnne pocitadlo. Jeji chyba nesmi prebit puvodni chybu. Kriticke vystupni zapisy zustavaji povinne.

## Zachovani fyzickeho a metodickeho vyznamu

808 puvodnich parent/datovych/konfiguracnich souboru zustalo byte-identickych. Zachovana je OA observation scope, fixed EXOG/CF/CL, kalibracni a validacni role, obe diagnosticke definice kordonu, C17, TG/TD velikosti kroku, IDP, LONG, AMDY 0.2 a IPF tolerance. V zadnem z techto mechanismu se neprovadela numericka uprava. Nenastavovalo se apply=true a profilova CSD2022/488 autorita nebyla importovana do behu.

Nedokoncene autority nejsou automaticky schvaleny. Plny supply/turn/connector fingerprint ani certifikace cerstvosti assignmentu nevznikaji pouze nactenim tras. Source version znamena model 2025; nejde o vynuceni aplikace PTV Visum 2025.

## Co lze nyni spustit

RUN_CORDON_2025_VISUM.py = read-only kontrola v aktualne otevrenem modelu.
RUN_CORDON_2025_CAPTURE.py = stejna kontrola + skutecne ulozene cesty + obe kordonove diagnostiky.

Nejde o zivy TG/TD -> assignment -> objective -> ACCEPT/ROLLBACK controller. Takova implementace v obnovenem zdroji neni. Tento port ji nenahrazuje prazdnou smyckou ani volanim profiloveho controlleru.

## Testy a zbyvajici riziko

Viz STARTUP_FIX2_TEST_REPORT.md a FINAL_STATUS.json. Nativni PTV/Windows test nebyl proveden; nepredstirame real_visum_tested. Licencni stav, skutecna COM verze, soucasna sit/mapovani a ulozene cesty musi byt overeny prvnim realnym read-only spustenim. Ruzna geometrie segmentu uvnitr jednoho modu vede k odmitnuti sdileni, nikoli k tiche nahrade.
