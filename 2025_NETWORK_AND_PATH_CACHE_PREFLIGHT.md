# Preflight budouci skutecne 2025 site a cache

Tento dokument je plan dalsiho gate; nize uvedene zive kroky NEBYLY provedeny.

1. Zachovat bezici model 2022 nedotceny. Pripravit samostatnou, jednoznacne
   identifikovanou instanci/kopii modelu 2025 az po souhlasu uzivatele.
2. Samostatne zaznamenat model_year=2025, survey_year=2026, network_sha256,
   demand_sha256, assignment scope, obdobi a jednotky vozidel. Rok poptavky
   neni verze site. Bez schvaleneho year_bridge jde o referencni scenar.
3. Overit vsech 16 SDP a 32 smerovych klicu (LinkNo, FromNodeNo, ToNodeNo)
   na teto konkretni siti. Drive potvrzeny SDP16 link2004231 neni automaticky
   dukazem stejnych identit v nove siti.
4. Auditovat kompletni OA scope: NATIVE_CW, CW_noT, CS, CS_noT, CL, CF a
   odpovidajici EXOG_EE segmenty. LNV/NV/BUS se nesmi vydavat za OA.
   Nepredpokladat, ze stejny parent key v C a C_noT ma stejne hrany.
5. Pouzit existujici 15A2 davkovy collector. Nespoustet stary 15N bez
   davkovani, vlastni shortest-path/Dijkstru ani automaticky 2022 launcher.
   V24915 sampler/sharing PROVISIONAL neni dukaz plne geometricke identity.
6. Po dokonceni exportu a uzavreni databaze pripravit samostatny stabilni
   snapshot. Nesmime kopirovat jen hlavni SQLite soubor behem zapisu WAL.
   V1 odmita soubory se sousednim -wal/-shm/-journal. Nikdy je nema smazat,
   aby si kontrolu vynutila. Pri pochybnosti ziskat snapshot pozdeji.
7. Dodana SQLite musi obsahovat metadata(schema), geometry(edge_ids,
   sequence_sha256, edge_count), edges, segments(audit_json), volumes.
   Uplne sektory geometry jsou v provedene sekvenci uint32 little-endian.
   NULL neni prazdna cesta. Nulovy pocet hran interzonalni cesty se uchova
   a reportuje, ale nedoplni vymyslenymi hranami.
8. Overit per-DSeg objemy a per-OD soucty proti nezavislemu exportu prislusne
   demand matice. Equality souctu samotnych cest neni nezavisly dukaz.
   Ciste path totals misto demand authority mohou zustat DIAGNOSTIC_ONLY.

## Povinna evidence JSON vedle explicitniho snapshotu

```json
{
  "schema": "CORDON_FROZEN_CACHE_EVIDENCE_V1",
  "completed": true,
  "model_year": 2025,
  "basis": "RPDI",
  "category": "OA",
  "origin": "VISUM_SAVED_PATHS",
  "cache_sha256": "SHA256 skutecneho dokonceneho souboru",
  "network_sha256": "SHA256 auditovane site",
  "demand_sha256": "SHA256 auditovaneho demand snapshotu",
  "geometry_full_identity_proven": false,
  "dseg_totals": {"NATIVE_CW": 123.0},
  "od_totals": [{"dseg":"NATIVE_CW","orig":1,"dest":2,"volume":123.0}]
}
```

Tato ukazka je zkracena SCHEMA, nikoli skutecna evidence. Je treba vsechny
vybrane segmenty a vsechny OD klice (vcetne legitimnich nulovych path parentu),
nikoli pouze tento jeden priklad. Celkovy rozsah schvaluje dseg_scope authority.
Nenulovy novy OD bez podpory musi znovu enumerovat cesty; gate se nesmi obejit.

Konfigurace pro `propose` navic vyzaduje presne actuatable_zones ze schvaleneho
TG/TD scope. `inspect-cache` zadne aktuatory nepouziva. Varianta se sdilenou
geometrii zustava podminena, dokud neni overena pro vsechny prispivajici DSeg.

## Co nelze uzavrit pouhym exportem

Observation semantics, smerova orientace survey matic, jejich symetrizace,
C17 fyzicka alokace a 2026->2025 bridge potrebuji samostatne autority.
Mala chyba na dvou ruznych enumeracnich hypotezach neni dukaz spravne definice.
Realizovatelnost TG/TD vyzaduje skutecne parametry nebo auditovany response
operator a nasledne zivy kontrolovany trial. V1 takovy trial neumoznuje.
