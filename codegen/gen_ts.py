"""TypeScript emitter: interfaces plus an abstract class of endpoint methods
that the handwritten clients in typescript/src extend."""

from __future__ import annotations

from common import HEADER, paragraphs
from ir import API, Operation, Type

CLASS = {"v1": "DynastyAPI", "partner": "PartnerAPI"}


def _doc(lines: list[str], indent: str = "") -> list[str]:
    if not lines:
        return []
    lines = [l.replace("*/", "*\\/") for l in lines]
    if len(lines) == 1:
        return [f"{indent}/** {lines[0]} */"]
    return [f"{indent}/**"] + [f"{indent} *{(' ' + l) if l else ''}" for l in lines] + [f"{indent} */"]


def _ts(t: Type) -> str:
    k = t.kind
    if k in ("string", "datetime"):
        s = "string"
    elif k in ("integer", "number"):
        s = "number"
    elif k == "boolean":
        s = "boolean"
    elif k == "any":
        s = "Record<string, unknown>"
    elif k in ("ref", "enum"):
        s = t.ref if k == "ref" else t.enum_name
    elif k == "array":
        inner = _ts(t.item)
        s = f"({inner})[]" if "|" in inner else f"{inner}[]"
    elif k == "map":
        s = f"Record<string, {_ts(t.item)}>"
    else:
        raise ValueError(k)
    return f"{s} | null" if t.nullable else s


def _key(name: str) -> str:
    return name if name.isidentifier() else f'"{name}"'


def _field_doc(doc: str, t: Type) -> list[str]:
    lines = paragraphs(doc)
    if t.kind == "datetime":
        lines.append("RFC 3339 timestamp.")
    return lines


def _query_type(op: Operation) -> str:
    return op.id[:1].upper() + op.id[1:] + "Query"


def _method(api: API, op: Operation) -> list[str]:
    args, opts = [], []
    for p in op.path_params:
        args.append(f"{p.name}: {_ts(p.type)}")
    if op.body:
        args.append(f"body{'' if op.body_required else '?'}: {op.body}")
    if op.query:
        req = any(q.required for q in op.query)
        args.append(f"query{'' if req else '?'}: {_query_type(op)}")
        opts.append("query")
    if op.body:
        opts.append("body")
    args.append("options?: RequestOptions")
    path = op.path
    for p in op.path_params:
        path = path.replace("{" + p.name + "}", "${encodeURIComponent(String(" + p.name + "))}")
    path_expr = f"`{path}`" if op.path_params else f'"{path}"'
    result = op.result or "void"
    doc = paragraphs(op.summary, op.doc) + ["", f"`{op.method} {api.base_path}{op.path}`"]
    out = _doc(doc, "  ")
    out.append(f"  {op.id}({', '.join(args)}): Promise<{result}> {{")
    extra = "".join(f"{o}, " for o in opts)
    out.append(f'    return this.request<{result}>("{op.method}", {path_expr}, {{ {extra}...options }});')
    out.append("  }")
    return out


def emit(api: API, shared: set[str], file: str) -> str:
    out = ["// " + HEADER.format(file=file), ""]
    out.append('import { Transport, type RequestOptions } from "../runtime.js";')
    reuse = sorted(shared) if api.name == "partner" else []
    if reuse:
        out.append(f'import type {{ {", ".join(reuse)} }} from "./v1.js";')
        out.append(f'export type {{ {", ".join(reuse)} }} from "./v1.js";')
    out.append("")

    for name, values in api.enums.items():
        out.append(f"/** Known values; newer servers may send others. */")
        out.append(f"export type {name} = {' | '.join(repr(v).replace(chr(39), chr(34)) for v in values)} | (string & {{}});")
        out.append("")

    for name, s in api.schemas.items():
        if name in reuse:
            continue
        out += _doc(paragraphs(s.doc))
        out.append(f"export interface {name} {{")
        for f in s.fields:
            out += _doc(_field_doc(f.doc, f.type), "  ")
            out.append(f"  {_key(f.name)}{'' if f.required else '?'}: {_ts(f.type)};")
        out.append("}")
        out.append("")

    for op in api.operations:
        if not op.query:
            continue
        out.append(f"/** Query parameters for {{@link {CLASS[api.name]}.{op.id}}}. */")
        out.append(f"export interface {_query_type(op)} {{")
        for q in op.query:
            out += _doc(paragraphs(q.doc), "  ")
            out.append(f"  {_key(q.name)}{'' if q.required else '?'}: {_ts(q.type)};")
        out.append("}")
        out.append("")

    out += _doc(paragraphs(f"Endpoint methods for the {api.title} ({api.base_path})."))
    out.append(f"export abstract class {CLASS[api.name]} extends Transport {{")
    for i, op in enumerate(api.operations):
        if i:
            out.append("")
        out += _method(api, op)
    out.append("}")
    out.append("")
    return "\n".join(out)
