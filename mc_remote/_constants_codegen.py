"""Generate the CWD ``mc_constants.py`` projection and its typing stub
(wire-format-design §7.2.1, DECISIONS 2026-07-29-04).

This implements 12-python-client/mc-constants-design_ja.md's project-local
CWD generation and ``sys.path`` guarantee from a live ``catalog.get`` fetch.
The projection is intentionally not bundled: since the registry can include
mods, there is no fixed set of "all versions" to ship, so generation only
happens once a live session has a ``catalogHash`` to key it by (see
:meth:`mc_remote.minecraft.Minecraft.sync_constants`).

Only ``block``/``entity``/``particle`` come from the catalog; world
constants (``y_sea`` etc.) are a separate ``hello`` field. The caller folds
those in via ``world_info`` so the generated file still satisfies the
``from mc_constants import block, entity, particle, world_info`` shape the
guide documents.
"""
import keyword
import re

_IDENTIFIER_SUB = re.compile(r"[^0-9A-Za-z_]")


def _to_identifier(name, seen):
    """Turn a catalog id (``"minecraft:oak_log"``, ``"modid:thing"``) into a
    valid, collision-resistant Python identifier: strip the namespace,
    upper-case, non-identifier characters become ``_``. A leading digit gets
    a ``_`` prefix, a Python-keyword collision gets a trailing ``_``, and a
    same-local-name collision across namespaces (e.g. two mods both exposing
    ``thing``) is disambiguated with a numeric suffix rather than silently
    overwritten."""
    local = name.split(":", 1)[-1]
    ident = _IDENTIFIER_SUB.sub("_", local).upper()
    if not ident or ident[0].isdigit():
        ident = f"_{ident}"
    if keyword.iskeyword(ident.lower()):
        ident = f"{ident}_"
    if ident in seen:
        seen[ident] += 1
        ident = f"{ident}_{seen[ident]}"
    else:
        seen[ident] = 0
    return ident


def _named_ids(catalog_ids):
    seen = {}
    return [
        (_to_identifier(full_id, seen), full_id)
        for full_id in sorted(catalog_ids)
    ]


def _class_body(named_ids):
    lines = [f"    {ident} = {full_id!r}" for ident, full_id in named_ids]
    return "\n".join(lines) if lines else "    pass"


def _safe_parameter(name):
    return (
        name.isidentifier()
        and not keyword.iskeyword(name)
        and name != "_MCREMOTE_UNSET"
    )


def _state_builder_body(named_blocks, catalog):
    lines = []
    for ident, block_id in named_blocks:
        properties = sorted(catalog["block"][block_id]["states"])
        lines.append("    @staticmethod")
        if not properties:
            lines.extend((f"    def {ident}():", "        return {}"))
        elif all(_safe_parameter(name) for name in properties):
            params = ", ".join(f"{name}=_MCREMOTE_UNSET" for name in properties)
            lines.extend((f"    def {ident}(*, {params}):", "        state = {}"))
            for name in properties:
                lines.extend(
                    (
                        f"        if {name} is not _MCREMOTE_UNSET:",
                        f"            state[{name!r}] = {name}",
                    )
                )
            lines.append("        return state")
        else:
            # Modded catalogs can legally expose property names that are not
            # Python identifiers. Direct mapping input still supports them.
            lines.extend((f"    def {ident}(**state):", "        return dict(state)"))
        lines.append("")
    return "\n".join(lines).rstrip() if lines else "    pass"


def _literal(values):
    return "Literal[" + ", ".join(repr(value) for value in values) + "]"


def _state_type_name(ident):
    return f"_{ident}_State"


def _stub_state_declaration(ident, entry):
    type_name = _state_type_name(ident)
    states = entry["states"]
    properties = sorted(states)
    if all(_safe_parameter(name) for name in properties):
        lines = [f"class {type_name}(TypedDict, total=False):"]
        lines.extend(
            f"    {name}: {_literal(states[name])}" for name in properties
        )
        if not properties:
            lines.append("    pass")
        return "\n".join(lines)
    fields = ", ".join(
        f"{name!r}: {_literal(states[name])}" for name in properties
    )
    return f"{type_name} = TypedDict({type_name!r}, {{{fields}}}, total=False)"


def _stub_constants_class(name, named_ids, *, typed_blocks=False):
    lines = [f"class {name}:"]
    for ident, full_id in named_ids:
        annotation = (
            f"BlockId[{_state_type_name(ident)}]"
            if typed_blocks
            else f"Literal[{full_id!r}]"
        )
        lines.append(f"    {ident}: {annotation}")
    if len(lines) == 1:
        lines.append("    pass")
    return "\n".join(lines)


def _stub_state_builder(named_blocks, catalog):
    lines = ["class block_state:"]
    for ident, block_id in named_blocks:
        states = catalog["block"][block_id]["states"]
        properties = sorted(states)
        lines.append("    @staticmethod")
        if not properties:
            params = ""
        elif all(_safe_parameter(name) for name in properties):
            params = "*, " + ", ".join(
                f"{name}: {_literal(states[name])} = ..." for name in properties
            )
        else:
            params = "**state: StateScalar"
        lines.append(
            f"    def {ident}({params}) -> {_state_type_name(ident)}: ..."
        )
    if len(lines) == 1:
        lines.append("    pass")
    return "\n".join(lines)


def generate_source(catalog, mc_version, catalog_hash, world_info=None):
    """Build the ``mc_constants.py`` source text for ``catalog`` (a
    :func:`mc_remote.catalog.validate_catalog`-checked ``catalog.get``
    result). ``world_info`` is an optional ``{NAME: value}`` mapping of
    extra module-level constants (e.g. ``{"Y_SEA": 63}`` from the connected
    session's ``hello`` response) folded into a ``world_info`` class."""
    named_blocks = _named_ids(catalog["block"])
    named_entities = _named_ids(catalog["entity"])
    named_particles = _named_ids(catalog["particle"])

    header = (
        "# ==========================================\n"
        "# This file is auto-generated by mc_remote.Minecraft.sync_constants().\n"
        "# Do not edit -- it is regenerated whenever the connected server's\n"
        "# catalogHash changes (a different mc_version or mod registry).\n"
        f"#   mc_version   = {mc_version!r}\n"
        f"#   catalogHash  = {catalog_hash!r}\n"
        f"#   block/entity/particle counts = "
        f"{len(named_blocks)}/{len(named_entities)}/{len(named_particles)}\n"
        "# ==========================================\n\n"
    )

    parts = [
        header,
        f"MC_VERSION = {mc_version!r}\n",
        f"CATALOG_HASH = {catalog_hash!r}\n\n\n",
        "_MCREMOTE_UNSET = object()\n\n\n",
        "class block:\n" + _class_body(named_blocks) + "\n\n\n",
        "class block_state:\n"
        + _state_builder_body(named_blocks, catalog)
        + "\n\n\n",
        "class entity:\n" + _class_body(named_entities) + "\n\n\n",
        "class particle:\n" + _class_body(named_particles) + "\n",
    ]
    if world_info:
        body = "\n".join(f"    {key} = {value!r}" for key, value in world_info.items())
        parts.append("\n\nclass world_info:\n" + (body or "    pass") + "\n")
    return "".join(parts)


def generate_stub(catalog, world_info=None):
    """Build ``mc_constants.pyi`` with catalog-specific state completion."""
    named_blocks = _named_ids(catalog["block"])
    named_entities = _named_ids(catalog["entity"])
    named_particles = _named_ids(catalog["particle"])
    parts = [
        "# Auto-generated by mc_remote.Minecraft.sync_constants().\n",
        "# Do not edit.\n",
        "from typing import Literal, TypedDict\n",
        "from mc_remote.block_value import BlockId, StateScalar\n\n",
        "MC_VERSION: str\n",
        "CATALOG_HASH: str\n\n",
    ]
    for ident, block_id in named_blocks:
        declaration = _stub_state_declaration(ident, catalog["block"][block_id])
        parts.append(declaration + "\n\n")
    parts.extend(
        (
            _stub_constants_class("block", named_blocks, typed_blocks=True) + "\n\n",
            _stub_state_builder(named_blocks, catalog) + "\n\n",
            _stub_constants_class("entity", named_entities) + "\n\n",
            _stub_constants_class("particle", named_particles) + "\n",
        )
    )
    if world_info:
        parts.append("\nclass world_info:\n")
        for key, value in world_info.items():
            parts.append(f"    {key}: Literal[{value!r}]\n")
    return "".join(parts)


def generate_projection(catalog, mc_version, catalog_hash, world_info=None):
    """Return the runtime module and matching catalog-specific typing stub."""
    return (
        generate_source(catalog, mc_version, catalog_hash, world_info=world_info),
        generate_stub(catalog, world_info=world_info),
    )
