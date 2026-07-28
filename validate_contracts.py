#!/usr/bin/env python3
"""
Datakontrakt-validator: leser alle YAML-kontrakter i contracts/, validerer dem
mot ODCS v3.1.0 + SB1U-profilen, og genererer en HTML-statusrapport.

Spesifikasjon: https://bitol-io.github.io/open-data-contract-standard/latest/

Validerer de fem dimensjonene SB1U krever at en datakontrakt dekker:
  1. Eierskap       — team.members (Owner, Data Steward), support-kanaler
  2. Klassifisering — dataCategory, personvern, oppbevaringstid
  3. Innhold        — schema/properties, grensesnitt (servers), datakvalitet, stabilitet
  4. Semantikk      — hva dataen betyr, og dataavstamming til kildene
  5. Versjonering   — semantisk versjon, varslingsfrist, livsløp (GA/EOS/EOL)

ODCS definerer ikke felter for alle SB1U-spesifikke styringskrav (datakategori,
GDPR-rettsgrunnlag, varslingsfrist). Disse ligger i customProperties med faste
navn — se SB1U_CUSTOM_PROPS og datakontrakt_mal.yml.
"""

import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml


# ── Datastrukturer ─────────────────────────────────────────────────────────────

@dataclass
class ValidationFinding:
    severity: str   # "error" | "warning"
    dimension: str  # nøkkel i DIM_LABELS
    field_path: str
    message: str


@dataclass
class ContractResult:
    file: Path
    contract_id: str
    title: str
    status: str
    version: str
    owner_team: str
    domain: str = ""
    findings: list[ValidationFinding] = field(default_factory=list)

    @property
    def errors(self) -> list[ValidationFinding]:
        return [f for f in self.findings if f.severity == "error"]

    @property
    def warnings(self) -> list[ValidationFinding]:
        return [f for f in self.findings if f.severity == "warning"]

    @property
    def is_valid(self) -> bool:
        return len(self.errors) == 0

    @property
    def score(self) -> int:
        """0–100 basert på antall feil og advarsler."""
        if not self.findings:
            return 100
        penalty = len(self.errors) * 15 + len(self.warnings) * 5
        return max(0, 100 - penalty)


# ── Valideringsregler ─────────────────────────────────────────────────────────

def _get(obj: Any, *keys, default="") -> Any:
    for k in keys:
        if not isinstance(obj, dict):
            return default
        obj = obj.get(k, default)
    return obj


def _todo(val: Any) -> bool:
    """Tomt, uutfylt eller fortsatt en TODO-plassholder fra malen."""
    if val is None or val == "" or val == [] or val == {}:
        return True
    return "TODO" in str(val)


def _custom_props(data: dict) -> dict[str, Any]:
    """Flat oppslagstabell av ODCS customProperties: [{property, value}] → {property: value}.

    ODCS tillater customProperties på både kontrakts- og schema-objektnivå, så
    denne tar imot begge.
    """
    props = data.get("customProperties") or []
    if not isinstance(props, list):
        return {}
    return {
        p["property"]: p.get("value")
        for p in props
        if isinstance(p, dict) and p.get("property")
    }


def _cat_rank(val: Any) -> int | None:
    """Konfidensialitetsrangering for en kategori, eller None hvis den ikke har en.

    `personal_data` har med hensikt ingen rangering — se PERSONAL_DATA_CATEGORY.
    """
    return CATEGORY_RANK.get(str(val))


def _sla_props(data: dict) -> dict[str, dict]:
    """Oppslagstabell av slaProperties på property-navn. Siste oppføring vinner."""
    props = data.get("slaProperties") or []
    if not isinstance(props, list):
        return {}
    return {
        p["property"]: p
        for p in props
        if isinstance(p, dict) and p.get("property")
    }


# ODCS-enum for status (fundamentals). "proposed" kom inn i v3.1.0.
VALID_STATUS = ("proposed", "draft", "active", "deprecated", "retired")

# ODCS-enum for logicalType (schema).
VALID_LOGICAL_TYPES = (
    "string", "date", "timestamp", "time", "number", "integer", "object", "array", "boolean",
)

# SB1U-interne konfidensialitetsnivåer, ordnet fra minst til mest streng.
# `classification` er fritekst i ODCS, så både listen og rangeringen er vår egen
# innsnevring. Rangeringen brukes til å sjekke at en klassifisering aldri er
# mindre streng enn innholdet den dekker.
CATEGORY_RANK = {
    "public":       0,
    "internal":     1,
    "confidential": 2,
    "sensitive":    3,
}

# `personal_data` er ikke et konfidensialitetsnivå, men en uavhengig akse:
# persondata kan være både internal og sensitive. Den er derfor holdt utenfor
# rangeringen — ellers ville én fødselsdato tvunget hele datasettet til å miste
# konfidensialitetsnivået sitt. Konsekvensen håndheves via containsPersonalData.
PERSONAL_DATA_CATEGORY = "personal_data"
VALID_CATEGORIES = tuple(CATEGORY_RANK) + (PERSONAL_DATA_CATEGORY,)

# customProperties-navn som SB1U-profilen krever. Endres kun sammen med malen.
SB1U_CUSTOM_PROPS = {
    "category":         "dataCategory",
    "pii":              "containsPersonalData",
    "gdpr":             "gdprLegalBasis",
    "github_team":      "githubTeam",
    "breaking_notice":  "breakingChangeNoticeDays",
}

# Minimum varslingsfrist (dager) før en breaking change kan settes i produksjon.
# Konsumenter må ha reell tid til å tilpasse seg.
MIN_BREAKING_NOTICE_DAYS = 30

# authoritativeDefinitions.type-verdier som ODCS definerer.
VALID_AUTH_DEF_TYPES = (
    "businessDefinition", "videoTutorial", "transformationImplementation",
    "implementation", "canonical", "privacy-statement", "schema",
)

# Semantisk versjon — kontrakten må kunne versjonshåndteres maskinelt.
SEMVER_RE = re.compile(r"^\d+\.\d+\.\d+")


def _classification_hint(level: str) -> str:
    """Feilmelding for `classification` plassert der ODCS ikke tillater det.

    ODCS definerer `classification` kun på property-nivå (kolonner). Både
    kontraktsroten og schema-objekter avviser ukjente felter i ODCS' eget
    JSON-skjema (`additionalProperties: false` / `unevaluatedProperties: false`),
    så en feilplassert `classification` gjør kontrakten ugyldig — ikke bare
    uvanlig. SB1U uttrykker kategori på disse nivåene som customProperty.
    """
    return (
        f"ODCS tillater ikke 'classification' på {level} — feltet finnes kun på "
        f"kolonner (schema[].properties[].classification). Bruk customProperty "
        f"'{SB1U_CUSTOM_PROPS['category']}' på dette nivået i stedet."
    )


def validate_contract(data: dict, filepath: Path) -> ContractResult:
    findings: list[ValidationFinding] = []

    def err(dim: str, path: str, msg: str):
        findings.append(ValidationFinding("error", dim, path, msg))

    def warn(dim: str, path: str, msg: str):
        findings.append(ValidationFinding("warning", dim, path, msg))

    custom = _custom_props(data)
    slas = _sla_props(data)

    contract_id = data.get("id", "")
    name = data.get("name", "")
    status = data.get("status", "")
    version = data.get("version", "")

    # ── ODCS-header ────────────────────────────────────────────────────────────
    api_version = str(data.get("apiVersion", ""))
    if not api_version:
        err("innhold", "apiVersion", "Mangler apiVersion. Forventer ODCS, f.eks. 'v3.1.0'.")
    elif not api_version.startswith("v3."):
        err("innhold", "apiVersion",
            f"apiVersion '{api_version}' er ikke ODCS v3. Forventer f.eks. 'v3.1.0'. "
            "Merk at 'datacontract.com/...' er en annen standard.")

    if data.get("kind") != "DataContract":
        err("innhold", "kind",
            f"kind må være 'DataContract', ikke '{data.get('kind', '')}'.")

    # ── Fundamentals ───────────────────────────────────────────────────────────
    if _todo(contract_id):
        err("innhold", "id", "Mangler unik kontrakt-ID (id).")
    if _todo(name):
        err("innhold", "name", "Mangler teknisk navn (name).")
    if status not in VALID_STATUS:
        err("innhold", "status",
            f"Ugyldig status '{status}'. Gyldige verdier: {', '.join(VALID_STATUS)}.")

    description = data.get("description") or {}
    if not isinstance(description, dict):
        err("innhold", "description",
            "description må være et objekt med purpose/usage/limitations (ODCS v3).")
    else:
        if _todo(description.get("purpose")):
            err("innhold", "description.purpose",
                "Mangler formålsbeskrivelse (description.purpose).")
        if _todo(description.get("usage")):
            warn("innhold", "description.usage",
                 "Anbefalt: beskriv tenkt bruk (description.usage).")
        if _todo(description.get("limitations")):
            warn("innhold", "description.limitations",
                 "Anbefalt: beskriv kjente begrensninger (description.limitations).")

    if _todo(data.get("domain")):
        warn("innhold", "domain", "Anbefalt: oppgi forretningsdomene (domain).")

    # ── VERSJONERING ──────────────────────────────────────────────────────────
    # Kontrakten skal kunne versjonshåndteres maskinelt, og konsumenter skal
    # kjenne livsløpet til leveransen før de tar avhengigheter på den.
    if _todo(version):
        err("versjonering", "version", "Mangler versjon (version).")
    elif not SEMVER_RE.match(str(version)):
        err("versjonering", "version",
            f"Versjon '{version}' er ikke semantisk (MAJOR.MINOR.PATCH). "
            "Semver er nødvendig for å skille breaking fra bakoverkompatible endringer.")

    notice_key = SB1U_CUSTOM_PROPS["breaking_notice"]
    notice = custom.get(notice_key)
    if _todo(notice):
        err("versjonering", f"customProperties.{notice_key}",
            f"Mangler varslingsfrist for breaking changes "
            f"(customProperty '{notice_key}', minst {MIN_BREAKING_NOTICE_DAYS} dager).")
    elif not isinstance(notice, int) or isinstance(notice, bool):
        err("versjonering", f"customProperties.{notice_key}",
            f"'{notice_key}' må være et heltall (antall dager), ikke '{notice}'.")
    elif notice < MIN_BREAKING_NOTICE_DAYS:
        err("versjonering", f"customProperties.{notice_key}",
            f"Varslingsfrist på {notice} dager er kortere enn minimumskravet på "
            f"{MIN_BREAKING_NOTICE_DAYS} dager. Konsumenter må ha tid til å tilpasse seg.")

    # Livsløp uttrykkes i ODCS som slaProperties: generalAvailability,
    # endOfSupport, endOfLife. En oppføring med uutfylt value teller ikke.
    def _lifecycle_date(prop: str) -> Any:
        entry = slas.get(prop)
        if not entry or _todo(entry.get("value")):
            return None
        return entry.get("value")

    if status == "active" and not _lifecycle_date("generalAvailability"):
        warn("versjonering", "slaProperties[generalAvailability].value",
             "Anbefalt for aktive kontrakter: oppgi slaProperty 'generalAvailability' "
             "(når leveransen ble/blir allment tilgjengelig).")

    if status in ("deprecated", "retired"):
        # Ved avvikling er livsløpsdatoene selve avviklingsplanen konsumentene
        # planlegger etter — da er de ikke lenger valgfrie.
        for prop, label in (("endOfSupport", "slutt på support"),
                            ("endOfLife", "endelig avvikling")):
            if not _lifecycle_date(prop):
                err("versjonering", f"slaProperties[{prop}].value",
                    f"Status er '{status}' — da må dato for {label} oppgis "
                    f"(slaProperty '{prop}').")
    else:
        for prop in ("endOfSupport", "endOfLife"):
            if not _lifecycle_date(prop):
                warn("versjonering", f"slaProperties[{prop}].value",
                     f"Anbefalt: oppgi slaProperty '{prop}' så konsumenter kjenner "
                     "leveransens livsløp.")

    eos, eol = _lifecycle_date("endOfSupport"), _lifecycle_date("endOfLife")
    if eos and eol and str(eol) < str(eos):
        err("versjonering", "slaProperties[endOfLife].value",
            f"endOfLife ({eol}) er før endOfSupport ({eos}). "
            "Leveransen kan ikke avvikles før supporten opphører.")

    # ── SEMANTIKK OG DATAAVSTAMMING ───────────────────────────────────────────
    # Kontrakten skal fortelle hva dataen betyr, ikke bare hvordan den ser ut,
    # og vise hvor den kommer fra.
    auth_defs = data.get("authoritativeDefinitions") or []
    if not isinstance(auth_defs, list):
        err("semantikk", "authoritativeDefinitions",
            "authoritativeDefinitions må være en liste av {type, url}.")
        auth_defs = []
    else:
        for i, ad in enumerate(auth_defs):
            if not isinstance(ad, dict):
                err("semantikk", f"authoritativeDefinitions[{i}]",
                    "Ugyldig oppføring (må være YAML-objekt med type og url).")
            elif _todo(ad.get("url")):
                err("semantikk", f"authoritativeDefinitions[{i}].url",
                    f"Referanse #{i+1} mangler url.")
            elif ad.get("type") not in VALID_AUTH_DEF_TYPES:
                warn("semantikk", f"authoritativeDefinitions[{i}].type",
                     f"Ukjent type '{ad.get('type')}'. ODCS definerer: "
                     f"{', '.join(VALID_AUTH_DEF_TYPES)}.")

    auth_types = {
        ad.get("type") for ad in auth_defs
        if isinstance(ad, dict) and not _todo(ad.get("url"))
    }
    if "implementation" not in auth_types:
        err("semantikk", "authoritativeDefinitions",
            "Mangler dataavstamming oppstrøms: legg til en authoritativeDefinition "
            "med type 'implementation' som peker på koden/modellen som produserer dataen.")
    if "canonical" not in auth_types:
        warn("semantikk", "authoritativeDefinitions",
             "Anbefalt: oppgi type 'canonical' — hvor den gjeldende versjonen "
             "av kontrakten bor.")
    if "businessDefinition" not in auth_types:
        warn("semantikk", "authoritativeDefinitions",
             "Anbefalt: oppgi type 'businessDefinition' — lenke til begrepsapparat "
             "eller definisjonskatalog som forklarer hva dataen betyr.")

    # ── 1. EIERSKAP ────────────────────────────────────────────────────────────
    team = data.get("team") or {}
    owner_team = ""

    if not isinstance(team, dict) or not team:
        err("eierskap", "team", "Mangler team-blokk (team) med eier og forvalter.")
    else:
        owner_team = "" if _todo(team.get("name")) else str(team.get("name"))
        if not owner_team:
            err("eierskap", "team.name", "Mangler teamnavn (team.name).")

        members = team.get("members") or []
        if not isinstance(members, list) or not members:
            err("eierskap", "team.members",
                "Mangler teammedlemmer (team.members) — minst én med role 'Owner'.")
        else:
            def _has_role(needle: str) -> bool:
                return any(
                    isinstance(m, dict)
                    and needle in str(m.get("role", "")).lower()
                    and not _todo(m.get("username"))
                    for m in members
                )

            if not _has_role("owner"):
                err("eierskap", "team.members",
                    "Ingen medlem med role 'Owner' og utfylt username. "
                    "Eierskap må være entydig plassert.")
            if not _has_role("steward"):
                warn("eierskap", "team.members",
                     "Anbefalt: oppgi et medlem med role 'Data Steward'.")

            for i, m in enumerate(members):
                if not isinstance(m, dict):
                    err("eierskap", f"team.members[{i}]",
                        "Ugyldig medlem-oppføring (må være YAML-objekt).")
                elif _todo(m.get("username")):
                    err("eierskap", f"team.members[{i}].username",
                        f"Medlem #{i+1} mangler username (e-post eller brukernavn).")

    support = data.get("support") or []
    if not isinstance(support, list) or not support:
        err("eierskap", "support",
            "Mangler kontaktkanaler (support) — minst én e-postkanal er påkrevd.")
    else:
        channels = [c for c in support if isinstance(c, dict) and not _todo(c.get("channel"))]
        if not channels:
            err("eierskap", "support", "Ingen support-kanal har utfylt 'channel'.")
        elif not any(str(c.get("tool", "")).lower() == "email" for c in channels):
            err("eierskap", "support",
                "Mangler kontaktkanal med tool 'email'. Konsumenter må ha en e-postadresse.")
        if not any(str(c.get("tool", "")).lower() == "slack" for c in channels):
            warn("eierskap", "support", "Anbefalt: oppgi en Slack-kanal (tool: slack).")

    if _todo(custom.get(SB1U_CUSTOM_PROPS["github_team"])):
        warn("eierskap", f"customProperties.{SB1U_CUSTOM_PROPS['github_team']}",
             f"Anbefalt: legg til GitHub-team som customProperty "
             f"'{SB1U_CUSTOM_PROPS['github_team']}'.")

    # ── 2. KLASSIFISERING ─────────────────────────────────────────────────────
    # ODCS klassifiserer per kolonne (schema[].properties[].classification).
    # SB1U krever i tillegg en samlet datakategori og personvernstatus på
    # kontraktsnivå — disse ligger i customProperties.
    cat_key = f"customProperties.{SB1U_CUSTOM_PROPS['category']}"
    cat = custom.get(SB1U_CUSTOM_PROPS["category"])
    if _todo(cat):
        err("klassifisering", cat_key,
            f"Mangler datakategori (customProperty '{SB1U_CUSTOM_PROPS['category']}').")
    elif cat not in VALID_CATEGORIES:
        err("klassifisering", cat_key,
            f"Ugyldig kategori '{cat}'. Gyldige: {', '.join(VALID_CATEGORIES)}.")

    if "classification" in data:
        err("klassifisering", "classification", _classification_hint("kontraktsnivå"))

    pii_key = f"customProperties.{SB1U_CUSTOM_PROPS['pii']}"
    contains_pii = custom.get(SB1U_CUSTOM_PROPS["pii"])
    if contains_pii is None:
        err("klassifisering", pii_key,
            f"Mangler personvern-flagg (customProperty '{SB1U_CUSTOM_PROPS['pii']}': true/false).")
    elif not isinstance(contains_pii, bool):
        err("klassifisering", pii_key,
            f"'{SB1U_CUSTOM_PROPS['pii']}' må være true eller false, ikke '{contains_pii}'.")
    elif contains_pii is True:
        if _todo(custom.get(SB1U_CUSTOM_PROPS["gdpr"])):
            err("klassifisering", f"customProperties.{SB1U_CUSTOM_PROPS['gdpr']}",
                f"Persondata krever GDPR-rettsgrunnlag "
                f"(customProperty '{SB1U_CUSTOM_PROPS['gdpr']}').")

    # Oppbevaringstid uttrykkes i ODCS som slaProperties[property=retention].
    retention = slas.get("retention")
    if not retention:
        err("klassifisering", "slaProperties[retention]",
            "Mangler oppbevaringstid — legg til slaProperty med property 'retention'.")
    else:
        ret_val = retention.get("value")
        if _todo(ret_val):
            err("klassifisering", "slaProperties[retention].value",
                "Mangler verdi for oppbevaringstid (retention.value).")
        elif not isinstance(ret_val, (int, float)):
            err("klassifisering", "slaProperties[retention].value",
                f"retention.value må være et tall, ikke '{ret_val}'.")
        if _todo(retention.get("unit")):
            err("klassifisering", "slaProperties[retention].unit",
                "Mangler enhet for oppbevaringstid (retention.unit), f.eks. 'd' eller 'y'.")

    # ── 3. INNHOLD ────────────────────────────────────────────────────────────
    servers = data.get("servers") or []
    if not isinstance(servers, list) or not servers:
        err("innhold", "servers",
            "Mangler grensesnitt-konfig (servers) — ODCS v3 forventer en liste.")
    else:
        prod = next(
            (
                s for s in servers
                if isinstance(s, dict)
                and (str(s.get("environment", "")).lower() in ("prod", "production")
                     or str(s.get("server", "")).lower() in ("prod", "production"))
            ),
            None,
        )
        if prod is None:
            err("innhold", "servers",
                "Ingen produksjonsserver funnet. Sett environment: prod på minst én server.")
        else:
            required = ("type", "database", "schema")
            if str(prod.get("type", "")).lower() == "snowflake":
                required = ("type", "account", "warehouse", "database", "schema")
            for srv_field in required:
                if _todo(prod.get(srv_field)):
                    err("innhold", f"servers[{srv_field}]",
                        f"Mangler '{srv_field}' på produksjonsserveren.")

    schema_objects = data.get("schema") or []
    # Strengeste konfidensialitetsnivå observert nedover i kontrakten, brukt til å
    # sjekke at kategorien på kontraktsnivå dekker innholdet sitt.
    max_nested_rank: int | None = None
    max_nested_source = ""
    # Kolonner klassifisert som persondata — sjekkes mot containsPersonalData.
    personal_data_cols: list[str] = []

    if not isinstance(schema_objects, list) or not schema_objects:
        err("innhold", "schema",
            "Mangler datasett-definisjon (schema). ODCS v3 bruker 'schema', ikke 'models'.")
    else:
        for i, obj in enumerate(schema_objects):
            prefix = f"schema[{i}]"
            if not isinstance(obj, dict):
                err("innhold", prefix, "Ugyldig schema-oppføring (må være YAML-objekt).")
                continue

            obj_name = "" if _todo(obj.get("name")) else str(obj.get("name"))
            label = obj_name or f"#{i+1}"
            if not obj_name:
                err("innhold", f"{prefix}.name", f"Datasett #{i+1} mangler navn.")

            if _todo(obj.get("description")):
                err("innhold", f"{prefix}.description",
                    f"Datasett '{label}' mangler beskrivelse.")

            if _todo(obj.get("physicalName")):
                warn("innhold", f"{prefix}.physicalName",
                     f"Anbefalt: oppgi fysisk tabellnavn for '{label}' (physicalName).")

            props = obj.get("properties") or []
            if not isinstance(props, list) or not props:
                err("innhold", f"{prefix}.properties",
                    f"Datasett '{label}' mangler kolonner (properties).")
                continue

            valid_props = [p for p in props if isinstance(p, dict)]
            if len(valid_props) != len(props):
                err("innhold", f"{prefix}.properties",
                    f"Datasett '{label}' har kolonne-oppføringer som ikke er YAML-objekter.")
            if not valid_props:
                continue

            if not any(p.get("primaryKey") is True for p in valid_props):
                err("innhold", f"{prefix}.properties",
                    f"Datasett '{label}' mangler primærnøkkel "
                    "(ingen kolonne har primaryKey: true).")

            unnamed = [j for j, p in enumerate(valid_props) if _todo(p.get("name"))]
            if unnamed:
                err("innhold", f"{prefix}.properties",
                    f"Datasett '{label}': {len(unnamed)} kolonne(r) mangler navn.")

            undocumented = [
                str(p.get("name", "?")) for p in valid_props if _todo(p.get("description"))
            ]
            if undocumented:
                pct = len(undocumented) / len(valid_props) * 100
                report = err if pct > 50 else warn
                report("innhold", f"{prefix}.properties",
                       f"{len(undocumented)}/{len(valid_props)} kolonner mangler beskrivelse: "
                       f"{', '.join(undocumented[:5])}{'…' if len(undocumented) > 5 else ''}.")

            bad_types = [
                f"{p.get('name', '?')} ({p.get('logicalType')})"
                for p in valid_props
                if p.get("logicalType") not in VALID_LOGICAL_TYPES
            ]
            if bad_types:
                err("innhold", f"{prefix}.properties",
                    f"Ugyldig/manglende logicalType på: {', '.join(bad_types[:5])}"
                    f"{'…' if len(bad_types) > 5 else ''}. "
                    f"Gyldige: {', '.join(VALID_LOGICAL_TYPES)}.")

            unclassified = [
                str(p.get("name", "?")) for p in valid_props if _todo(p.get("classification"))
            ]
            if unclassified:
                warn("klassifisering", f"{prefix}.properties",
                     f"{len(unclassified)}/{len(valid_props)} kolonner mangler classification: "
                     f"{', '.join(unclassified[:5])}{'…' if len(unclassified) > 5 else ''}.")

            bad_col_cats = [
                f"{p.get('name', '?')} ({p.get('classification')})"
                for p in valid_props
                if not _todo(p.get("classification"))
                and p.get("classification") not in VALID_CATEGORIES
            ]
            if bad_col_cats:
                err("klassifisering", f"{prefix}.properties",
                    f"Ugyldig classification på: {', '.join(bad_col_cats[:5])}"
                    f"{'…' if len(bad_col_cats) > 5 else ''}. "
                    f"Gyldige: {', '.join(VALID_CATEGORIES)}.")

            # ── Klassifisering på objektnivå ──────────────────────────────────
            # ODCS tillater ikke `classification` på schema-objekter (kun på
            # kolonner), så datasettets samlede kategori uttrykkes som
            # customProperty.
            if "classification" in obj:
                err("klassifisering", f"{prefix}.classification",
                    _classification_hint(f"datasettet '{label}'"))

            obj_cat = _custom_props(obj).get(SB1U_CUSTOM_PROPS["category"])
            obj_cat_path = f"{prefix}.customProperties.{SB1U_CUSTOM_PROPS['category']}"

            # Strengeste konfidensialitetsnivå blant kolonnene. personal_data
            # inngår ikke — den er en egen akse, se PERSONAL_DATA_CATEGORY.
            col_ranks = [
                r for r in (_cat_rank(p.get("classification")) for p in valid_props)
                if r is not None
            ]
            strictest = max(col_ranks, default=None)

            if _todo(obj_cat):
                if len(schema_objects) > 1:
                    # Med flere datasett i én kontrakt er kategorien på
                    # kontraktsnivå ikke nok til å skille dem.
                    warn("klassifisering", obj_cat_path,
                         f"Anbefalt når kontrakten har flere datasett: oppgi "
                         f"'{SB1U_CUSTOM_PROPS['category']}' som customProperty på "
                         f"'{label}', slik at datasett med ulik sensitivitet kan "
                         "skilles.")
            elif obj_cat not in VALID_CATEGORIES:
                err("klassifisering", obj_cat_path,
                    f"Ugyldig kategori '{obj_cat}' på datasett '{label}'. "
                    f"Gyldige: {', '.join(VALID_CATEGORIES)}.")
            else:
                obj_rank = _cat_rank(obj_cat)
                if obj_rank is not None and strictest is not None and obj_rank < strictest:
                    strictest_name = next(
                        c for c, r in CATEGORY_RANK.items() if r == strictest
                    )
                    offenders = [
                        str(p.get("name", "?")) for p in valid_props
                        if _cat_rank(p.get("classification")) == strictest
                    ]
                    err("klassifisering", obj_cat_path,
                        f"Datasett '{label}' er klassifisert '{obj_cat}', men inneholder "
                        f"kolonner klassifisert '{strictest_name}': "
                        f"{', '.join(offenders[:5])}{'…' if len(offenders) > 5 else ''}. "
                        "Et datasett kan ikke være mindre strengt enn innholdet sitt.")

            # Kontraktsnivået måles mot det strengeste under seg — datasettets
            # egen kategori hvis den finnes, ellers kolonnene direkte.
            for rank, source in (
                (_cat_rank(obj_cat), f"datasettet '{label}'"),
                (strictest, f"en kolonne i '{label}'"),
            ):
                if rank is not None and (max_nested_rank is None or rank > max_nested_rank):
                    max_nested_rank, max_nested_source = rank, source

            personal_data_cols += [
                f"{label}.{p.get('name', '?')}" for p in valid_props
                if p.get("classification") == PERSONAL_DATA_CATEGORY
            ]
            if obj_cat == PERSONAL_DATA_CATEGORY:
                personal_data_cols.append(label)

            # Kvalitetsregler kan ligge på datasettet eller på enkeltkolonner.
            # Uten dem er kontrakten en strukturbeskrivelse, ikke en forpliktelse
            # på datakvalitet — så dette er blokkerende.
            has_quality = bool(obj.get("quality")) or any(p.get("quality") for p in valid_props)
            if not has_quality:
                err("innhold", f"{prefix}.quality",
                    f"Datasett '{label}' har ingen datakvalitetsregler (quality). "
                    "Datakontrakten må forplikte på kvalitet, ikke bare struktur.")

            # Primærnøkkelen bærer entydigheten i leveransen og skal alltid være
            # dekket av både null- og duplikatsjekk.
            pk_props = [p for p in valid_props if p.get("primaryKey") is True]
            for p in pk_props:
                metrics = {
                    q.get("metric") for q in (p.get("quality") or [])
                    if isinstance(q, dict)
                }
                missing = {"nullValues", "duplicateValues"} - metrics
                if missing:
                    warn("innhold", f"{prefix}.properties",
                         f"Primærnøkkel '{p.get('name', '?')}' mangler kvalitetsregel: "
                         f"{', '.join(sorted(missing))}.")

            # ── Semantikk på kolonnenivå ──────────────────────────────────────
            no_business_name = [
                str(p.get("name", "?")) for p in valid_props if _todo(p.get("businessName"))
            ]
            if no_business_name:
                pct = len(no_business_name) / len(valid_props) * 100
                report = err if pct > 75 else warn
                report("semantikk", f"{prefix}.properties",
                       f"{len(no_business_name)}/{len(valid_props)} kolonner mangler "
                       f"businessName (forretningsbegrep): "
                       f"{', '.join(no_business_name[:5])}"
                       f"{'…' if len(no_business_name) > 5 else ''}.")

            # Dataavstamming per kolonne: ODCS uttrykker dette med
            # transformSourceObjects (hvilke kilder kolonnen er utledet fra).
            with_lineage = [p for p in valid_props if p.get("transformSourceObjects")]
            if not with_lineage:
                err("semantikk", f"{prefix}.properties",
                    f"Datasett '{label}' har ingen dataavstamming — ingen kolonne oppgir "
                    "transformSourceObjects. Konsumenter må kunne se hvor dataen kommer fra.")
            elif len(with_lineage) < len(valid_props):
                missing_lineage = [
                    str(p.get("name", "?")) for p in valid_props
                    if not p.get("transformSourceObjects")
                ]
                warn("semantikk", f"{prefix}.properties",
                     f"{len(missing_lineage)}/{len(valid_props)} kolonner mangler "
                     f"transformSourceObjects: {', '.join(missing_lineage[:5])}"
                     f"{'…' if len(missing_lineage) > 5 else ''}.")

            # Utledede kolonner bør forklares i forretningstermer, ikke bare SQL.
            undocumented_transforms = [
                str(p.get("name", "?")) for p in valid_props
                if p.get("transformLogic") and _todo(p.get("transformDescription"))
            ]
            if undocumented_transforms:
                warn("semantikk", f"{prefix}.properties",
                     f"Kolonner med transformLogic mangler transformDescription "
                     f"(forklaring i forretningstermer): "
                     f"{', '.join(undocumented_transforms[:5])}"
                     f"{'…' if len(undocumented_transforms) > 5 else ''}.")

            if _todo(obj.get("dataGranularityDescription")):
                warn("semantikk", f"{prefix}.dataGranularityDescription",
                     f"Anbefalt: beskriv granularitet for '{label}' — hva én rad "
                     "representerer.")

    # ── Klassifisering: samsvar mellom nivåene ────────────────────────────────
    # Kategorien på kontraktsnivå er den konsumenter og tilgangsstyring ser først.
    # Den må derfor dekke det strengeste innholdet under seg — ellers underrapporterer
    # kontrakten sin egen sensitivitet.
    cat_rank = _cat_rank(cat)
    if cat_rank is not None and max_nested_rank is not None and cat_rank < max_nested_rank:
        strictest_name = next(c for c, r in CATEGORY_RANK.items() if r == max_nested_rank)
        err("klassifisering", cat_key,
            f"Kontrakten er klassifisert '{cat}', men {max_nested_source} er "
            f"klassifisert '{strictest_name}'. Kontraktsnivået kan ikke være "
            "mindre strengt enn innholdet sitt.")

    # personal_data er en egen akse og skal gjenspeiles i personvern-flagget,
    # ikke i konfidensialitetsnivået.
    if personal_data_cols and contains_pii is False:
        err("klassifisering", pii_key,
            f"'{SB1U_CUSTOM_PROPS['pii']}' er false, men følgende er klassifisert "
            f"'{PERSONAL_DATA_CATEGORY}': {', '.join(personal_data_cols[:5])}"
            f"{'…' if len(personal_data_cols) > 5 else ''}.")

    # ── SLA ───────────────────────────────────────────────────────────────────
    if not slas:
        err("innhold", "slaProperties",
            "Mangler SLA-blokk (slaProperties). ODCS v3 bruker 'slaProperties', ikke 'sla'.")
    else:
        latency = slas.get("latency")
        if not latency:
            err("innhold", "slaProperties[latency]",
                "Mangler ferskhet-SLA — legg til slaProperty med property 'latency' "
                "(ODCS foretrekker 'latency' over 'freshness').")
        else:
            if _todo(latency.get("value")):
                err("innhold", "slaProperties[latency].value",
                    "Mangler maks. akseptabel forsinkelse (latency.value).")
            if _todo(latency.get("unit")):
                err("innhold", "slaProperties[latency].unit",
                    "Mangler enhet for latency (latency.unit), f.eks. 'h' eller 'd'.")
            if _todo(latency.get("element")):
                warn("innhold", "slaProperties[latency].element",
                     "Anbefalt: oppgi hvilken kolonne latency måles på (latency.element).")

        frequency = slas.get("frequency")
        if not frequency:
            warn("innhold", "slaProperties[frequency]",
                 "Anbefalt: oppgi oppdateringsfrekvens (slaProperty 'frequency').")
        elif _todo(frequency.get("schedule")):
            warn("innhold", "slaProperties[frequency].schedule",
                 "Anbefalt: oppgi faktisk kjøreplan (frequency.schedule).")

        # Stabilitet er et eget krav i SB1U-definisjonen, ved siden av
        # datakvalitet. For aktive leveranser må konsumenter vite hvor
        # pålitelig leveransen er, ikke bare hvor fersk.
        availability = slas.get("availability")
        if not availability:
            report = err if status == "active" else warn
            report("innhold", "slaProperties[availability]",
                   "Mangler tilgjengelighetsmål (slaProperty 'availability'). "
                   "Kontrakten skal forplikte på stabilitet, ikke bare ferskhet.")
        elif _todo(availability.get("value")):
            err("innhold", "slaProperties[availability].value",
                "Mangler verdi for tilgjengelighetsmål (availability.value).")

        if not slas.get("timeToNotify"):
            warn("innhold", "slaProperties[timeToNotify]",
                 "Anbefalt: oppgi hvor raskt konsumenter varsles ved avvik "
                 "(slaProperty 'timeToNotify').")

    domain = data.get("domain")
    return ContractResult(
        file=filepath,
        contract_id=contract_id,
        title=name or filepath.stem,
        status=status,
        version=version,
        owner_team=owner_team,
        domain="" if _todo(domain) else str(domain),
        findings=findings,
    )


# ── HTML-rapport ──────────────────────────────────────────────────────────────

STATUS_COLORS = {
    "active":     ("#dcfce7", "#166534"),
    "draft":      ("#fef9c3", "#854d0e"),
    "proposed":   ("#e0e7ff", "#3730a3"),
    "deprecated": ("#fee2e2", "#991b1b"),
    "retired":    ("#f1f5f9", "#475569"),
}

# Rekkefølgen styrer visningen av dimensjonsmerker i rapporten.
DIM_LABELS = {
    "eierskap":       "Eierskap",
    "klassifisering": "Klassifisering",
    "innhold":        "Innhold",
    "semantikk":      "Semantikk",
    "versjonering":   "Versjonering",
}


def score_color(score: int) -> tuple[str, str]:
    if score >= 90:
        return "#dcfce7", "#166534"
    if score >= 70:
        return "#fef9c3", "#854d0e"
    return "#fee2e2", "#991b1b"


def render_contract_row(r: ContractResult) -> str:
    status_bg, status_fg = STATUS_COLORS.get(r.status, ("#f1f5f9", "#475569"))
    sbg, sfg = score_color(r.score)

    dim_counts: dict[str, dict[str, int]] = {}
    for f in r.findings:
        dim_counts.setdefault(f.dimension, {"error": 0, "warning": 0})
        dim_counts[f.dimension][f.severity] += 1

    dim_badges = ""
    for dim in DIM_LABELS:
        counts = dim_counts.get(dim, {})
        errs = counts.get("error", 0)
        warns = counts.get("warning", 0)
        if errs or warns:
            color = "#fee2e2" if errs else "#fef9c3"
            fgcolor = "#991b1b" if errs else "#854d0e"
            text = f"{DIM_LABELS[dim]}: {errs}E {warns}A" if errs and warns else \
                   f"{DIM_LABELS[dim]}: {errs}E" if errs else \
                   f"{DIM_LABELS[dim]}: {warns}A"
        else:
            color, fgcolor, text = "#dcfce7", "#166534", f"✓ {DIM_LABELS[dim]}"
        dim_badges += (
            f'<span class="dim-badge" style="background:{color};color:{fgcolor}">'
            f'{text}</span>'
        )

    findings_html = ""
    if r.findings:
        items = ""
        for f in r.findings:
            icon = "✗" if f.severity == "error" else "⚠"
            color = "#991b1b" if f.severity == "error" else "#92400e"
            items += (
                f'<li style="color:{color};margin:3px 0">'
                f'<b>{icon} [{DIM_LABELS[f.dimension]}]</b> '
                f'<code style="font-size:.78rem;background:#f8fafc;padding:1px 4px;border-radius:3px">'
                f'{f.field_path}</code>: {f.message}</li>'
            )
        findings_html = f'<ul style="margin:8px 0 0 0;padding-left:16px;list-style:none">{items}</ul>'

    return f"""
    <div class="contract-card" data-valid="{'true' if r.is_valid else 'false'}"
         data-status="{r.status}">
      <div class="contract-header">
        <div class="contract-title-row">
          <span class="contract-title">{r.title}</span>
          <div class="contract-badges">
            <span class="status-badge" style="background:{status_bg};color:{status_fg}">{r.status}</span>
            <span class="score-badge" style="background:{sbg};color:{sfg}">{r.score}/100</span>
          </div>
        </div>
        <div class="contract-meta">
          {f'<span class="meta-chip">v{r.version}</span>' if r.version else ''}
          {f'<span class="meta-chip">Team: {r.owner_team}</span>' if r.owner_team else ''}
          {f'<span class="meta-chip">Domene: {r.domain}</span>' if r.domain else ''}
          <span class="meta-chip" style="color:#64748b;font-family:monospace">{r.file.name}</span>
        </div>
      </div>
      <div class="dim-badges">{dim_badges}</div>
      {findings_html}
    </div>"""


def build_report_html(results: list[ContractResult]) -> str:
    total = len(results)
    valid = sum(1 for r in results if r.is_valid)
    total_errors = sum(len(r.errors) for r in results)
    total_warnings = sum(len(r.warnings) for r in results)
    avg_score = int(sum(r.score for r in results) / total) if total else 0

    contracts_html = "\n".join(render_contract_row(r) for r in results)

    return f"""<!DOCTYPE html>
<html lang="no">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Datakontrakts-rapport</title>
<style>
  *, *::before, *::after {{ box-sizing: border-box; margin: 0; padding: 0; }}
  body {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
         background: #f1f5f9; color: #1e293b; min-height: 100vh; }}

  .header {{ background: linear-gradient(135deg, #1e3a5f 0%, #0f2942 100%);
             color: #fff; padding: 32px 40px; }}
  .header h1 {{ font-size: 1.7rem; font-weight: 700; }}
  .header p  {{ margin-top: 6px; opacity: .75; font-size: .95rem; }}

  .stats {{ display: flex; gap: 0; background: #fff;
            border-bottom: 1px solid #e2e8f0; }}
  .stat {{ flex: 1; padding: 20px 32px; border-right: 1px solid #e2e8f0;
           display: flex; flex-direction: column; align-items: center; }}
  .stat:last-child {{ border-right: none; }}
  .stat-num   {{ font-size: 2rem; font-weight: 700; color: #1e3a5f; }}
  .stat-label {{ font-size: .78rem; color: #64748b; text-transform: uppercase;
                 letter-spacing: .05em; margin-top: 2px; }}

  .toolbar {{ padding: 16px 40px; background: #fff;
              border-bottom: 1px solid #e2e8f0;
              display: flex; gap: 12px; flex-wrap: wrap; align-items: center; }}
  #search {{ flex: 1; min-width: 200px; max-width: 400px;
             padding: 8px 14px; border: 1px solid #cbd5e1; border-radius: 8px;
             font-size: .95rem; outline: none; }}
  #search:focus {{ border-color: #6366f1; box-shadow: 0 0 0 3px #6366f120; }}
  .filter-btn {{ padding: 6px 14px; border: 2px solid #cbd5e1; border-radius: 20px;
                 background: #fff; cursor: pointer; font-size: .82rem; font-weight: 600; }}
  .filter-btn.active {{ background: #1e3a5f; color: #fff; border-color: #1e3a5f; }}

  .legend {{ padding: 12px 40px; background: #f8fafc; border-bottom: 1px solid #e2e8f0;
             font-size: .78rem; color: #64748b; display: flex; gap: 20px; flex-wrap: wrap; }}
  .legend b {{ color: #1e293b; }}

  .grid {{ padding: 24px 40px; display: flex; flex-direction: column; gap: 12px; }}

  .contract-card {{ background: #fff; border-radius: 12px; padding: 18px 20px;
                    border: 1px solid #e2e8f0;
                    box-shadow: 0 1px 3px rgba(0,0,0,.06); }}
  .contract-header {{ margin-bottom: 10px; }}
  .contract-title-row {{ display: flex; justify-content: space-between;
                         align-items: center; gap: 8px; flex-wrap: wrap; }}
  .contract-title {{ font-size: 1.05rem; font-weight: 700; color: #1e293b; }}
  .contract-badges {{ display: flex; gap: 6px; align-items: center; }}
  .status-badge {{ border-radius: 4px; padding: 2px 8px;
                   font-size: .72rem; font-weight: 700; }}
  .score-badge  {{ border-radius: 4px; padding: 2px 8px;
                   font-size: .78rem; font-weight: 700; font-family: monospace; }}
  .contract-meta {{ display: flex; gap: 6px; flex-wrap: wrap; margin-top: 6px; }}
  .meta-chip {{ background: #f1f5f9; color: #64748b; border-radius: 4px;
                padding: 2px 8px; font-size: .72rem; font-weight: 600; }}
  .dim-badges {{ display: flex; gap: 6px; flex-wrap: wrap; }}
  .dim-badge  {{ border-radius: 4px; padding: 3px 10px;
                 font-size: .72rem; font-weight: 700; white-space: nowrap; }}

  .no-results {{ display: none; padding: 60px 40px; text-align: center;
                 color: #64748b; font-size: 1rem; }}

  @media (max-width: 600px) {{
    .header, .stats, .toolbar, .grid, .legend {{ padding-left: 16px; padding-right: 16px; }}
    .stats {{ flex-wrap: wrap; }}
    .stat {{ min-width: 50%; border-right: none; border-bottom: 1px solid #e2e8f0; }}
  }}
</style>
</head>
<body>

<div class="header">
  <h1>Datakontrakts-rapport</h1>
  <p>ODCS v3.1.0 + SB1U-profil — {' · '.join(DIM_LABELS.values())}</p>
</div>

<div class="stats">
  <div class="stat">
    <span class="stat-num">{total}</span>
    <span class="stat-label">Kontrakter totalt</span>
  </div>
  <div class="stat">
    <span class="stat-num" style="color:{'#166534' if valid==total else '#991b1b'}">{valid}</span>
    <span class="stat-label">Uten feil</span>
  </div>
  <div class="stat">
    <span class="stat-num" style="color:{'#991b1b' if total_errors else '#166534'}">{total_errors}</span>
    <span class="stat-label">Feil totalt</span>
  </div>
  <div class="stat">
    <span class="stat-num" style="color:{'#854d0e' if total_warnings else '#166534'}">{total_warnings}</span>
    <span class="stat-label">Advarsler totalt</span>
  </div>
  <div class="stat">
    <span class="stat-num">{avg_score}</span>
    <span class="stat-label">Gjennomsnittsscore</span>
  </div>
</div>

<div class="legend">
  <span><b>E</b> = feil (blokkerende) &nbsp;·&nbsp; <b>A</b> = advarsel (anbefaling)</span>
  <span><b>Score</b>: 100 − 15×feil − 5×advarsler, min 0</span>
  <span><b>Dimensjoner</b>: {' · '.join(DIM_LABELS.values())}</span>
</div>

<div class="toolbar">
  <input id="search" type="search" placeholder="Søk etter kontrakt, team eller fil…"
         oninput="filterCards()">
  <button class="filter-btn active" data-filter="all" onclick="setFilter('all',this)">Alle ({total})</button>
  <button class="filter-btn" data-filter="invalid" onclick="setFilter('invalid',this)">Med feil ({total - valid})</button>
  <button class="filter-btn" data-filter="valid" onclick="setFilter('valid',this)">Uten feil ({valid})</button>
</div>

<div class="grid" id="grid">
  {contracts_html}
</div>
<div class="no-results" id="no-results">Ingen kontrakter funnet.</div>

<script>
  let activeFilter = 'all';

  function setFilter(f, btn) {{
    activeFilter = f;
    document.querySelectorAll('.filter-btn').forEach(b => b.classList.remove('active'));
    btn.classList.add('active');
    filterCards();
  }}

  function filterCards() {{
    const q = document.getElementById('search').value.toLowerCase().trim();
    const cards = document.querySelectorAll('.contract-card');
    let visible = 0;
    cards.forEach(card => {{
      const filterMatch =
        activeFilter === 'all' ||
        (activeFilter === 'valid'   && card.dataset.valid === 'true') ||
        (activeFilter === 'invalid' && card.dataset.valid === 'false');
      const textMatch = !q || card.textContent.toLowerCase().includes(q);
      const show = filterMatch && textMatch;
      card.style.display = show ? '' : 'none';
      if (show) visible++;
    }});
    document.getElementById('no-results').style.display = visible === 0 ? 'block' : 'none';
  }}
</script>
</body>
</html>"""


# ── Hovedprogram ──────────────────────────────────────────────────────────────

CONTRACTS_DIR = Path(__file__).parent / "contracts"
OUTPUT_FILE   = Path(__file__).parent / "contracts_report.html"


def load_contract_file(filepath: Path) -> dict | None:
    try:
        content = filepath.read_text(encoding="utf-8")
        data = yaml.safe_load(content)
        if not isinstance(data, dict):
            print(f"  Advarsel: {filepath.name} er ikke et gyldig YAML-objekt, hopper over.")
            return None
        return data
    except yaml.YAMLError as e:
        print(f"  Feil ved parsing av {filepath.name}: {e}")
        return None


def main():
    contract_files = sorted(CONTRACTS_DIR.glob("*.yml"))
    contract_files = [f for f in contract_files if not f.name.startswith("_")]

    if not contract_files:
        sys.exit(
            f"Ingen kontrakt-filer funnet i {CONTRACTS_DIR}.\n"
            "Opprett YAML-filer basert på catalog/datakontrakt_mal.yml."
        )

    print(f"Validerer {len(contract_files)} kontrakt(er) i {CONTRACTS_DIR}…\n")

    results = []
    for fp in contract_files:
        data = load_contract_file(fp)
        if data is None:
            continue
        result = validate_contract(data, fp)
        results.append(result)

        status_icon = "✓" if result.is_valid else "✗"
        print(f"  {status_icon} {fp.name}  (score: {result.score}/100"
              f"  feil: {len(result.errors)}  advarsler: {len(result.warnings)})")
        for f in result.findings:
            icon = "  ✗" if f.severity == "error" else "  ⚠"
            print(f"{icon}  [{f.dimension}] {f.field_path}: {f.message}")
        if result.findings:
            print()

    total = len(results)
    valid = sum(1 for r in results if r.is_valid)
    total_errors = sum(len(r.errors) for r in results)

    print(f"\nResultat: {valid}/{total} kontrakter uten feil  |  {total_errors} feil totalt")

    html = build_report_html(results)
    OUTPUT_FILE.write_text(html, encoding="utf-8")
    print(f"Rapport skrevet til: {OUTPUT_FILE}")

    if total_errors > 0:
        sys.exit(1)


if __name__ == "__main__":
    main()
