"""Reads the OpenAPI specs into a small language-neutral model.

The specs use a narrow slice of OpenAPI 3.1 (objects, arrays, scalars,
string enums, $ref, oneOf [X, null], additionalProperties, date-time). Anything
outside that slice raises, so a spec change that needs new generator support
fails loudly instead of producing a wrong SDK.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# Schema names that would shadow language built-ins (TypeScript's Error).
RENAMES = {"Error": "ErrorResponse"}


def _ref(r: str) -> str:
    name = r.rsplit("/", 1)[1]
    return RENAMES.get(name, name)


# Keys that carry documentation or validation only; generators ignore them.
_IGNORED = {"description", "examples", "example", "maximum", "minimum", "maxLength", "minLength", "default", "title"}


@dataclass
class Type:
    """A resolved type. kind is one of: string, integer, number, boolean,
    datetime, any, ref, array, map, enum."""

    kind: str
    ref: str | None = None          # kind == ref: schema name
    item: Type | None = None        # array items / map values
    enum: list[str] | None = None   # kind == enum: allowed string values
    enum_name: str | None = None    # kind == enum: generated name for the enum
    nullable: bool = False


@dataclass
class Field:
    name: str          # wire (JSON) name
    type: Type
    required: bool
    doc: str = ""


@dataclass
class Schema:
    name: str
    fields: list[Field]
    doc: str = ""


@dataclass
class Param:
    name: str
    type: Type
    required: bool
    doc: str = ""
    default: object = None


@dataclass
class Operation:
    id: str
    method: str            # GET, POST, ...
    path: str              # relative to the API base, e.g. /games/{key}
    summary: str
    doc: str
    path_params: list[Param]
    query: list[Param]
    body: str | None       # schema name
    body_required: bool
    result: str | None     # schema name, None for 204 responses
    tag: str = ""


@dataclass
class API:
    name: str              # "v1" or "partner"
    title: str
    version: str
    base_path: str         # /v1 or /partner/v1
    doc: str
    schemas: dict[str, Schema] = field(default_factory=dict)
    enums: dict[str, list[str]] = field(default_factory=dict)
    operations: list[Operation] = field(default_factory=list)


def _doc(s: dict) -> str:
    d = s.get("description", "")
    if "enum" in s and s.get("type") != "string":
        d = (d + ". " if d else "") + "One of " + ", ".join(map(str, s["enum"])) + "."
    return d


def _pascal(s: str) -> str:
    return "".join(p[:1].upper() + p[1:] for p in re.split(r"[_\-.]", s) if p)


class _Loader:
    def __init__(self, api: API, doc: dict):
        self.api = api
        self.doc = doc

    def type_of(self, s: dict, owner: str, prop: str) -> Type:
        s = {k: v for k, v in s.items() if k not in _IGNORED}
        if "$ref" in s:
            return Type("ref", ref=_ref(s["$ref"]))
        if "oneOf" in s:
            alts = s["oneOf"]
            non_null = [a for a in alts if a.get("type") != "null"]
            if len(alts) == 2 and len(non_null) == 1 and set(s) == {"oneOf"}:
                t = self.type_of(non_null[0], owner, prop)
                t.nullable = True
                return t
            raise ValueError(f"{owner}.{prop}: unsupported oneOf {alts}")
        t = s.get("type")
        if isinstance(t, list):
            non_null = [x for x in t if x != "null"]
            if len(non_null) != 1 or len(t) != 2:
                raise ValueError(f"{owner}.{prop}: unsupported type array {t}")
            inner = self.type_of({**s, "type": non_null[0]}, owner, prop)
            inner.nullable = True
            return inner
        if t == "string":
            if "enum" in s:
                name = _pascal(owner) + _pascal(prop)
                values = list(s["enum"])
                prev = self.api.enums.get(name)
                if prev is not None and prev != values:
                    raise ValueError(f"enum name clash: {name}")
                self.api.enums[name] = values
                return Type("enum", enum=values, enum_name=name)
            fmt = s.get("format")
            if fmt == "date-time":
                return Type("datetime")
            if fmt not in (None, "uri", "email", "date"):
                raise ValueError(f"{owner}.{prop}: unsupported string format {fmt}")
            return Type("string")
        if t in ("integer", "number", "boolean"):
            # Numeric enums (only the sync interval today) stay plain numbers;
            # Field/Param docs list the allowed values.
            return Type(t)
        if t == "array":
            return Type("array", item=self.type_of(s["items"], owner, prop))
        if t == "object":
            if "properties" in s:
                raise ValueError(f"{owner}.{prop}: inline objects not supported; give it a named schema")
            ap = s.get("additionalProperties")
            if isinstance(ap, dict):
                return Type("map", item=self.type_of(ap, owner, prop))
            return Type("any")
        raise ValueError(f"{owner}.{prop}: unsupported schema {s}")

    def schema(self, name: str, s: dict) -> Schema:
        if s.get("type") != "object" or "properties" not in s:
            raise ValueError(f"schema {name}: only object schemas with properties are supported")
        extra = set(s) - {"type", "properties", "required", "description", "additionalProperties"}
        if extra:
            raise ValueError(f"schema {name}: unsupported keys {extra}")
        req = set(s.get("required", []))
        fields = [
            Field(p, self.type_of(ps, name, p), p in req, _doc(ps))
            for p, ps in s["properties"].items()
        ]
        return Schema(name, fields, s.get("description", ""))

    def param(self, p: dict) -> dict:
        if "$ref" in p:
            parts = p["$ref"].lstrip("#/").split("/")
            node = self.doc
            for part in parts:
                node = node[part]
            return node
        return p

    def response_schema(self, op_id: str, responses: dict) -> str | None:
        ok = sorted(k for k in responses if k.startswith("2"))
        names = set()
        for code in ok:
            content = responses[code].get("content")
            if not content:
                names.add(None)
                continue
            schema = content["application/json"]["schema"]
            if "$ref" not in schema:
                raise ValueError(f"{op_id}: {code} response must be a $ref")
            names.add(_ref(schema["$ref"]))
        if len(names) != 1:
            raise ValueError(f"{op_id}: success responses disagree: {names}")
        return names.pop()

    def operations(self):
        for path, item in self.doc["paths"].items():
            for method, op in item.items():
                if method not in ("get", "post", "put", "patch", "delete"):
                    raise ValueError(f"{path}: unsupported key {method}")
                op_id = op["operationId"]
                path_params, query = [], []
                for raw in op.get("parameters", []):
                    p = self.param(raw)
                    if p["in"] == "header":
                        if p["name"] != "Dynasty-Id":
                            raise ValueError(f"{op_id}: unexpected header param {p['name']}")
                        continue  # handled by the client configuration
                    prm = Param(
                        p["name"],
                        self.type_of(p["schema"], op_id, p["name"]),
                        bool(p.get("required")),
                        _doc({**p["schema"], "description": p.get("description", "")}),
                        p["schema"].get("default"),
                    )
                    if prm.type.kind not in ("string", "integer", "number", "boolean", "enum"):
                        raise ValueError(f"{op_id}: param {p['name']} must be a scalar")
                    (path_params if p["in"] == "path" else query).append(prm)
                    if p["in"] not in ("path", "query"):
                        raise ValueError(f"{op_id}: unsupported param location {p['in']}")
                body, body_required = None, False
                if "requestBody" in op:
                    rb = op["requestBody"]
                    schema = rb["content"]["application/json"]["schema"]
                    body = _ref(schema["$ref"])
                    body_required = bool(rb.get("required"))
                # path params must appear in path order
                order = re.findall(r"{(\w+)}", path)
                path_params.sort(key=lambda p: order.index(p.name))
                self.api.operations.append(
                    Operation(
                        id=op_id,
                        method=method.upper(),
                        path=path,
                        summary=op.get("summary", ""),
                        doc=op.get("description", ""),
                        path_params=path_params,
                        query=query,
                        body=body,
                        body_required=body_required,
                        result=self.response_schema(op_id, op["responses"]),
                        tag=(op.get("tags") or [""])[0],
                    )
                )


def load(name: str, file: str) -> API:
    doc = json.loads((ROOT / "spec" / file).read_text())
    info = doc["info"]
    api = API(name, info["title"], info["version"], doc["servers"][0]["url"].rstrip("/"), info.get("description", ""))
    loader = _Loader(api, doc)
    for sname, s in sorted(doc["components"]["schemas"].items()):
        sname = RENAMES.get(sname, sname)
        api.schemas[sname] = loader.schema(sname, s)
    loader.operations()
    clash = set(api.enums) & set(api.schemas)
    if clash:
        raise ValueError(f"{name}: enum and schema names clash: {clash}")
    return api


def load_all() -> list[API]:
    return [load("v1", "v1.json"), load("partner", "partner.json")]


if __name__ == "__main__":
    for api in load_all():
        print(api.name, api.base_path, len(api.schemas), "schemas", len(api.enums), "enums", len(api.operations), "ops")
        for op in api.operations:
            print(" ", op.method, op.path, op.id, [p.name for p in op.path_params], [q.name for q in op.query], op.body, op.result)
