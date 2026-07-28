# data-contracts

Datakontrakter for SB1U, basert på [ODCS v3.1.0](https://bitol-io.github.io/open-data-contract-standard/latest/) (Open Data Contract Standard).

En datakontrakt definerer en forpliktelse fra en dataleverandør mot sine konsumenter: hvilke data som leveres, hvordan de er strukturert, hva de betyr, hvilken kvalitet og stabilitet som kan forventes, hvilke grensesnitt som støttes og hvordan versjonsendringer håndteres. Kontrakten forutsetter at eierskapet til dataleveransen er entydig plassert.

## Kom i gang

Skal du fylle ut din første kontrakt, bruk appen — den er et skjema, og du trenger ikke skrive YAML:

```bash
pip install -r requirements-app.txt
streamlit run app.py
```

Appen åpner i nettleseren på `http://localhost:8501`. Du fyller ut skjemaet, trykker **Verifiser** når du er ferdig, og laster ned en ferdig YAML-fil du legger i `contracts/`. Den bruker samme validator som CI, så en kontrakt som er grønn i appen er grønn i CI.

Foretrekker du å redigere YAML direkte:

```bash
pip install -r requirements.txt
cp datakontrakt_mal_enkel.yml contracts/mitt_dataprodukt.yml
# fyll ut TODO-feltene
python validate_contracts.py
```

Den første kontrakten din trenger bare dette:

- **Hvem eier den** — teamnavn, e-post til produkteier, en team-e-post
- **Hva leveres** — datasettnavn, og for hver kolonne: navn, type og beskrivelse
- **Klassifisering** — nivå per kolonne og for leveransen som helhet
- **Kategorisering** — `personopplysning` og `personidentifikator` per kolonne
- **Hvor den ligger** — Snowflake-server

Behold `status: draft` til leveransen faktisk er i produksjon. Da er SLA, livsløpsdatoer, kvalitetsregler og referanselenker **advarsler** — nyttige å fylle ut, men de stopper deg ikke. Det gjør det mulig å opprette kontrakten allerede når du har en hypotese om en ny leveranse, uten å gjette på tall du ikke kan vite ennå.

Når du setter `status: active`, blir de samme kravene blokkerende. Det er den kontrollerte overgangen: kontrakten må være komplett før noen kan ta avhengigheter på leveransen i produksjon.

## Innhold

| Fil | Beskrivelse |
| --- | --- |
| `app.py` | **Start her.** Utfyllingsapp — skjema i nettleseren, ingen YAML. `streamlit run app.py` |
| `datakontrakt_mal_enkel.yml` | Minimumsmal for deg som vil redigere YAML — alt som kreves for en `draft`. |
| `datakontrakt_mal.yml` | Fullstendig mal med alle felter og forklaringer. Bruk den når du skal til `active`. |
| `contracts/` | Datakontrakter, én YAML-fil per dataprodukt. |
| `contracts/example_kredittkunde_serving.yml` | Enkelt eksempel med ett datasett. |
| `contracts/example_betaling_kategorisering.yml` | Eksempel som viser hele klassifiserings- og kategoriseringsmodellen: to datasett med ulikt beskyttelsesbehov, alle fire nivåer, alle kategoriverdier og SKPO. |
| `validate_contracts.py` | Validerer alle kontrakter i `contracts/` og skriver en HTML-statusrapport. |

Validatoren skriver en oversikt til terminalen og en rapport til `contracts_report.html`. Den avslutter med exit-kode 1 hvis én eller flere kontrakter har feil, slik at den kan brukes direkte som en gate i CI. Filer i `contracts/` som starter med `_` hoppes over.

## Utfyllingsappen

`app.py` er et skjema for å opprette og endre datakontrakter uten å skrive YAML. Den er laget for produkteiere og andre som eier innholdet i en kontrakt, men ikke nødvendigvis skriver kode.

```bash
pip install -r requirements-app.txt
streamlit run app.py
```

Appen er delt i de fem spørsmålene en kontrakt svarer på — hva er dette, hvem eier det, hvor ligger dataen, hva leveres, hvor beskyttet er det. Kolonnene redigeres som et regneark, med nedtrekksmenyer for klassifisering og kategorisering, slik at man ikke trenger å kjenne maskinverdiene: skjemaet viser «Strengt fortrolig» og skriver `strengt_fortrolig`. Hva hver verdi betyr står i tegnforklaringen under tabellen.

Valideringen kjører når du ber om den, ikke mens du skriver: trykk **Verifiser** når skjemaet er fylt ut. Et tomt skjema bryter naturligvis alle regler, og å møte en førstegangsbruker med fjorten feil før første tastetrykk er støy, ikke veiledning. Etter første verifisering holder statusen seg levende, slik at du ser avvikene forsvinne mens du retter dem.

Avvikene listes under skjemaet med hvilken dimensjon og hvilket felt de gjelder, og sidepanelet viser antall feil, antall advarsler og score. Nedlastingsknappen er sperret til kontrakten er verifisert uten feil, så en fil som kommer ut av appen validerer også i CI. Appen importerer `validate_contract` fra `validate_contracts.py` — det er samme kode, ikke en kopi av reglene, så de kan ikke komme i utakt.

Felter som ikke kreves i utkastfasen ligger bak «Valgfritt»-seksjoner. En førstegangsbruker ser dermed bare de feltene en `draft` faktisk trenger.

En eksisterende kontrakt kan lastes inn fra sidepanelet — enten fra `contracts/` eller som opplastet fil — endres i skjemaet og lastes ned igjen. Appen skriver ikke til `contracts/` selv: den gir deg en fil du legger inn og committer, slik at endringen går gjennom Git og CI som alle andre endringer.

## Valideringsregler

En datakontrakt skal definere hvilke data som leveres og hvordan de er strukturert, hva dataen betyr, hvilken kvalitet og stabilitet som kan forventes, hvilke grensesnitt som støttes og hvordan versjonsendringer håndteres — alt forankret i et entydig eierskap. Validatoren håndhever dette som fem dimensjoner. Feil (`E`) er blokkerende, advarsler (`A`) er anbefalinger.

Kravene avhenger av `status`. Reglene under er beskrevet slik de gjelder for en **aktiv** kontrakt. I `proposed` og `draft` er kravene merket 🕓 advarsler i stedet for feil:

| Krav | `draft` | `active` |
| --- | --- | --- |
| Eierskap, kolonner med beskrivelse, klassifisering, kategorisering, server | Feil | Feil |
| 🕓 SLA (`latency`), oppbevaringstid (`retention`) | Advarsel | Feil |
| 🕓 Kvalitetsregler per datasett | Advarsel | Feil |
| 🕓 `implementation`-referanse til koden som produserer dataen | Advarsel | Feil |
| 🕓 `businessName` på over 75 % av kolonnene | Advarsel | Feil |

**Eierskap** — `team.name` og minst ett `team.members`-medlem med rollen `Owner` og utfylt `username`. Minst én `support`-kanal med `tool: email`. Data steward og Slack-kanal gir advarsel hvis de mangler.

**Klassifisering** — hver kolonne skal ha et klassifiseringsnivå (`classification`) og full kategorisering (`personopplysning` + `personidentifikator`). `dataClassification` som `customProperty` på kontraktsnivå, og oppbevaringstid som `slaProperties[property=retention]`. Se [Klassifisering og kategorisering](#klassifisering-og-kategorisering).

**Innhold** — ODCS-header (`apiVersion` v3.x, `kind: DataContract`), fundamentals, `description.purpose`, en produksjonsserver med komplett konfig, `schema` med beskrevne kolonner, gyldig `logicalType` og primærnøkkel. Minst én kvalitetsregel per datasett, på tabell- eller kolonnenivå — en kontrakt uten kvalitetsregler forplikter bare på struktur. Ferskhet via `slaProperties[latency]` og stabilitet via `slaProperties[availability]`, som er påkrevd for `status: active`.

**Semantikk** — kontrakten skal fortelle hva dataen betyr, ikke bare hvordan den ser ut. `businessName` per kolonne, og en `authoritativeDefinitions`-oppføring med `type: implementation` som peker på koden som produserer leveransen. `canonical` og `businessDefinition` gir advarsel hvis de mangler.

**Versjonering** — `version` må være semantisk (`MAJOR.MINOR.PATCH`), slik at breaking changes kan skilles maskinelt fra bakoverkompatible endringer. Livsløp via `slaProperties`: `generalAvailability`, `endOfSupport` og `endOfLife` — de to siste er påkrevd når status er `deprecated` eller `retired`, siden de da utgjør avviklingsplanen konsumentene planlegger etter.

## SB1U-profilen

ODCS har ingen native felter for klassifisering på datasett- og kontraktsnivå eller for kategorisering per kolonne. Disse ligger som `customProperties` med faste navn, definert i `SB1U_CUSTOM_PROPS` i `validate_contracts.py`:

| customProperty | Krav | Verdier |
| --- | --- | --- |
| `dataClassification` | Påkrevd (kontrakt + datasett) | `aapen`, `intern`, `fortrolig`, `strengt_fortrolig` |
| `personopplysning` | Påkrevd per kolonne | `ingen`, `alminnelig`, `skpo` |
| `personidentifikator` | Påkrevd per kolonne | `direkte`, `indirekte`, `ikke_identifiserende` |

Øvrige valg i profilen:

- Oppbevaringstid uttrykkes som `slaProperties[property=retention]` med `value` og `unit` (`d` eller `y`), siden ODCS har et definert felt for dette.
- Livsløp og stabilitet uttrykkes også som `slaProperties` (`generalAvailability`, `endOfSupport`, `endOfLife`, `availability`, `timeToNotify`) i stedet for egne felter.
- Dataavstamming per kolonne kreves ikke. Å vedlikeholde kildekolonner manuelt for hver kolonne er kostbart, og avstammingen hentes bedre maskinelt fra dbt. Kontrakten peker på implementasjonen via `authoritativeDefinitions[type=implementation]` i stedet. `transformDescription` per kolonne er valgfri, for tilfeller der en utledning trenger en forklaring i forretningstermer.
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
