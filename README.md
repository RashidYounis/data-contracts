# data-contracts

Datakontrakter for SB1U, basert på [ODCS v3.1.0](https://bitol-io.github.io/open-data-contract-standard/latest/) (Open Data Contract Standard).

En datakontrakt definerer en forpliktelse fra en dataleverandør mot sine konsumenter: hvilke data som leveres, hvordan de er strukturert, hva de betyr, hvilken kvalitet og stabilitet som kan forventes, hvilke grensesnitt som støttes og hvordan versjonsendringer håndteres. Kontrakten forutsetter at eierskapet til dataleveransen er entydig plassert.

## Innhold

| Fil | Beskrivelse |
| --- | --- |
| `datakontrakt_mal.yml` | Mal for nye datakontrakter. Kopiér denne og fyll ut alle `TODO`-felter. |
| `contracts/` | Datakontrakter, én YAML-fil per dataprodukt. |
| `contracts/example_betaling_kategorisering.yml` | Eksempel som viser hele klassifiserings- og kategoriseringsmodellen: to datasett med ulikt beskyttelsesbehov, alle fire nivåer, alle kategoriverdier og SKPO. |
| `contracts/example_kredittkunde_serving.yml` | Enklere eksempel med ett datasett. |
| `validate_contracts.py` | Validerer alle kontrakter i `contracts/` og skriver en HTML-statusrapport. |

## Bruk

```bash
pip install -r requirements.txt
python validate_contracts.py
```

Validatoren skriver en oversikt til terminalen og en rapport til `contracts_report.html`. Den avslutter med exit-kode 1 hvis én eller flere kontrakter har feil, slik at den kan brukes direkte som en gate i CI.

### Legge til en ny kontrakt

```bash
cp datakontrakt_mal.yml contracts/mitt_dataprodukt.yml
# fyll ut alle TODO-felter
python validate_contracts.py
```

Filer i `contracts/` som starter med `_` hoppes over.

## Valideringsregler

En datakontrakt skal definere hvilke data som leveres og hvordan de er strukturert, hva dataen betyr, hvilken kvalitet og stabilitet som kan forventes, hvilke grensesnitt som støttes og hvordan versjonsendringer håndteres — alt forankret i et entydig eierskap. Validatoren håndhever dette som fem dimensjoner. Feil (`E`) er blokkerende, advarsler (`A`) er anbefalinger.

**Eierskap** — `team.name` og minst ett `team.members`-medlem med rollen `Owner` og utfylt `username`. Minst én `support`-kanal med `tool: email`. Data steward og Slack-kanal gir advarsel hvis de mangler.

**Klassifisering** — hver kolonne skal ha et klassifiseringsnivå (`classification`) og full kategorisering (`personopplysning` + `personidentifikator`). `dataClassification` og `containsPersonalData` som `customProperties` på kontraktsnivå, `gdprLegalBasis` hvis kontrakten inneholder persondata, og oppbevaringstid som `slaProperties[property=retention]`. Se [Klassifisering og kategorisering](#klassifisering-og-kategorisering).

**Innhold** — ODCS-header (`apiVersion` v3.x, `kind: DataContract`), fundamentals, `description.purpose`, en produksjonsserver med komplett konfig, `schema` med beskrevne kolonner, gyldig `logicalType` og primærnøkkel. Minst én kvalitetsregel per datasett, på tabell- eller kolonnenivå — en kontrakt uten kvalitetsregler forplikter bare på struktur. Ferskhet via `slaProperties[latency]` og stabilitet via `slaProperties[availability]`, som er påkrevd for `status: active`.

**Semantikk** — kontrakten skal fortelle hva dataen betyr og hvor den kommer fra, ikke bare hvordan den ser ut. `businessName` per kolonne, `transformSourceObjects` som dataavstamming oppstrøms, og en `authoritativeDefinitions`-oppføring med `type: implementation` som peker på koden som produserer leveransen. `canonical` og `businessDefinition` gir advarsel hvis de mangler.

**Versjonering** — `version` må være semantisk (`MAJOR.MINOR.PATCH`), slik at breaking changes kan skilles maskinelt fra bakoverkompatible endringer. `breakingChangeNoticeDays` må være minst 30. Livsløp via `slaProperties`: `generalAvailability`, `endOfSupport` og `endOfLife` — de to siste er påkrevd når status er `deprecated` eller `retired`, siden de da utgjør avviklingsplanen konsumentene planlegger etter.

## SB1U-profilen

ODCS har ingen native felter for enkelte norske styringskrav. Disse ligger som `customProperties` med faste navn, definert i `SB1U_CUSTOM_PROPS` i `validate_contracts.py`:

| customProperty | Krav | Verdier |
| --- | --- | --- |
| `dataClassification` | Påkrevd (kontrakt + datasett) | `aapen`, `intern`, `fortrolig`, `strengt_fortrolig` |
| `personopplysning` | Påkrevd per kolonne | `ingen`, `alminnelig`, `skpo` |
| `personidentifikator` | Påkrevd per kolonne | `direkte`, `indirekte`, `ikke_identifiserende` |
| `containsPersonalData` | Påkrevd | `true` / `false` (ekte boolean) |
| `gdprLegalBasis` | Påkrevd hvis `containsPersonalData: true` | f.eks. `legitimate_interest`, `contract`, `consent` |
| `breakingChangeNoticeDays` | Påkrevd, minst `30` | heltall, antall dager |
| `githubTeam` | Anbefalt | f.eks. `@example-org/example-data-team` |
| `consumers` | Valgfri | liste av `{team, useCase}` |

Øvrige valg i profilen:

- Oppbevaringstid uttrykkes som `slaProperties[property=retention]` med `value` og `unit` (`d` eller `y`), siden ODCS har et definert felt for dette.
- Livsløp og stabilitet uttrykkes også som `slaProperties` (`generalAvailability`, `endOfSupport`, `endOfLife`, `availability`, `timeToNotify`) i stedet for egne felter.
- Dataavstamming ligger per kolonne i `transformSourceObjects`, med `transformDescription` som forklaring i forretningstermer.
- Persondata markeres per kolonne gjennom kategoriseringen (`personopplysning` + `personidentifikator`), ikke som en sentral liste og ikke som tags. En `pii`-tag ville duplisert kategoriseringen med mindre presisjon, og to kilder til samme faktum kommer før eller senere i utakt.
- Produksjonsserveren identifiseres ved `environment: prod` (eller `server: production`).

Endres disse navnene, må `datakontrakt_mal.yml` og `validate_contracts.py` oppdateres samtidig.

## Klassifisering og kategorisering

Klassifisering og kategorisering er grunnleggende mekanismer for å sikre at data håndteres i samsvar med gjeldende lover, forskrifter og interne styrende dokumenter gjennom hele dataens livssyklus. De skal ligge i metadataene og følge dataene ved lagring, behandling, analyse og deling — det er derfor de hører i datakontrakten og ikke i et sidedokument.

### Klassifisering

Klassifisering er en vurderingsprosess hvor data inndeles etter juridiske og regulatoriske krav, grad av sensitivitet og konfidensialitet, og forretningsmessig og omdømmesmessig risiko. Nivået fastsetter hvilket beskyttelsesnivå, hvilke kontrolltiltak og hvilke bruksbegrensninger som gjelder. SB1U opererer med fire nivåer:

| Nivå | Beskrivelse |
| --- | --- |
| `aapen` | Offentlig tilgjengelig eller kan deles fritt uten risiko. Kan distribueres internt og eksternt uten restriksjoner. |
| `intern` | Beregnet for intern bruk, kan deles innenfor virksomheten. Skal ikke deles eksternt uten særskilt vurdering, og skal være sporbar. F.eks. produkthierarki og aggregert statistikk uten personidentifiserbare opplysninger. |
| `fortrolig` | Kun tilgjengelig for autoriserte mottakere med tjenstlig behov. Tilgang og deling skal være begrenset og sporbar. F.eks. kundemaster og transaksjoner uten full detaljeringsgrad. |
| `strengt_fortrolig` | Kun tilgjengelig for en særskilt, begrenset krets av autoriserte mottakere med tjenstlig behov. Tilgang og deling skal være svært begrenset og fullt sporbar. F.eks. transaksjoner med full detaljeringsgrad, kortdata og særlige kategorier personopplysninger. |

Nivået angis på tre steder. ODCS definerer `classification` **kun på kolonnenivå** — både kontraktsroten og schema-objekter avviser ukjente felter i ODCS' eget JSON-skjema, så en `classification` plassert der gjør kontrakten ugyldig. Validatoren avviser det eksplisitt og peker på riktig alternativ:

| Nivå | Hvor | Krav |
| --- | --- | --- |
| Kontrakt | `customProperties.dataClassification` | Påkrevd |
| Datasett | `schema[].customProperties.dataClassification` | Anbefalt; påkrevd i praksis når kontrakten har flere datasett |
| Kolonne | `schema[].properties[].classification` | Påkrevd |

**Et nivå kan ikke være mindre strengt enn innholdet under seg** (`aapen` < `intern` < `fortrolig` < `strengt_fortrolig`). En kontrakt merket `intern` som inneholder en `fortrolig`-kolonne underrapporterer sitt eget beskyttelsesbehov, og gir feil. Datasettnivået måles mot kolonnene sine, og kontraktsnivået mot det strengeste under seg — datasettets nivå hvis det er satt, ellers kolonnene direkte.

### Kategorisering

Kategorisering er den operative implementeringen av klassifiseringen. Den registreres som maskinlesbare metadata, beskriver dataelementets juridiske kategori og grad av personidentifisering, og skal være entydig og konsistent nok til å brukes til automatisert tilgangsstyring, logging og revisjon.

**Alle kolonner skal ha verdi for begge attributter. Manglende kategorisering er ikke tillatt** — validatoren gir feil, ikke advarsel. ODCS har ingen felter for dette, så de ligger som `customProperties` per kolonne (tillatt via `SchemaElement`, som `SchemaProperty` arver fra).

**1. `personopplysning`** — om dataelementet inneholder personopplysninger etter personopplysningsloven og GDPR:

| Verdi | Beskrivelse |
| --- | --- |
| `ingen` | Dataelementet inneholder ikke personopplysninger |
| `alminnelig` | Personopplysning etter GDPR artikkel 4 |
| `skpo` | Særlige kategorier personopplysninger etter GDPR artikkel 9 |

**2. `personidentifikator`** — om dataelementet kan brukes til å identifisere en fysisk person:

| Verdi | Beskrivelse |
| --- | --- |
| `direkte` | Kan alene identifisere en fysisk person |
| `indirekte` | Kan bidra til identifisering sammen med andre opplysninger |
| `ikke_identifiserende` | Kan ikke benyttes til å identifisere en fysisk person |

```yaml
properties:
  - name: kunde_id
    classification: fortrolig
    customProperties:
      - property: personopplysning
        value: alminnelig
      - property: personidentifikator
        value: indirekte
```

### Sammenhengen mellom dem

Kategorisering fastsetter **ikke** klassifisering automatisk — den skal inngå som grunnlag ved fastsettelse av nivå etter SB1Us klassifiseringsmodell. Validatoren håndhever derfor bare de sammenhengene som er entydige:

- En kolonne kategorisert `skpo` kan ikke klassifiseres lavere enn `strengt_fortrolig`.
- En kolonne kategorisert `personopplysning: ingen` kan ikke samtidig være `direkte` eller `indirekte` identifiserende — kan den identifisere en person, inneholder den personopplysninger.
- `containsPersonalData` på kontraktsnivå kan ikke være `false` når en kolonne er kategorisert `alminnelig` eller `skpo`.

Utover dette er valg av nivå produktteamets vurdering. Produktteamet etablerer og vedlikeholder kategoriseringen som del av metadataforvaltningen, og produktleder er ansvarlig for at den er korrekt og oppdatert. Kategoriseringen skal gjennomgås ved endringer i datastruktur, behandlingsformål eller regulatoriske krav, og ved etablering av nye dataelementer. En kontraktsendring i Git med validatoren som gate i CI er stedet den gjennomgangen blir etterprøvbar.

## Bruk i dataverdikjeden

Kontrakten er ment å følge leveransen gjennom hele livsløpet, ikke bare være dokumentasjon:

- **Design** — bruk kontrakten som strukturert verktøy for å avklare innhold og avgrensninger tidlig, allerede når det foreligger en hypotese om en ny dataleveranse (Data Contract First).
- **Utvikling** — definisjonene i kontrakten er grunnlag for testdrevet utvikling og automatiserte tester på dataflyt, struktur og datakvalitet.
- **Utrulling** — som et absolutt minimum skal kontrakten brukes som gate i CI/CD, slik at endringer ikke bryter avhengigheter nedstrøms. Det er dette workflowen i `.github/workflows/` gjør.
- **Drift** — `slaProperties` og `quality` er maskinlesbare og kan brukes til å overvåke faktisk leveranse mot det som er avtalt.
- **Katalog** — kontraktene er tenkt som kilde for katalog- og søketjenester.
- **Avvikling** — `endOfSupport` og `endOfLife` gir konsumenter en forutsigbar avviklingsplan.

## Merk

ODCS må ikke forveksles med [Data Contract Specification](https://datacontract.com) (`apiVersion: datacontract.com/...`). Standardene bruker ulike feltnavn — ODCS har `schema`/`properties` der den andre har `models`/`fields`, og `slaProperties` der den andre har `sla`. Validatoren avviser eksplisitt kontrakter med feil `apiVersion`.

Datakontrakter skal heller ikke forveksles med rene tekniske kontrakter eller verktøyspesifikk dokumentasjon som dbt-skjemaer, modeller eller tester. Slike artefakter kan understøtte implementeringen av en datakontrakt, men utgjør ikke alene en fullverdig kontrakt, siden de ikke dekker ansvar, forventninger, semantikk og styringsmessige forhold knyttet til dataleveransen.
