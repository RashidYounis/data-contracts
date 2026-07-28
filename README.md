# data-contracts

Datakontrakter for SB1U, basert på [ODCS v3.1.0](https://bitol-io.github.io/open-data-contract-standard/latest/) (Open Data Contract Standard).

En datakontrakt definerer en forpliktelse fra en dataleverandør mot sine konsumenter: hvilke data som leveres, hvordan de er strukturert, hva de betyr, hvilken kvalitet og stabilitet som kan forventes, hvilke grensesnitt som støttes og hvordan versjonsendringer håndteres. Kontrakten forutsetter at eierskapet til dataleveransen er entydig plassert.

## Innhold

| Fil | Beskrivelse |
| --- | --- |
| `datakontrakt_mal.yml` | Mal for nye datakontrakter. Kopiér denne og fyll ut alle `TODO`-felter. |
| `contracts/` | Datakontrakter, én YAML-fil per dataprodukt. |
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

Kontrakter valideres langs tre dimensjoner. Feil (`E`) er blokkerende, advarsler (`A`) er anbefalinger.

**Eierskap** — `team.name` og minst ett `team.members`-medlem med rollen `Owner` og utfylt `username`. Minst én `support`-kanal med `tool: email`. Data steward og Slack-kanal gir advarsel hvis de mangler.

**Klassifisering** — `dataCategory` og `containsPersonalData` som `customProperties`, `gdprLegalBasis` hvis kontrakten inneholder persondata, og oppbevaringstid som `slaProperties[property=retention]`.

**Innhold** — ODCS-header (`apiVersion` v3.x, `kind: DataContract`), fundamentals, `description.purpose`, en produksjonsserver med komplett konfig, `schema` med beskrevne kolonner, gyldig `logicalType`, primærnøkkel, og en ferskhets-SLA (`slaProperties[property=latency]`).

## SB1U-profilen

ODCS har ingen native felter for enkelte norske styringskrav. Disse ligger som `customProperties` med faste navn, definert i `SB1U_CUSTOM_PROPS` i `validate_contracts.py`:

| customProperty | Krav | Verdier |
| --- | --- | --- |
| `dataCategory` | Påkrevd | `public`, `internal`, `confidential`, `sensitive`, `personal_data` |
| `containsPersonalData` | Påkrevd | `true` / `false` (ekte boolean) |
| `gdprLegalBasis` | Påkrevd hvis `containsPersonalData: true` | f.eks. `legitimate_interest`, `contract`, `consent` |
| `githubTeam` | Anbefalt | f.eks. `@example-org/example-data-team` |
| `consumers` | Valgfri | liste av `{team, useCase}` |

Øvrige valg i profilen:

- Oppbevaringstid uttrykkes som `slaProperties[property=retention]` med `value` og `unit` (`d` eller `y`), siden ODCS har et definert felt for dette.
- PII markeres per kolonne med tag `pii` og `classification`, ikke som en sentral liste.
- Produksjonsserveren identifiseres ved `environment: prod` (eller `server: production`).

Endres disse navnene, må `datakontrakt_mal.yml` og `validate_contracts.py` oppdateres samtidig.

## Merk

ODCS må ikke forveksles med [Data Contract Specification](https://datacontract.com) (`apiVersion: datacontract.com/...`). Standardene bruker ulike feltnavn — ODCS har `schema`/`properties` der den andre har `models`/`fields`, og `slaProperties` der den andre har `sla`. Validatoren avviser eksplisitt kontrakter med feil `apiVersion`.

Datakontrakter skal heller ikke forveksles med rene tekniske kontrakter eller verktøyspesifikk dokumentasjon som dbt-skjemaer, modeller eller tester. Slike artefakter kan understøtte implementeringen av en datakontrakt, men utgjør ikke alene en fullverdig kontrakt, siden de ikke dekker ansvar, forventninger, semantikk og styringsmessige forhold knyttet til dataleveransen.
