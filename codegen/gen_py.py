"""Python emitter: pydantic v2 models and sync/async endpoint mixins that the
handwritten clients in python/src/cfb27_dynasty extend."""

from __future__ import annotations

import keyword

from common import HEADER, paragraphs, snake
from ir import API, Operation, Type

CLASS = {"v1": "DynastyAPI", "partner": "PartnerAPI"}
# Field names that would shadow BaseModel attributes.
_RESERVED = {"json", "dict", "copy", "schema", "construct", "validate", "fields", "model_config"}


def _doc(lines: list[str], indent: str) -> list[str]:
    if not lines:
        return []
    lines = [l.replace("\\", "\\\\").replace('"""', '\\"\\"\\"') for l in lines]
    if len(lines) == 1:
        return [f'{indent}"""{lines[0]}"""']
    return [f'{indent}"""{lines[0]}'] + [f"{indent}{l}" if l else "" for l in lines[1:]] + [f'{indent}"""']


def _py(t: Type) -> str:
    k = t.kind
    if k == "string":
        s = "str"
    elif k == "datetime":
        s = "datetime"
    elif k == "integer":
        s = "int"
    elif k == "number":
        s = "float"
    elif k == "boolean":
        s = "bool"
    elif k == "any":
        s = "dict[str, Any]"
    elif k == "ref":
        s = t.ref
    elif k == "enum":
        s = t.enum_name
    elif k == "array":
        s = f"list[{_py(t.item)}]"
    elif k == "map":
        s = f"dict[str, {_py(t.item)}]"
    else:
        raise ValueError(k)
    return f"{s} | None" if t.nullable else s


def _attr(name: str) -> str:
    return name + "_" if keyword.iskeyword(name) or name in _RESERVED else name


def emit_models(api: API, shared: set[str], file: str) -> str:
    out = ["# " + HEADER.format(file=file), "# ruff: noqa: E501", "", "from __future__ import annotations", ""]
    out += ["from datetime import datetime", "from typing import Any, Literal", "", "from pydantic import Field", ""]
    out.append("from .._model import Model")
    reuse = sorted(shared) if api.name == "partner" else []
    if reuse:
        out.append(f"from .models_v1 import {', '.join(reuse)}")
    out += ["", "__all__ = ["]
    names = list(api.enums) + list(api.schemas)
    out += [f'    "{n}",' for n in names]
    out += ["]", ""]

    for name, values in api.enums.items():
        lits = ", ".join('"' + v.replace('"', '\\"') + '"' for v in values)
        out.append(f"{name} = Literal[{lits}] | str")
        out.append(f'"""Known values; newer servers may send others."""')
        out.append("")

    for name, s in api.schemas.items():
        if name in reuse:
            continue
        out += ["", f"class {name}(Model):"]
        out += _doc(paragraphs(s.doc), "    ")
        for f in s.fields:
            attr = _attr(f.name)
            typ = _py(f.type)
            if not f.required and not f.type.nullable:
                typ += " | None"
            default = "" if f.required else "None"
            if attr != f.name:
                args = (f"{default}, " if default else "") + f'alias="{f.name}"'
                out.append(f"    {attr}: {typ} = Field({args})")
            else:
                out.append(f"    {attr}: {typ}" + (f" = {default}" if default else ""))
            out += _doc(paragraphs(f.doc), "    ")
        if not s.fields:
            out.append("    pass")
        out.append("")

    out.append("")
    for name in api.schemas:
        if name not in reuse:
            out.append(f"{name}.model_rebuild()")
    out.append("")
    return "\n".join(out)


def _signature(api: API, op: Operation) -> tuple[list[str], list[str], str | None]:
    """Returns (params, body-building lines, body var) for an operation."""
    params = ["self"] + [f"{p.name}: {_py(p.type)}" for p in op.path_params]
    kw = []
    body_lines: list[str] = []
    seen = {p.name for p in op.path_params}
    if op.body:
        schema = api.schemas[op.body]
        items = []
        for f in schema.fields:
            if f.name in seen:
                raise ValueError(f"{op.id}: body field {f.name} clashes with a parameter")
            seen.add(f.name)
            attr = _attr(f.name)
            if f.required:
                kw.append(f"{attr}: {_py(f.type)}")
            else:
                kw.append(f"{attr}: {_py(f.type)} | None = None")
            items.append(f'"{f.name}": {attr}')
        body_lines.append(f"body = {{{', '.join(items)}}}")
    for q in op.query:
        if q.name in seen:
            raise ValueError(f"{op.id}: query {q.name} clashes with another parameter")
        seen.add(q.name)
        attr = _attr(q.name)
        kw.append(f"{attr}: {_py(q.type)}" + ("" if q.required else " | None = None"))
    # required keyword arguments first so the signature is valid and readable
    kw.sort(key=lambda a: "=" in a)
    if kw:
        params += ["*"] + kw
    params.append("timeout: float | None = None")
    return params, body_lines, "body" if op.body else None


def _method(api: API, op: Operation, is_async: bool) -> list[str]:
    params, body_lines, body = _signature(api, op)
    name = snake(op.id)
    ret = op.result or "None"
    out = [f"    {'async ' if is_async else ''}def {name}(", *[f"        {p}," for p in params], f"    ) -> {ret}:"]
    doc = paragraphs(op.summary, op.doc) + ["", f"``{op.method} {api.base_path}{op.path}``"]
    out += _doc(doc, "        ")
    out += [f"        {l}" for l in body_lines]
    path = op.path
    fmt = "f" if op.path_params else ""
    for p in op.path_params:
        path = path.replace("{" + p.name + "}", "{_seg(" + p.name + ")}")
    args = [f'"{op.method}"', f'{fmt}"{path}"']
    if op.query:
        args.append("query={" + ", ".join(f'"{q.name}": {_attr(q.name)}' for q in op.query) + "}")
    if body:
        args.append("body=body")
    args.append(f"response={op.result or 'None'}")
    args.append("timeout=timeout")
    call = f"self._request({', '.join(args)})"
    out.append(f"        return {'await ' if is_async else ''}{call}")
    return out


def emit_api(api: API, shared: set[str], file: str) -> str:
    out = ["# " + HEADER.format(file=file), "# ruff: noqa: E501", "", "from __future__ import annotations", ""]
    out += ["from datetime import datetime  # noqa: F401", "from typing import TYPE_CHECKING, Any", ""]
    out.append("from .._transport import _seg")
    used = sorted({op.result for op in api.operations if op.result})
    enum_params = sorted({p.type.enum_name for op in api.operations for p in op.query + op.path_params if p.type.kind == "enum"})
    out.append(f"from .models_{api.name} import {', '.join(used)}")
    if enum_params:
        out.append(f"from .models_{api.name} import {', '.join(enum_params)}")
    out += ["", "if TYPE_CHECKING:", "    from .._transport import AsyncTransport, SyncTransport", ""]
    for is_async in (False, True):
        cls = ("Async" if is_async else "") + CLASS[api.name]
        base = "AsyncTransport" if is_async else "SyncTransport"
        out += ["", f"class {cls}:"]
        out += _doc([f"Endpoint methods for the {api.title} ({api.base_path})."], "    ")
        out += ["", f"    _request: Any  # provided by {base}", ""]
        for i, op in enumerate(api.operations):
            if i:
                out.append("")
            out += _method(api, op, is_async)
        out.append("")
    return "\n".join(out)
