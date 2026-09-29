"""Interactive and deterministic callbacks for modern MCP elicitation."""

from __future__ import annotations

import json
import sys
from typing import Any, cast

from mcp.client.session import ClientRequestContext, ElicitationFnT
from mcp_types import (
    INVALID_REQUEST,
    ElicitRequestFormParams,
    ElicitRequestParams,
    ElicitResult,
    ErrorData,
)

from mcp_stateless_client.config import ElicitationPolicy


def make_elicitation_callback(policy: ElicitationPolicy) -> ElicitationFnT:
    """Build a callback that handles form requests without exposing them to tool output."""

    async def respond(
        _context: ClientRequestContext,
        params: ElicitRequestParams,
    ) -> ElicitResult | ErrorData:
        if not isinstance(params, ElicitRequestFormParams):
            return ErrorData(
                code=INVALID_REQUEST,
                message="This CLI supports form-mode elicitation only.",
            )
        if policy == "decline":
            return ElicitResult(action="decline")
        if policy == "cancel":
            return ElicitResult(action="cancel")
        if policy == "interactive":
            return _interactive_response(params)
        content = _example_content(params.requested_schema)
        return ElicitResult(action="accept", content=content)

    return cast(ElicitationFnT, respond)


def _interactive_response(params: ElicitRequestFormParams) -> ElicitResult:
    print(params.message, file=sys.stderr)
    print("Respond [a]ccept, [d]ecline, or [c]ancel.", file=sys.stderr)
    while True:
        try:
            action = input("> ").strip().casefold()
        except EOFError:
            return ElicitResult(action="cancel")
        if action in {"d", "decline"}:
            return ElicitResult(action="decline")
        if action in {"c", "cancel"}:
            return ElicitResult(action="cancel")
        if action in {"a", "accept"}:
            break
        print("Enter a, d, or c.", file=sys.stderr)

    schema = params.requested_schema
    properties = schema.get("properties", {})
    required = set(schema.get("required", []))
    result: dict[str, Any] = {}
    for name, definition in properties.items():
        prompt = f"{name} ({definition.get('type', 'value')})"
        if definition.get("enum"):
            prompt += f" choices={definition['enum']}"
        while True:
            try:
                raw = input(f"{prompt}: ").strip()
            except EOFError:
                return ElicitResult(action="cancel")
            if not raw and "default" in definition:
                result[name] = definition["default"]
                break
            if not raw and name not in required:
                break
            try:
                result[name] = _parse_value(raw, definition)
                break
            except ValueError:
                print(f"Invalid value for {name}; please try again.", file=sys.stderr)
    return ElicitResult(action="accept", content=result)


def _parse_value(raw: str, definition: dict[str, Any]) -> Any:
    if "enum" in definition and raw not in definition["enum"]:
        raise ValueError("value is not one of the allowed choices")
    kind = definition.get("type")
    if kind == "boolean":
        normalized = raw.casefold()
        if normalized in {"true", "yes", "y"}:
            value: Any = True
        elif normalized in {"false", "no", "n"}:
            value = False
        else:
            raise ValueError("expected yes or no")
    elif kind in {"integer", "number"}:
        value = json.loads(raw)
        if isinstance(value, bool) or not isinstance(value, int | float):
            raise ValueError("expected a number")
    else:
        value = raw

    if kind == "string":
        if len(value) < int(definition.get("minLength", 0)):
            raise ValueError("value is too short")
        if "maxLength" in definition and len(value) > int(definition["maxLength"]):
            raise ValueError("value is too long")
    if isinstance(value, int | float) and not isinstance(value, bool):
        if "minimum" in definition and value < definition["minimum"]:
            raise ValueError("value is below the minimum")
        if "maximum" in definition and value > definition["maximum"]:
            raise ValueError("value is above the maximum")
    return value


def _example_content(schema: dict[str, Any]) -> dict[str, Any]:
    """Generate repeatable, schema-valid examples for non-interactive acceptance."""
    properties = schema.get("properties", {})
    required = set(schema.get("required", []))
    result: dict[str, Any] = {}
    for name, definition in properties.items():
        if name not in required and "default" not in definition:
            continue
        if "default" in definition:
            value = definition["default"]
        elif definition.get("enum"):
            value = definition["enum"][0]
        elif definition.get("type") == "boolean":
            value = name.casefold() in {"confirm", "approved", "accept"}
        elif definition.get("type") == "integer":
            value = int(definition.get("minimum", 0))
            if "maximum" in definition:
                value = min(value, int(definition["maximum"]))
        elif definition.get("type") == "number":
            value = float(definition.get("minimum", 0))
            if "maximum" in definition:
                value = min(value, float(definition["maximum"]))
        else:
            value = "Elicited title" if name.casefold() == "title" else "example"
            value = value[: int(definition.get("maxLength", len(value)))]
            value = value.ljust(int(definition.get("minLength", 0)), "x")
        result[name] = value
    return result
