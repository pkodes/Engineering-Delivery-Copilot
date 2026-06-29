"""
AppSpec — the validated, normalized contract between the Builder Agent (LLM
judgment) and the deterministic code generators (template emission).

The LLM returns a loose JSON blob; everything downstream consumes an AppSpec.
All normalization (pluralization, table names, types, slugs) happens here so the
generators can stay dumb and reliable.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

# Field type system. The LLM is constrained to these; everything else derives.
ALLOWED_TYPES = {"string", "text", "integer", "number", "boolean", "date"}
SQLITE_TYPES = {
    "string": "TEXT",
    "text": "TEXT",
    "integer": "INTEGER",
    "number": "REAL",
    "boolean": "INTEGER",
    "date": "TEXT",
}
PY_TYPES = {
    "string": "str",
    "text": "str",
    "integer": "int",
    "number": "float",
    "boolean": "bool",
    "date": "str",
}

_HEX_RE = re.compile(r"^#([0-9a-fA-F]{6})$")


# --------------------------------------------------------------------------- #
# String helpers
# --------------------------------------------------------------------------- #
def slugify(value: str) -> str:
    out = re.sub(r"[^a-zA-Z0-9]+", "-", (value or "").strip().lower()).strip("-")
    return out or "app"


def snake(value: str) -> str:
    s = (value or "").strip()
    # Split camelCase / PascalCase boundaries before flattening separators.
    s = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", "_", s)
    s = re.sub(r"(?<=[A-Z])(?=[A-Z][a-z])", "_", s)
    s = re.sub(r"[^a-zA-Z0-9]+", "_", s).strip("_").lower()
    return s or "field"


def pascal(value: str) -> str:
    parts = [p for p in re.split(r"[^a-zA-Z0-9]+", value or "") if p]
    return "".join(p[:1].upper() + p[1:] for p in parts) or "Entity"


def titleize(value: str) -> str:
    parts = [p for p in re.split(r"[_\s-]+", value or "") if p]
    return " ".join(p[:1].upper() + p[1:] for p in parts) or value


def pluralize(word: str) -> str:
    w = word or "item"
    lower = w.lower()
    if lower.endswith("y") and len(w) > 1 and w[-2].lower() not in "aeiou":
        return w[:-1] + "ies"
    if lower.endswith(("s", "x", "z", "ch", "sh")):
        return w + "es"
    return w + "s"


# --------------------------------------------------------------------------- #
# Spec model
# --------------------------------------------------------------------------- #
@dataclass
class Field:
    name: str          # snake_case column name
    label: str         # human label
    type: str          # one of ALLOWED_TYPES
    required: bool = False

    @property
    def sqlite_type(self) -> str:
        return SQLITE_TYPES[self.type]

    @property
    def py_type(self) -> str:
        return PY_TYPES[self.type]

    def to_dict(self) -> dict[str, Any]:
        return {"name": self.name, "label": self.label, "type": self.type, "required": self.required}


@dataclass
class Entity:
    name: str                       # PascalCase singular, e.g. "Patient"
    name_plural: str                # "Patients"
    table: str                      # "patients"
    fields: list[Field] = field(default_factory=list)
    seed: list[dict[str, Any]] = field(default_factory=list)

    @property
    def path(self) -> str:
        return self.table  # URL segment, e.g. /api/patients

    @property
    def var(self) -> str:
        return snake(self.name)

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "name_plural": self.name_plural,
            "table": self.table,
            "path": self.path,
            "fields": [f.to_dict() for f in self.fields],
            "seed": self.seed,
        }


@dataclass
class AppSpec:
    app_title: str
    description: str
    slug: str
    primary_color: str
    entities: list[Entity] = field(default_factory=list)
    source: str = "llm"  # "llm" or "fallback" — recorded for transparency

    def to_dict(self) -> dict[str, Any]:
        return {
            "app_title": self.app_title,
            "description": self.description,
            "slug": self.slug,
            "primary_color": self.primary_color,
            "source": self.source,
            "entities": [e.to_dict() for e in self.entities],
        }


# --------------------------------------------------------------------------- #
# JSON schema handed to Gemini (kept intentionally small & reliable)
# --------------------------------------------------------------------------- #
GEMINI_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "app_title": {"type": "string"},
        "description": {"type": "string"},
        "primary_color": {"type": "string", "description": "hex color like #2563eb"},
        "entities": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "name": {"type": "string", "description": "singular noun, e.g. Patient"},
                    "fields": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "name": {"type": "string"},
                                "type": {
                                    "type": "string",
                                    "enum": sorted(ALLOWED_TYPES),
                                },
                                "required": {"type": "boolean"},
                            },
                            "required": ["name", "type"],
                        },
                    },
                    "seed": {
                        "type": "array",
                        "description": "2-4 example rows as objects of field->value",
                        "items": {"type": "object"},
                    },
                },
                "required": ["name", "fields"],
            },
        },
    },
    "required": ["app_title", "entities"],
}


# --------------------------------------------------------------------------- #
# Normalization: loose LLM dict -> validated AppSpec
# --------------------------------------------------------------------------- #
_RESERVED = {"id"}


def _coerce_color(raw: Any) -> str:
    if isinstance(raw, str) and _HEX_RE.match(raw.strip()):
        return raw.strip().lower()
    return "#6d28d9"


def _normalize_field(raw: dict[str, Any], used: set[str]) -> Field | None:
    name = snake(str(raw.get("name", "")).strip())
    if not name or name in _RESERVED or name in used:
        return None
    ftype = str(raw.get("type", "string")).strip().lower()
    if ftype not in ALLOWED_TYPES:
        ftype = "string"
    used.add(name)
    return Field(
        name=name,
        label=titleize(name),
        type=ftype,
        required=bool(raw.get("required", False)),
    )


def _normalize_entity(raw: dict[str, Any], used_tables: set[str]) -> Entity | None:
    name = pascal(str(raw.get("name", "")).strip())
    if not name:
        return None
    table = snake(pluralize(name))
    if table in used_tables:
        return None
    used_tables.add(table)

    used_fields: set[str] = set()
    fields: list[Field] = []
    for raw_field in raw.get("fields", []) or []:
        if not isinstance(raw_field, dict):
            continue
        f = _normalize_field(raw_field, used_fields)
        if f is not None:
            fields.append(f)
    if not fields:
        # An entity with no usable fields is useless; give it a sane default.
        fields = [Field(name="name", label="Name", type="string", required=True)]
        used_fields.add("name")

    # Clean seed rows down to known fields only.
    valid_names = {f.name for f in fields}
    seed: list[dict[str, Any]] = []
    for row in raw.get("seed", []) or []:
        if not isinstance(row, dict):
            continue
        cleaned = {snake(str(k)): v for k, v in row.items()}
        cleaned = {k: v for k, v in cleaned.items() if k in valid_names}
        if cleaned:
            seed.append(cleaned)

    # Gemini's JSON mode rarely fills free-form seed objects reliably, so
    # synthesize plausible demo rows when none survived. Keeps previews populated.
    if not seed:
        seed = synthesize_seed(name, fields)

    return Entity(
        name=name,
        name_plural=titleize(pluralize(name)),
        table=table,
        fields=fields,
        seed=seed[:6],
    )


def normalize_spec(raw: dict[str, Any], *, requirement: str, source: str = "llm") -> AppSpec:
    """Turn a loose LLM/JSON dict into a validated, generation-ready AppSpec."""
    app_title = str(raw.get("app_title") or "").strip() or _title_from_requirement(requirement)
    description = str(raw.get("description") or "").strip() or (
        f"A working application generated from the requirement: {requirement.strip()}"
    )

    used_tables: set[str] = set()
    entities: list[Entity] = []
    for raw_entity in raw.get("entities", []) or []:
        if not isinstance(raw_entity, dict):
            continue
        ent = _normalize_entity(raw_entity, used_tables)
        if ent is not None:
            entities.append(ent)
        if len(entities) >= 8:
            break

    if not entities:
        entities = _fallback_entities()
        source = "fallback"

    return AppSpec(
        app_title=app_title,
        description=description,
        slug=slugify(app_title),
        primary_color=_coerce_color(raw.get("primary_color")),
        entities=entities,
        source=source,
    )


_NAME_POOL = ["Ada Lovelace", "Alan Turing", "Grace Hopper", "Linus Torvalds", "Margaret Hamilton"]
_FIRST_POOL = ["Ada", "Alan", "Grace", "Linus", "Margaret"]
_LAST_POOL = ["Lovelace", "Turing", "Hopper", "Torvalds", "Hamilton"]
_ADDR_POOL = ["123 Main St", "456 Oak Ave", "789 Pine Rd"]
_STATUS_POOL = ["active", "pending", "completed"]
_CITY_POOL = ["London", "Paris", "Berlin"]
_CATEGORY_POOL = ["General", "Cardiology", "Pediatrics"]


def _seed_value(entity_name: str, f: "Field", i: int) -> Any:
    """Deterministically synthesize a plausible value for a field, by type + name hints."""
    name = f.name
    if f.type == "boolean":
        return i % 2 == 0
    if f.type == "integer":
        if "age" in name:
            return 25 + i * 5
        if "year" in name:
            return 2020 + i
        return i + 1
    if f.type == "number":
        if any(k in name for k in ("price", "amount", "cost", "total", "fee", "salary", "balance", "rate")):
            return round(100.0 * (i + 1), 2)
        return round((i + 1) * 1.5, 2)
    if f.type == "date":
        return f"2024-0{i + 1}-15"
    # string / text
    if "email" in name:
        return f"user{i + 1}@example.com"
    if any(k in name for k in ("phone", "contact_number", "mobile", "tel")):
        return f"555-01{i:02d}"
    if "first" in name and "name" in name:
        return _FIRST_POOL[i % len(_FIRST_POOL)]
    if "last" in name and "name" in name:
        return _LAST_POOL[i % len(_LAST_POOL)]
    if "medication" in name or "drug" in name or "medicine" in name:
        return ["Amoxicillin", "Ibuprofen", "Paracetamol"][i % 3]
    if name == "name" or name.endswith("name") or "title" in name:
        return _NAME_POOL[i % len(_NAME_POOL)]
    if "gender" in name:
        return ["Female", "Male", "Other"][i % 3]
    if "address" in name:
        return _ADDR_POOL[i % len(_ADDR_POOL)]
    if "city" in name:
        return _CITY_POOL[i % len(_CITY_POOL)]
    if "status" in name or "state" in name:
        return _STATUS_POOL[i % len(_STATUS_POOL)]
    if any(k in name for k in ("department", "specialization", "category", "type", "role")):
        return _CATEGORY_POOL[i % len(_CATEGORY_POOL)]
    if f.type == "text" or any(k in name for k in ("description", "notes", "summary", "details")):
        return f"Sample {titleize(entity_name).lower()} entry #{i + 1}"
    return f"{titleize(name)} {i + 1}"


def synthesize_seed(entity_name: str, fields: list["Field"], count: int = 3) -> list[dict[str, Any]]:
    """Build `count` demo rows covering every field, with type-correct values."""
    return [{f.name: _seed_value(entity_name, f, i) for f in fields} for i in range(count)]


def _title_from_requirement(requirement: str) -> str:
    text = (requirement or "").strip()
    text = re.sub(r"^(build|create|make|develop|design)\s+(me\s+)?(a|an|the)?\s*", "", text, flags=re.I)
    text = text.split("\n")[0].strip().strip(".")
    return titleize(text) if text else "Generated Application"


def _fallback_entities() -> list[Entity]:
    """Minimal but genuinely-working schema used when the LLM is unavailable."""
    return [
        Entity(
            name="Record",
            name_plural="Records",
            table="records",
            fields=[
                Field("title", "Title", "string", required=True),
                Field("description", "Description", "text", required=False),
                Field("status", "Status", "string", required=False),
                Field("created_on", "Created On", "date", required=False),
            ],
            seed=[
                {"title": "First record", "description": "Example seeded item", "status": "open"},
                {"title": "Second record", "description": "Another example", "status": "done"},
            ],
        )
    ]


def heuristic_spec(requirement: str) -> AppSpec:
    """Deterministic fallback spec when Gemini cannot be reached."""
    return AppSpec(
        app_title=_title_from_requirement(requirement),
        description=f"A working application generated from the requirement: {requirement.strip()}",
        slug=slugify(_title_from_requirement(requirement)),
        primary_color="#6d28d9",
        entities=_fallback_entities(),
        source="fallback",
    )
