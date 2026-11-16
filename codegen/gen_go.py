"""Go emitter: structs, string enum types, params structs and endpoint
methods on the handwritten Client/PartnerClient in go/dynasty."""

from __future__ import annotations

import re

from common import HEADER, paragraphs, pascal, words
from ir import API, Operation, Type

RECV = {"v1": "Client", "partner": "PartnerClient"}
INITIALISMS = {"id", "url", "nil", "ea", "cfp", "api", "json", "http", "utc", "qb", "rb", "wr", "te", "ol", "dl", "lb", "kp", "db", "ip"}


def go_name(s: str) -> str:
    out = ""
    for w in words(s):
        if out and out[-1].isdigit() and w[0].isdigit():
            out += "_"
        out += w.upper() if w.lower() in INITIALISMS else w[:1].upper() + w[1:]
    if not out or out[0].isdigit():
        out = "X" + out
    return out


def _doc(lines: list[str], indent: str = "") -> list[str]:
    return [f"{indent}//{(' ' + l) if l else ''}" for l in lines]


def _go(t: Type, ptr: bool = False) -> str:
    """Go type. ptr forces a pointer for scalar/struct types (optional or
    nullable values); slices and maps use nil instead."""
    k = t.kind
    if k == "string":
        s = "string"
    elif k == "datetime":
        s = "time.Time"
    elif k == "integer":
        s = "int"
    elif k == "number":
        s = "float64"
    elif k == "boolean":
        s = "bool"
    elif k == "any":
        return "json.RawMessage"
    elif k == "ref":
        s = t.ref
    elif k == "enum":
        s = t.enum_name
    elif k == "array":
        return "[]" + _go(t.item, t.item.nullable)
    elif k == "map":
        return "map[string]" + _go(t.item, t.item.nullable)
    else:
        raise ValueError(k)
    return ("*" + s) if (ptr or t.nullable) else s


def _uses_time(api: API) -> bool:
    def has(t: Type) -> bool:
        return t.kind == "datetime" or (t.item is not None and has(t.item))
    return any(has(f.type) for s in api.schemas.values() for f in s.fields)


def _params_type(op: Operation) -> str:
    return go_name(op.id) + "Params"


def _query_value(expr: str, t: Type) -> str:
    k = t.kind
    if k == "integer":
        return f"strconv.Itoa({expr})"
    if k == "number":
        return f"strconv.FormatFloat({expr}, 'f', -1, 64)"
    if k == "boolean":
        return f"strconv.FormatBool({expr})"
    if k == "enum":
        return f"string({expr})"
    return expr


def _method(api: API, op: Operation) -> list[str]:
    recv = RECV[api.name]
    name = go_name(op.id)
    args = ["ctx context.Context"]
    for p in op.path_params:
        args.append(f"{p.name} {_go(p.type)}")
    if op.body:
        args.append(f"body *{op.body}")
    if op.query:
        args.append(f"params *{_params_type(op)}")
    ret = f"(*{op.result}, error)" if op.result else "error"
    doc = paragraphs(f"{name}: {op.summary}" if op.summary else name, op.doc) + ["", f"{op.method} {api.base_path}{op.path}"]
    out = _doc(doc)
    out.append(f"func (c *{recv}) {name}({', '.join(args)}) {ret} {{")
    path = op.path
    fmt_args = []
    for p in op.path_params:
        path = path.replace("{" + p.name + "}", "%s")
        fmt_args.append(f"url.PathEscape({_query_value(p.name, p.type)})")
    path_expr = f'fmt.Sprintf("{path}", {", ".join(fmt_args)})' if fmt_args else f'"{path}"'
    q = "nil"
    if op.query:
        out.append("\tq := url.Values{}")
        out.append("\tif params != nil {")
        for qp in op.query:
            f = go_name(qp.name)
            if qp.required:
                out.append(f'\t\tq.Set("{qp.name}", {_query_value("params." + f, qp.type)})')
            else:
                out.append(f"\t\tif params.{f} != nil {{")
                out.append(f'\t\t\tq.Set("{qp.name}", {_query_value("*params." + f, qp.type)})')
                out.append("\t\t}")
        out.append("\t}")
        q = "q"
    body = "body" if op.body else "nil"
    if op.body:
        # a typed nil pointer must reach the transport as an untyped nil
        out.append("\tvar in any")
        out.append("\tif body != nil {")
        out.append("\t\tin = body")
        out.append("\t}")
        body = "in"
    if op.result:
        out.append(f"\tout := new({op.result})")
        out.append(f'\tif err := c.t.do(ctx, c.dynastyID, "{op.method}", {path_expr}, {q}, {body}, out); err != nil {{')
        out.append("\t\treturn nil, err")
        out.append("\t}")
        out.append("\treturn out, nil")
    else:
        out.append(f'\treturn c.t.do(ctx, c.dynastyID, "{op.method}", {path_expr}, {q}, {body}, nil)')
    out.append("}")
    return out


def emit(api: API, shared: set[str], file: str) -> str:
    out = ["// " + HEADER.format(file=file), "", "package dynasty", ""]
    imports = ["context", "encoding/json", "fmt", "net/url", "strconv", "time"]
    out.append("import (")
    out += [f'\t"{i}"' for i in imports]
    out += [")", ""]
    # keep every import used regardless of what this spec needs
    out += ["var (", "\t_ = context.Background", "\t_ = json.Marshal", "\t_ = fmt.Sprintf", "\t_ = url.PathEscape",
            "\t_ = strconv.Itoa", "\t_ = time.Now", ")", ""]
    skip = shared if api.name == "partner" else set()

    for name, values in api.enums.items():
        out.append(f"// {name} is a string enum. Newer servers may send values not listed here.")
        out.append(f"type {name} string")
        out.append("")
        out.append(f"// Known {name} values.")
        out.append("const (")
        seen = set()
        for v in values:
            c = name + (go_name(v) if v else "Empty")
            if c in seen:
                raise ValueError(f"enum constant clash: {c}")
            seen.add(c)
            out.append(f'\t{c} {name} = "{v}"')
        out.append(")")
        out.append("")

    for name, s in api.schemas.items():
        if name in skip:
            continue
        doc = paragraphs(s.doc)
        out += _doc([f"{name}: {doc[0]}"] + doc[1:] if doc else [f"{name} is a {api.title} schema."])
        out.append(f"type {name} struct {{")
        seen = set()
        for f in s.fields:
            fname = go_name(f.name)
            if fname in seen:
                raise ValueError(f"{name}: Go field clash {fname}")
            seen.add(fname)
            out += _doc(paragraphs(f.doc), "\t")
            typ = _go(f.type, ptr=not f.required)
            tag = f.name + ("" if f.required else ",omitempty")
            out.append(f'\t{fname} {typ} `json:"{tag}"`')
        out.append("}")
        out.append("")

    for op in api.operations:
        if not op.query:
            continue
        pt = _params_type(op)
        out.append(f"// {pt} holds the query parameters of {RECV[api.name]}.{go_name(op.id)}. Nil fields are left out.")
        out.append(f"type {pt} struct {{")
        for q in op.query:
            out += _doc(paragraphs(q.doc), "\t")
            out.append(f"\t{go_name(q.name)} {_go(q.type, ptr=not q.required)}")
        out.append("}")
        out.append("")

    for op in api.operations:
        out += _method(api, op)
        out.append("")
    return "\n".join(out).rstrip() + "\n"
