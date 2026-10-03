"""Build the Japanese client API draft without importing or connecting the client.

Python 3.11+; signatures, overloads, defaults and value fields come from AST.
Japanese descriptions and examples live in docs/client-api-metadata_ja.json.
"""

from __future__ import annotations

import argparse
import ast
import copy
import inspect
import json
from pathlib import Path
import sys
import tomllib


ROOT = Path(__file__).resolve().parents[1]
METADATA = Path("docs/client-api-metadata_ja.json")
OUTPUT = Path("docs/python-api-reference_ja.md")
TICK = chr(96)


def code(value, *, table=False):
    value = str(value)
    if table:
        value = value.replace("|", r"\|")
    return f"{TICK}{value}{TICK}"


def block(language, lines):
    return [TICK * 3 + language, *lines, TICK * 3, ""]


def decorator_name(node):
    if isinstance(node, ast.Call):
        return decorator_name(node.func)
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return node.attr
    return ""


def expression(node):
    # Forward-reference quotes are unnecessary in the displayed annotation.
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    return ast.unparse(node)


def public_methods(cls):
    methods = {}
    for node in cls.body:
        if isinstance(node, ast.FunctionDef) and not node.name.startswith("_"):
            methods.setdefault(node.name, []).append(node)
    return methods


def implementation(nodes):
    candidates = [
        node for node in nodes
        if not any(decorator_name(d) == "overload" for d in node.decorator_list)
    ]
    if len(candidates) != 1:
        raise ValueError("each documented method needs one implementation")
    return candidates[0]


def public_arguments(node):
    args = copy.deepcopy(node.args)
    positional = args.posonlyargs if args.posonlyargs else args.args
    if positional and positional[0].arg in ("self", "cls"):
        positional.pop(0)
    return args


def default_text(node, bindings):
    if isinstance(node, ast.Name) and isinstance(bindings.get(node.id), ast.Constant):
        return ast.unparse(bindings[node.id])
    return ast.unparse(node)


def argument_parts(args, bindings):
    positional = [*args.posonlyargs, *args.args]
    defaults = [None] * (len(positional) - len(args.defaults)) + args.defaults

    def part(arg, default=None, prefix=""):
        result = prefix + arg.arg
        if arg.annotation is not None:
            result += ": " + expression(arg.annotation)
        if default is not None:
            result += " = " + default_text(default, bindings)
        return result

    parts = []
    for index, (arg, default) in enumerate(zip(positional, defaults)):
        parts.append(part(arg, default))
        if args.posonlyargs and index + 1 == len(args.posonlyargs):
            parts.append("/")
    if args.vararg is not None:
        parts.append(part(args.vararg, prefix="*"))
    elif args.kwonlyargs:
        parts.append("*")
    parts.extend(part(arg, default) for arg, default in zip(args.kwonlyargs, args.kw_defaults))
    if args.kwarg is not None:
        parts.append(part(args.kwarg, prefix="**"))
    return parts


def signature(node, name, bindings):
    if any(decorator_name(d) == "property" for d in node.decorator_list):
        suffix = ": " + expression(node.returns) if node.returns is not None else ""
        return [name + suffix]
    parts = argument_parts(public_arguments(node), bindings)
    suffix = " -> " + expression(node.returns) if node.returns is not None else ""
    one_line = f"{name}({', '.join(parts)}){suffix}"
    if len(one_line) <= 100:
        return [one_line]
    return [name + "(", *["    " + p + "," for p in parts], ")" + suffix]


def return_annotation(nodes):
    impl = implementation(nodes)
    if impl.returns is not None:
        return expression(impl.returns)
    annotations = {expression(n.returns) for n in nodes if n.returns is not None}
    return next(iter(annotations)) if len(annotations) == 1 else None


def notes(lines):
    return [*["- " + line for line in lines], ""] if len(lines) > 1 else [*lines, ""]


def has_sentinel_default(node, bindings):
    defaults = [*node.args.defaults, *node.args.kw_defaults]
    for default in defaults:
        value = bindings.get(default.id) if isinstance(default, ast.Name) else None
        if isinstance(value, ast.Call) and isinstance(value.func, ast.Name):
            if value.func.id == "object":
                return True
    return False


def bind_signature(node):
    """Validate example argument names/counts without evaluating any expression."""
    args = public_arguments(node)
    positional = [*args.posonlyargs, *args.args]
    defaults = [inspect.Parameter.empty] * (len(positional) - len(args.defaults))
    defaults += [None] * len(args.defaults)
    parameters = []
    for index, (arg, default) in enumerate(zip(positional, defaults)):
        kind = inspect.Parameter.POSITIONAL_ONLY if index < len(args.posonlyargs) else inspect.Parameter.POSITIONAL_OR_KEYWORD
        parameters.append(inspect.Parameter(arg.arg, kind, default=default))
    if args.vararg is not None:
        parameters.append(inspect.Parameter(args.vararg.arg, inspect.Parameter.VAR_POSITIONAL))
    for arg, default in zip(args.kwonlyargs, args.kw_defaults):
        value = inspect.Parameter.empty if default is None else None
        parameters.append(inspect.Parameter(arg.arg, inspect.Parameter.KEYWORD_ONLY, default=value))
    if args.kwarg is not None:
        parameters.append(inspect.Parameter(args.kwarg.arg, inspect.Parameter.VAR_KEYWORD))
    return inspect.Signature(parameters)


def validate_example(lines, methods, where):
    tree = ast.parse("\n".join(lines), filename=where)
    for call in ast.walk(tree):
        if not isinstance(call, ast.Call) or not isinstance(call.func, ast.Attribute):
            continue
        owner = call.func.value
        if not isinstance(owner, ast.Name) or owner.id not in ("mc", "Minecraft"):
            continue
        name = call.func.attr
        if name not in methods:
            raise ValueError(f"{where}: unknown client method {name}")
        if any(isinstance(a, ast.Starred) for a in call.args) or any(k.arg is None for k in call.keywords):
            # Expanded values cannot be resolved statically.
            continue
        bind_signature(implementation(methods[name])).bind(
            *[None for _ in call.args], **{k.arg: None for k in call.keywords}
        )


def generate(root):
    metadata = json.loads((root / METADATA).read_text(encoding="utf-8"))
    if metadata["schema_version"] != 1:
        raise ValueError("unsupported client API metadata schema")
    modules = {}

    def module(path):
        if path not in modules:
            modules[path] = ast.parse((root / path).read_text(encoding="utf-8"))
        return modules[path]

    source = "mc_remote/minecraft.py"
    tree = module(source)
    cls = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == "Minecraft")
    methods = public_methods(cls)
    if set(methods) != set(metadata["methods"]):
        missing = sorted(set(methods) - set(metadata["methods"]))
        obsolete = sorted(set(metadata["methods"]) - set(methods))
        raise ValueError(f"method coverage: missing={missing}, obsolete={obsolete}")
    group_ids = [group["id"] for group in metadata["groups"]]
    if len(set(group_ids)) != len(group_ids):
        raise ValueError("duplicate client API group")
    for name, item in metadata["methods"].items():
        if item["group"] not in group_ids:
            raise ValueError(f"{name}: unknown group")
    for example in metadata["examples"]:
        validate_example(example["code"], methods, example["title"])

    bindings = {}
    for node in tree.body:
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name):
                    bindings[target.id] = node.value
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            bindings[node.target.id] = node.value
    protocol = ast.literal_eval(bindings["PROTOCOL"])
    with (root / "pyproject.toml").open("rb") as stream:
        version = tomllib.load(stream)["project"]["version"]

    lines = [
        "<!-- Generated by scripts/build_client_api_reference.py; edit client-api-metadata_ja.json. -->",
        "# PythonクライアントAPI一覧（ドラフト）",
        "",
        "Pythonから使う操作を、用途別に探すための一覧です。",
        f"対象実装: {code('minecraft-remote-api ' + version)} / Protocol {code(protocol)}。",
        "",
        *[line for paragraph in metadata["introduction"] for line in (paragraph, "")],
        "## 用途から探す",
        "",
        "| 用途 | 主な入口 |",
        "| --- | --- |",
    ]
    for group in metadata["groups"]:
        names = [name for name, item in metadata["methods"].items() if item["group"] == group["id"]]
        labels = "、".join(code(name) for name in names)
        lines.append(f"| [{group['title']}](#{group['id']}) | {labels} |")
    lines += [
        "| [入力・戻り値の型](#values) | ブロック、位置、エンティティ、パーティクル、看板、イベント |",
        "| [例外と警告](#errors) | サーバーの拒否、接続切断、カタログ生成 |",
        "| [短い作例](#examples) | 接続、ブロックの復元、エンティティ、音、イベント |",
        "",
        "## 共通の読み方",
        "",
        *metadata["conventions"],
        "",
    ]
    properties = 0
    for group in metadata["groups"]:
        lines += [f'<a id="{group["id"]}"></a>', "", "## " + group["title"], ""]
        lines += ["| Python | 用途 | 戻り値・値 | 対応するProtocol API |", "| --- | --- | --- | --- |"]
        items = [(name, item) for name, item in metadata["methods"].items() if item["group"] == group["id"]]
        for name, item in items:
            impl = implementation(methods[name])
            is_property = any(decorator_name(d) == "property" for d in impl.decorator_list)
            is_static = any(decorator_name(d) == "staticmethod" for d in impl.decorator_list)
            label = ("Minecraft." if is_static else "mc.") + name + ("" if is_property else "()")
            wire = "、".join(
                f'[{code(p["method"])}](https://mc-remote.com/api/#{p["section"]})' for p in item["protocol"]
            ) or "Python内の補助機能"
            annotation = return_annotation(methods[name])
            returns = code(annotation, table=True) if annotation else item["returns"].split("。", 1)[0]
            lines.append(f"| [{code(label)}](#mc-{name}) | {item['purpose']} | {returns} | {wire} |")
        lines.append("")
        for name, item in items:
            nodes = methods[name]
            impl = implementation(nodes)
            is_property = any(decorator_name(d) == "property" for d in impl.decorator_list)
            properties += is_property
            is_static = any(decorator_name(d) == "staticmethod" for d in impl.decorator_list)
            label = ("Minecraft." if is_static else "mc.") + name
            overloads = [node for node in nodes if node is not impl]
            sentinel = has_sentinel_default(impl, bindings)
            if sentinel and not overloads:
                raise ValueError(f"{name}: a sentinel default needs public overloads")
            lines += [f'<a id="mc-{name}"></a>', "", "### " + code(label), "", item["purpose"] + "。", ""]
            display = overloads if sentinel else [impl]
            for node in display:
                lines += block("text", signature(node, label, bindings))
            lines += ["**戻り値・値:** " + item["returns"], ""]
            if item.get("notes"):
                lines += notes(item["notes"])
            if overloads and not sentinel:
                lines += ["<details>", "<summary>型の書き分け（overload）</summary>", ""]
                for node in overloads:
                    lines += block("text", signature(node, label, bindings))
                lines += ["</details>", ""]
            lines += [f"[実装を見る](../{source}#L{impl.lineno})", ""]

    lines += ['<a id="values"></a>', "", "## 入力・戻り値の型", ""]
    for item in metadata["values"]:
        value_tree = module(item["source"])
        definitions = {
            node.name if isinstance(node, ast.ClassDef) else node.target.id: node
            for node in value_tree.body
            if isinstance(node, ast.ClassDef)
            or (isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name))
        }
        node = definitions[item["name"]]
        lines += [f'<a id="type-{item["name"]}"></a>', "", "### " + code(item["name"]), "", item["purpose"], ""]
        lines += block("python", [f'from {item["import"]} import {item["name"]}'])
        if isinstance(node, ast.AnnAssign):
            lines += block("text", [item["name"] + " = " + ast.unparse(node.value)])
        else:
            def fields(current):
                result = {}
                for base in current.bases:
                    if isinstance(base, ast.Name) and isinstance(definitions.get(base.id), ast.ClassDef):
                        result.update(fields(definitions[base.id]))
                total = not any(k.arg == "total" and isinstance(k.value, ast.Constant) and k.value.value is False for k in current.keywords)
                for field in current.body:
                    if isinstance(field, ast.AnnAssign) and isinstance(field.target, ast.Name) and not field.target.id.startswith("_"):
                        default = ast.unparse(field.value) if field.value is not None else ("省略可" if not total else "必須")
                        result[field.target.id] = (expression(field.annotation), default)
                return result
            value_fields = fields(node)
            if value_fields:
                lines += ["| フィールド | 型 | 既定値・省略 |", "| --- | --- | --- |"]
                for name, (annotation, default) in sorted(value_fields.items(), key=lambda row: row[1][1] != "必須"):
                    lines.append(f"| {code(name)} | {code(annotation, table=True)} | {code(default, table=True)} |")
                lines.append("")
            if item["name"] == "BuildMode":
                for field in node.body:
                    if isinstance(field, ast.Assign) and isinstance(field.targets[0], ast.Name):
                        lines.append("- " + code("BuildMode." + field.targets[0].id) + ": " + code(ast.literal_eval(field.value)))
                lines.append("")
        if item.get("notes"):
            lines += notes(item["notes"])
        lines += [f'[定義を見る](../{item["source"]}#L{node.lineno})', ""]

    lines += ['<a id="errors"></a>', "", "## 例外と警告", "", *notes(metadata["error_notes"])]
    lines += ["| 名前 | 意味 | import元 |", "| --- | --- | --- |"]
    for item in metadata["errors"]:
        error_tree = module(item["source"])
        node = next(n for n in error_tree.body if isinstance(n, ast.ClassDef) and n.name == item["name"])
        lines.append(f'| [{code(item["name"])}](../{item["source"]}#L{node.lineno}) | {item["purpose"]} | {code(item["import"])} |')
    lines += ["", '<a id="examples"></a>', "", "## 短い作例", "", *metadata["example_notes"], ""]
    for example in metadata["examples"]:
        lines += ["### " + example["title"], "", example["description"], ""]
        lines += block("python", example["code"])
    lines += [
        "## 一覧の更新",
        "",
        "引数・型注釈・overload・定数の既定値・値オブジェクトのフィールド・版情報は実装から生成します。",
        "用途、戻り値の説明、作例は [metadata](client-api-metadata_ja.json) で補っています。",
        "型注釈がない箇所の説明と、掲載する補助型・例外の範囲はドラフトのレビュー対象です。",
        "",
    ]
    lines += block("bash", [
        "uv run --frozen python scripts/build_client_api_reference.py",
        "uv run --frozen python scripts/build_client_api_reference.py --check",
    ])
    lines += [
        "生成器はPython 3.11以上で動き、サーバーへ接続せずにファイルを読みます。",
        "CIでは生成結果の古さと、Minecraftの公開メソッド／propertyの掲載漏れを確認します。",
        "",
    ]
    return "\n".join(lines), len(methods) - properties, properties


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="fail if the generated draft is stale")
    parser.add_argument("--root", type=Path, default=ROOT, help="repository root")
    parser.add_argument("--output", type=Path, help="alternate output file")
    args = parser.parse_args()
    output = args.output or args.root / OUTPUT
    try:
        text, methods, properties = generate(args.root)
        if args.check:
            if not output.exists() or output.read_bytes() != text.encode("utf-8"):
                print("client API draft is stale; run scripts/build_client_api_reference.py", file=sys.stderr)
                return 1
            print(f"client API draft: current ({methods} methods, {properties} properties)")
        else:
            output.write_text(text, encoding="utf-8", newline="\n")
            print(f"wrote {output} ({methods} methods, {properties} properties)")
    except (ValueError, KeyError, OSError, TypeError, SyntaxError, StopIteration) as exc:
        print(f"client API draft: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
