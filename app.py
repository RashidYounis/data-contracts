#!/usr/bin/env python3
"""
Datakontrakt-utfyller: et skjema for å opprette en datakontrakt uten å skrive YAML.

Kjør med:  streamlit run app.py

Appen importerer validate_contracts.py, så skjemaet og CI-gaten håndhever nøyaktig
de samme reglene. Alt som er valgfritt i utkastfasen er skjult bak
«Valgfritt»-seksjoner, slik at førstegangsbrukere ser de ~8 feltene en `draft`
faktisk krever.

Valideringen kjører først når brukeren ber om den — «Verifiser» eller nedlasting.
Et tomt skjema bryter naturligvis alle regler, og å møte en førstegangsbruker med
fjorten feil før første tastetrykk er ikke veiledning, det er støy.
"""

from __future__ import annotations

import copy
from pathlib import Path

import pandas as pd
import streamlit as st
import yaml

from validate_contracts import (
    CLASSIFICATION_RANK,
    DIM_LABELS,
    IDENTIFIER_VALUES,
    PERSONAL_DATA_VALUES,
    VALID_LOGICAL_TYPES,
    validate_contract,
)

CONTRACTS_DIR = Path(__file__).parent / "contracts"

# Leservennlige etiketter for maskinverdiene. Skjemaet viser venstre side og
# skriver høyre side til YAML — en produkteier skal ikke måtte kjenne
# «strengt_fortrolig» for å velge riktig beskyttelsesnivå.
#
# Etikettene er korte med vilje: de står i nedtrekksmenyer inne i kolonne-
# regnearket, og en full setning per verdi gjorde tabellen bredere enn skjermen.
# Forklaringene ligger i FORKLARINGER, som vises som en tegnforklaring under
# tabellen.
CLASSIFICATION_LABELS = {
    "Åpen": "aapen",
    "Intern": "intern",
    "Fortrolig": "fortrolig",
    "Strengt fortrolig": "strengt_fortrolig",
}
PERSONAL_DATA_LABELS = {
    "Ingen": "ingen",
    "Alminnelig (art. 4)": "alminnelig",
    "SKPO (art. 9)": "skpo",
}
IDENTIFIER_LABELS = {
    "Direkte": "direkte",
    "Indirekte": "indirekte",
    "Ikke identifiserende": "ikke_identifiserende",
}

FORKLARINGER = {
    "Klassifisering": [
        ("Åpen", "kan deles fritt, også eksternt"),
        ("Intern", "kan deles i virksomheten, skal være sporbar"),
        ("Fortrolig", "kun autoriserte med tjenstlig behov"),
        ("Strengt fortrolig", "særskilt begrenset krets, fullt sporbar"),
    ],
    "Personopplysning": [
        ("Ingen", "kolonnen inneholder ikke personopplysninger"),
        ("Alminnelig (art. 4)", "personopplysning etter GDPR artikkel 4"),
        ("SKPO (art. 9)", "særlige kategorier etter GDPR artikkel 9 — "
                          "kan ikke klassifiseres lavere enn strengt fortrolig"),
    ],
    "Personidentifikator": [
        ("Direkte", "kan alene peke ut en fysisk person"),
        ("Indirekte", "kan identifisere sammen med andre opplysninger"),
        ("Ikke identifiserende", "kan ikke brukes til å identifisere en person"),
    ],
}


def _label_for(value: str, labels: dict[str, str], fallback: str) -> str:
    """Etiketten som hører til en maskinverdi, eller fallback hvis ukjent."""
    return next((k for k, v in labels.items() if v == value), fallback)


# ── Kolonnetabellen ───────────────────────────────────────────────────────────
# Kolonnene redigeres som et regneark. Det er den formen ikke-tekniske brukere
# er vant til, og den gjør det raskt å kategorisere tjue kolonner etter hverandre.
COLUMN_SPEC = {
    "Kolonnenavn": "",
    "Forretningsnavn": "",
    "Beskrivelse": "",
    "Datatype": "string",
    "Påkrevd": True,
    "Primærnøkkel": False,
    "Klassifisering": "Fortrolig",
    "Personopplysning": "Ingen",
    "Personidentifikator": "Ikke identifiserende",
}


def empty_columns(n: int = 3) -> pd.DataFrame:
    rows = []
    for i in range(n):
        row = dict(COLUMN_SPEC)
        row["Primærnøkkel"] = i == 0
        rows.append(row)
    return pd.DataFrame(rows)


def columns_to_yaml(df: pd.DataFrame) -> list[dict]:
    """Regnearket → ODCS `properties`. Tomme rader hoppes over."""
    props, pk_pos = [], 0
    for _, row in df.iterrows():
        navn = str(row.get("Kolonnenavn") or "").strip()
        if not navn:
            continue
        is_pk = bool(row.get("Primærnøkkel"))
        if is_pk:
            pk_pos += 1
        prop: dict = {
            "name": navn,
            "logicalType": str(row.get("Datatype") or "string"),
            "description": str(row.get("Beskrivelse") or "").strip(),
            "required": bool(row.get("Påkrevd")),
            "primaryKey": is_pk,
            "primaryKeyPosition": pk_pos if is_pk else -1,
            "classification": CLASSIFICATION_LABELS.get(
                str(row.get("Klassifisering")), ""
            ),
            "customProperties": [
                {
                    "property": "personopplysning",
                    "value": PERSONAL_DATA_LABELS.get(str(row.get("Personopplysning")), ""),
                },
                {
                    "property": "personidentifikator",
                    "value": IDENTIFIER_LABELS.get(str(row.get("Personidentifikator")), ""),
                },
            ],
        }
        forretningsnavn = str(row.get("Forretningsnavn") or "").strip()
        if forretningsnavn:
            prop["businessName"] = forretningsnavn
        props.append(prop)
    return props


def columns_from_yaml(props: list[dict]) -> pd.DataFrame:
    """ODCS `properties` → regneark, for redigering av en eksisterende kontrakt."""
    rows = []
    for p in props:
        cp = {
            c.get("property"): c.get("value")
            for c in (p.get("customProperties") or [])
            if isinstance(c, dict)
        }
        rows.append({
            "Kolonnenavn": p.get("name", ""),
            "Forretningsnavn": p.get("businessName", ""),
            "Beskrivelse": p.get("description", ""),
            "Datatype": p.get("logicalType", "string"),
            "Påkrevd": bool(p.get("required")),
            "Primærnøkkel": bool(p.get("primaryKey")),
            # Ukjent eller manglende verdi faller tilbake til samme standard som
            # en ny rad får, slik at nedtrekksmenyen alltid har en gyldig verdi.
            "Klassifisering": _label_for(
                p.get("classification", ""), CLASSIFICATION_LABELS,
                COLUMN_SPEC["Klassifisering"]),
            "Personopplysning": _label_for(
                cp.get("personopplysning", ""), PERSONAL_DATA_LABELS,
                COLUMN_SPEC["Personopplysning"]),
            "Personidentifikator": _label_for(
                cp.get("personidentifikator", ""), IDENTIFIER_LABELS,
                COLUMN_SPEC["Personidentifikator"]),
        })
    return pd.DataFrame(rows) if rows else empty_columns()


# ── Kontraktsbygging ──────────────────────────────────────────────────────────

def build_contract(f: dict, df: pd.DataFrame) -> dict:
    """Skjemaverdiene → en ODCS-kontrakt. Tomme valgfrie felter utelates."""
    contract: dict = {
        "apiVersion": "v3.1.0",
        "kind": "DataContract",
        "id": f["id"].strip(),
        "name": f["name"].strip(),
        "version": f["version"].strip(),
        "status": f["status"],
        "domain": f["domain"].strip(),
        "tenant": f["tenant"].strip(),
        "description": {"purpose": f["purpose"].strip()},
    }
    for key, val in (("usage", f["usage"]), ("limitations", f["limitations"])):
        if val.strip():
            contract["description"][key] = val.strip()

    contract["team"] = {
        "name": f["team_name"].strip(),
        "members": [{"username": f["owner"].strip(), "role": "Owner"}],
    }
    if f["steward"].strip():
        contract["team"]["members"].append(
            {"username": f["steward"].strip(), "role": "Data Steward"}
        )

    contract["support"] = [
        {"channel": f["email"].strip(), "tool": "email",
         "url": f"mailto:{f['email'].strip()}"}
    ]
    if f["slack"].strip():
        contract["support"].append({"channel": f["slack"].strip(), "tool": "slack"})

    contract["servers"] = [{
        "server": "production",
        "type": "snowflake",
        "environment": "prod",
        "account": f["account"].strip(),
        "warehouse": f["warehouse"].strip(),
        "database": f["database"].strip(),
        "schema": f["db_schema"].strip(),
    }]

    dataset: dict = {
        "name": f["dataset_name"].strip(),
        "description": f["dataset_desc"].strip(),
        "properties": columns_to_yaml(df),
    }
    if f["physical_name"].strip():
        dataset["physicalName"] = f["physical_name"].strip()
    if f["granularity"].strip():
        dataset["dataGranularityDescription"] = f["granularity"].strip()
    if f["row_count_rule"]:
        dataset["quality"] = [{
            "metric": "rowCount",
            "mustBeGreaterThan": 0,
            "dimension": "completeness",
            "severity": "error",
            "description": "Tabellen skal ikke være tom.",
        }]
    contract["schema"] = [dataset]

    slas = []
    if f["latency"]:
        slas.append({"property": "latency", "value": int(f["latency"]),
                     "unit": "h", "driver": "analytics"})
    if f["retention"]:
        slas.append({"property": "retention", "value": int(f["retention"]),
                     "unit": "y", "driver": "regulatory"})
    if f["availability"]:
        slas.append({"property": "availability", "value": float(f["availability"]),
                     "unit": "percent"})
    if slas:
        contract["slaProperties"] = slas

    contract["customProperties"] = [
        {"property": "dataClassification",
         "value": CLASSIFICATION_LABELS.get(f["contract_classification"], "")}
    ]

    if f["implementation_url"].strip():
        contract["authoritativeDefinitions"] = [{
            "type": "implementation",
            "url": f["implementation_url"].strip(),
            "description": "Koden som produserer datasettet.",
        }]
    return contract


def strictest_column_label(df: pd.DataFrame) -> str | None:
    """Strengeste klassifisering blant kolonnene — brukes til å foreslå nivå."""
    ranks = [
        CLASSIFICATION_RANK[v]
        for v in (CLASSIFICATION_LABELS.get(str(r.get("Klassifisering")))
                  for _, r in df.iterrows()
                  if str(r.get("Kolonnenavn") or "").strip())
        if v in CLASSIFICATION_RANK
    ]
    if not ranks:
        return None
    strictest = max(ranks)
    return next(k for k, v in CLASSIFICATION_LABELS.items()
                if CLASSIFICATION_RANK[v] == strictest)


# ── Oppsett ───────────────────────────────────────────────────────────────────

st.set_page_config(page_title="Datakontrakt-utfyller", page_icon="📄", layout="wide")

if "columns" not in st.session_state:
    st.session_state.columns = empty_columns()
if "loaded" not in st.session_state:
    st.session_state.loaded = {}
# Valideringen er en handling, ikke en tilstand skjemaet starter i. Når den først
# er utløst holder den seg levende, slik at brukeren ser feilene forsvinne mens
# de rettes.
if "verified" not in st.session_state:
    st.session_state.verified = False

st.title("📄 Datakontrakt-utfyller")
st.caption(
    "Fyll ut skjemaet og last ned en ferdig ODCS-datakontrakt. Når du er ferdig, "
    "trykk **Verifiser** nederst — da sjekkes kontrakten mot de samme reglene "
    "som CI bruker."
)

# Statuspanelet bor i sidepanelet, men fylles først etter at skjemaet er lest.
# Vi reserverer plassen her og skriver inn i den nederst — det gir skjemaet full
# bredde, slik at kolonnetabellen med sine ni felter faktisk er lesbar.
status_slot = st.sidebar.container()
st.sidebar.divider()

# ── Sidepanel: last inn eksisterende kontrakt ─────────────────────────────────
with st.sidebar:
    st.header("Åpne en kontrakt")
    st.caption("Skal du endre en kontrakt som finnes? Last den inn her.")

    existing = sorted(p.name for p in CONTRACTS_DIR.glob("*.yml")
                      if not p.name.startswith("_")) if CONTRACTS_DIR.exists() else []
    if existing:
        valgt = st.selectbox("Fra contracts/", ["—"] + existing)
        if valgt != "—" and st.button("Last inn", use_container_width=True):
            data = yaml.safe_load((CONTRACTS_DIR / valgt).read_text()) or {}
            st.session_state.loaded = data
            props = (data.get("schema") or [{}])[0].get("properties") or []
            st.session_state.columns = columns_from_yaml(props)
            st.session_state.verified = False
            st.rerun()

    opplastet = st.file_uploader("…eller last opp en YAML-fil", type=["yml", "yaml"])
    if opplastet is not None and st.button("Bruk opplastet fil", use_container_width=True):
        data = yaml.safe_load(opplastet.getvalue()) or {}
        st.session_state.loaded = data
        props = (data.get("schema") or [{}])[0].get("properties") or []
        st.session_state.columns = columns_from_yaml(props)
        st.session_state.verified = False
        st.rerun()

    if st.session_state.loaded:
        st.success(f"Lastet: {st.session_state.loaded.get('name', '(uten navn)')}")
        if st.button("Tøm skjemaet", use_container_width=True):
            st.session_state.loaded = {}
            st.session_state.columns = empty_columns()
            st.session_state.verified = False
            st.rerun()

    st.divider()
    st.markdown(
        "**Hjelp**\n\n"
        "- Behold status `draft` til leveransen er i produksjon.\n"
        "- Alle kolonner må kategoriseres — det er ikke valgfritt.\n"
        "- Klassifiseringen av leveransen kan ikke være mildere enn "
        "den strengeste kolonnen.\n\n"
        "Se README for hele regelverket."
    )

L = st.session_state.loaded
_desc = L.get("description") or {}
_team = L.get("team") or {}
_members = _team.get("members") or []
_support = L.get("support") or []
_server = (L.get("servers") or [{}])[0]
_dataset = (L.get("schema") or [{}])[0]
_slas = {s.get("property"): s for s in (L.get("slaProperties") or [])
         if isinstance(s, dict)}
_custom = {c.get("property"): c.get("value")
           for c in (L.get("customProperties") or []) if isinstance(c, dict)}
_authdefs = {a.get("type"): a.get("url") for a in (L.get("authoritativeDefinitions") or [])
             if isinstance(a, dict)}


def _member(role: str) -> str:
    return next((str(m.get("username", "")) for m in _members
                 if isinstance(m, dict) and role in str(m.get("role", ""))), "")


def _channel(tool: str) -> str:
    return next((str(c.get("channel", "")) for c in _support
                 if isinstance(c, dict) and str(c.get("tool", "")).lower() == tool), "")


f: dict = {}

# Skjemaet får hele hovedflaten. Alternativet — skjema og status side om side —
# klemte kolonnetabellen så smal at klassifisering og kategorisering falt utenfor.
with st.container():
    # ── 1. Hva er dette? ──────────────────────────────────────────────────────
    st.subheader("1. Hva er dette?")
    c1, c2 = st.columns(2)
    f["name"] = c1.text_input(
        "Teknisk navn *", value=L.get("name", ""),
        placeholder="kunde_serving_v1",
        help="Navnet utviklere bruker. Små bokstaver og understrek.")
    f["domain"] = c2.text_input(
        "Forretningsdomene *", value=L.get("domain", ""),
        placeholder="risiko", help="Hvilket område i virksomheten eier dette?")
    f["id"] = st.text_input(
        "Unik ID *", value=L.get("id", ""),
        placeholder="urn:datacontract:dp-mitt-team:kunde",
        help="Kontraktens permanente identifikator. Endres aldri.")
    f["purpose"] = st.text_area(
        "Hva inneholder dataproduktet, og hva er det laget for? *",
        value=_desc.get("purpose", ""), height=90,
        placeholder="Kundeopplysninger for risikomodellering. Én rad per kunde …")

    c1, c2, c3 = st.columns(3)
    f["version"] = c1.text_input("Versjon *", value=L.get("version", "0.1.0"),
                                 help="MAJOR.MINOR.PATCH")
    status_valg = ["draft", "proposed", "active", "deprecated", "retired"]
    lagret_status = L.get("status", "draft")
    f["status"] = c2.selectbox(
        "Status *", status_valg,
        index=status_valg.index(lagret_status) if lagret_status in status_valg else 0,
        help="Behold 'draft' til leveransen er i produksjon.")
    f["tenant"] = c3.text_input("Organisasjon", value=L.get("tenant", "SB1U"))

    with st.expander("Valgfritt: bruk og begrensninger"):
        f["usage"] = st.text_area("Hvordan er det tenkt brukt?",
                                  value=_desc.get("usage", ""), height=70)
        f["limitations"] = st.text_area(
            "Hva kan dataen IKKE brukes til?",
            value=_desc.get("limitations", ""), height=70,
            placeholder="Kun aktive kunder. Historikk finnes ikke her …")

    # ── 2. Hvem eier det? ─────────────────────────────────────────────────────
    st.subheader("2. Hvem eier det?")
    c1, c2 = st.columns(2)
    f["team_name"] = c1.text_input("Teamnavn *", value=_team.get("name", ""),
                                   placeholder="Example Data Team")
    f["owner"] = c2.text_input("E-post til produkteier *", value=_member("Owner"),
                               placeholder="produkteier@example.com",
                               help="Den som svarer for leveransen.")
    c1, c2 = st.columns(2)
    f["email"] = c1.text_input("Team-e-post *", value=_channel("email"),
                               placeholder="mitt-team@example.com",
                               help="Adressen konsumenter kan kontakte.")
    f["steward"] = c2.text_input("E-post til forvalter", value=_member("Data Steward"),
                                 placeholder="forvalter@example.com")
    f["slack"] = st.text_input("Slack-kanal", value=_channel("slack"),
                               placeholder="#dp-mitt-team")

    # ── 3. Hvor ligger dataen? ────────────────────────────────────────────────
    st.subheader("3. Hvor ligger dataen?")
    c1, c2 = st.columns(2)
    f["account"] = c1.text_input("Snowflake-konto *", value=_server.get("account", ""),
                                 placeholder="example-account")
    f["warehouse"] = c2.text_input("Warehouse *", value=_server.get("warehouse", ""),
                                   placeholder="EXAMPLE_WH")
    c1, c2 = st.columns(2)
    f["database"] = c1.text_input("Database *", value=_server.get("database", ""),
                                  placeholder="EXAMPLE_DB__PROD__MAIN")
    f["db_schema"] = c2.text_input("Skjema *", value=_server.get("schema", ""),
                                   placeholder="SERVING")

    # ── 4. Hva leveres? ───────────────────────────────────────────────────────
    st.subheader("4. Hva leveres?")
    c1, c2 = st.columns(2)
    f["dataset_name"] = c1.text_input("Navn på datasettet *",
                                      value=_dataset.get("name", ""),
                                      placeholder="kunde")
    f["physical_name"] = c2.text_input("Tabellnavn i Snowflake",
                                       value=_dataset.get("physicalName", ""),
                                       placeholder="KUNDE")
    f["dataset_desc"] = st.text_area(
        "Hva inneholder tabellen? Hva representerer én rad? *",
        value=_dataset.get("description", ""), height=70,
        placeholder="Én rad per kunde med siste gyldige status.")

    st.markdown("**Kolonner** — én rad per kolonne. Alle tre valgene til høyre er påkrevd.")
    st.caption(
        "Klassifisering sier hvor beskyttet kolonnen skal være. "
        "De to siste er kategoriseringen: om innholdet er en personopplysning, "
        "og om det kan brukes til å identifisere en person. "
        "Se forklaringen under tabellen."
    )
    # Bredder er satt eksplisitt: de tre nedtrekksmenyene er poenget med tabellen
    # og må være synlige uten å skrolle sidelengs, så tekstfeltene får ikke
    # bredden de ellers ville tatt.
    redigert = st.data_editor(
        st.session_state.columns,
        num_rows="dynamic",
        use_container_width=True,
        key="kolonne_editor",
        column_config={
            "Kolonnenavn": st.column_config.TextColumn(required=False, width="medium"),
            "Forretningsnavn": st.column_config.TextColumn(
                help="Hva kolonnen heter for folk, f.eks. «Kundeidentifikator»",
                width="small"),
            "Beskrivelse": st.column_config.TextColumn(width="small"),
            "Datatype": st.column_config.SelectboxColumn(
                options=list(VALID_LOGICAL_TYPES), width="small"),
            "Påkrevd": st.column_config.CheckboxColumn(
                help="Kan kolonnen aldri være tom?", width="small"),
            "Primærnøkkel": st.column_config.CheckboxColumn(
                help="Er kolonnen del av det som gjør raden unik?", width="small"),
            "Klassifisering": st.column_config.SelectboxColumn(
                options=list(CLASSIFICATION_LABELS), width="small",
                help="Hvor beskyttet skal kolonnen være?"),
            "Personopplysning": st.column_config.SelectboxColumn(
                options=list(PERSONAL_DATA_LABELS), width="small",
                help="Er innholdet en personopplysning etter GDPR?"),
            "Personidentifikator": st.column_config.SelectboxColumn(
                options=list(IDENTIFIER_LABELS), width="medium",
                help="Kan innholdet brukes til å identifisere en person?"),
        },
    )
    st.session_state.columns = redigert

    with st.expander("Hva betyr valgene i tabellen?"):
        for tittel, verdier in FORKLARINGER.items():
            st.markdown(
                f"**{tittel}**\n\n"
                + "\n".join(f"- **{navn}** — {forklaring}" for navn, forklaring in verdier)
            )

    with st.expander("Valgfritt: granularitet og kvalitetsregel"):
        f["granularity"] = st.text_input(
            "Granularitet", value=_dataset.get("dataGranularityDescription", ""),
            placeholder="Én rad per kunde_id")
        f["row_count_rule"] = st.checkbox(
            "Legg til kvalitetsregel: tabellen skal ikke være tom",
            value=bool(_dataset.get("quality")))

    # ── 5. Klassifisering av leveransen ───────────────────────────────────────
    st.subheader("5. Klassifisering av leveransen")
    forslag = strictest_column_label(redigert)
    lagret_cls = _label_for(_custom.get("dataClassification", ""),
                            CLASSIFICATION_LABELS, "")
    valgt_cls = lagret_cls or forslag or list(CLASSIFICATION_LABELS)[2]
    f["contract_classification"] = st.selectbox(
        "Samlet nivå for hele leveransen *", list(CLASSIFICATION_LABELS),
        index=list(CLASSIFICATION_LABELS).index(valgt_cls),
        help="Kan ikke være mildere enn den strengeste kolonnen.")
    st.caption(" · ".join(f"**{navn}**: {forklaring}"
                          for navn, forklaring in FORKLARINGER["Klassifisering"]))
    if forslag and forslag != f["contract_classification"]:
        r_valgt = CLASSIFICATION_RANK[CLASSIFICATION_LABELS[f["contract_classification"]]]
        r_forslag = CLASSIFICATION_RANK[CLASSIFICATION_LABELS[forslag]]
        if r_valgt < r_forslag:
            st.warning(f"Strengeste kolonne er «{forslag}». Nivået må minst være det.")

    with st.expander("Valgfritt: SLA og referanse til koden (påkrevd for status active)"):
        c1, c2, c3 = st.columns(3)
        f["latency"] = c1.number_input(
            "Maks alder på dataen (timer)", min_value=0, step=1,
            value=int(_slas.get("latency", {}).get("value") or 0),
            help="0 = ikke satt ennå")
        f["retention"] = c2.number_input(
            "Oppbevaringstid (år)", min_value=0, step=1,
            value=int(_slas.get("retention", {}).get("value") or 0),
            help="0 = ikke satt ennå")
        f["availability"] = c3.number_input(
            "Tilgjengelighet (%)", min_value=0.0, max_value=100.0, step=0.1,
            value=float(_slas.get("availability", {}).get("value") or 0.0),
            help="Hvor stor andel av tiden leveransen skal være tilgjengelig. "
                 "0 = ikke satt ennå")
        f["implementation_url"] = st.text_input(
            "Lenke til koden som produserer dataen",
            value=_authdefs.get("implementation", "") or "",
            placeholder="https://github.com/…/models/serving/kunde.sql")

# ── Verifisering ──────────────────────────────────────────────────────────────
# Kontrakten bygges på hver rerun — det er billig og gir YAML-visningen noe å
# vise — men valideringen presenteres ikke før brukeren har bedt om den.
contract = build_contract(f, redigert)
yaml_text = yaml.safe_dump(contract, allow_unicode=True, sort_keys=False, width=88)
filnavn = f"{(f['name'] or 'datakontrakt').strip()}.yml"

st.divider()
st.subheader("Verifiser kontrakten")
st.caption(
    "Når du er ferdig med å fylle ut, sjekk kontrakten mot regelverket. "
    "Det er samme kontroll som kjører i CI når kontrakten legges inn i repoet."
)
if st.button("✓ Verifiser", type="primary"):
    st.session_state.verified = True

if not st.session_state.verified:
    # Ingen validering ennå: ikke bygg opp en liste over feil i et skjema
    # brukeren fortsatt er i gang med å fylle ut.
    st.info("Kontrakten er ikke verifisert ennå. Trykk **Verifiser** for å se "
            "hva som mangler før den kan brukes.")
    result = None
else:
    result = validate_contract(copy.deepcopy(contract),
                              Path(f"{f['name'] or 'kontrakt'}.yml"))

    if f["status"] in ("proposed", "draft"):
        st.info(
            "Status er **draft**. Krav som forutsetter en ferdig leveranse "
            "(SLA, kvalitetsregler, lenke til koden) er advarsler nå, og blir "
            "blokkerende når du setter status til **active**."
        )

    if result.errors:
        st.subheader(f"Må rettes ({len(result.errors)})")
        for finding in result.errors:
            st.markdown(
                f"<div style='border-left:3px solid #d13438;padding:.4rem .7rem;"
                f"margin-bottom:.4rem;background:#fdf2f2'>"
                f"<b>{DIM_LABELS.get(finding.dimension, finding.dimension)}</b> — "
                f"{finding.message}<br>"
                f"<code style='font-size:.8em;color:#666'>{finding.field_path}</code>"
                f"</div>",
                unsafe_allow_html=True,
            )

    if result.warnings:
        with st.expander(f"Anbefalinger ({len(result.warnings)})"):
            for finding in result.warnings:
                st.markdown(
                    f"**{DIM_LABELS.get(finding.dimension, finding.dimension)}** — "
                    f"{finding.message}  \n`{finding.field_path}`"
                )

with st.expander("Se YAML-en"):
    st.code(yaml_text, language="yaml")

# ── Statuspanel ───────────────────────────────────────────────────────────────
# Skrives inn i plassen som ble reservert i sidepanelet øverst. Tallene vises
# bare når kontrakten er verifisert; før det er de bare et mål på hvor langt
# brukeren har kommet i utfyllingen, og det er ikke det de ser ut som.
with status_slot:
    st.subheader("Status")

    if result is None:
        st.caption("Ikke verifisert ennå.")
        st.button("✓ Verifiser", key="verify_sidebar", use_container_width=True,
                  on_click=lambda: st.session_state.update(verified=True))
        st.caption("Nedlasting åpner seg når kontrakten er verifisert uten feil.")
    else:
        c1, c2 = st.columns(2)
        c1.metric("Feil", len(result.errors))
        c2.metric("Advarsler", len(result.warnings))
        st.progress(result.score / 100, text=f"Score {result.score}/100")

        if result.errors:
            st.error(f"{len(result.errors)} ting må rettes.")
        else:
            st.success("Kontrakten er gyldig.")

        st.download_button(
            "⬇️ Last ned kontrakten", data=yaml_text.encode("utf-8"),
            file_name=filnavn, mime="application/x-yaml",
            use_container_width=True, type="primary",
            disabled=bool(result.errors))
        if result.errors:
            st.caption("Nedlasting åpner seg når feilene er rettet — se listen "
                       "under skjemaet.")
        else:
            st.caption(f"Legg filen i `contracts/` og commit den. Navn: `{filnavn}`")
