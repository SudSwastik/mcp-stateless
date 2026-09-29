"""SDK-backed MCP primitive operations and compatibility catalogs."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Awaitable, Callable, Coroutine, Sequence
from dataclasses import dataclass
from typing import Any

from httpx2 import TransportError as HttpTransportError
from mcp import Client
from mcp.shared.exceptions import MCPError
from mcp.shared.subscriptions import ServerEvent
from mcp_types import (
    CallToolResult,
    CompleteResult,
    DiscoverResult,
    GetPromptResult,
    Implementation,
    Prompt,
    PromptReference,
    ReadResourceResult,
    Resource,
    ResourceTemplate,
    ResourceTemplateReference,
    Tool,
)
from pydantic import BaseModel, ValidationError

from mcp_stateless_client.config import ClientConfig
from mcp_stateless_client.discovery import (
    CLIENT_NAME,
    CLIENT_VERSION,
    ClientError,
    DiscoveryObservation,
    ProtocolError,
    TransportError,
    VerificationCheck,
    VerificationReport,
    discover,
    verify,
)


class CommandInputError(ClientError):
    """A local command argument is malformed."""

    category = "input"


@dataclass(frozen=True, slots=True)
class PrimitiveCatalog:
    """All advertised primitive definitions, traversed across every page."""

    discovery: DiscoveryObservation
    tools: tuple[Tool, ...]
    resources: tuple[Resource, ...]
    resource_templates: tuple[ResourceTemplate, ...]
    prompts: tuple[Prompt, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "discovery": self.discovery.to_dict(),
            "tools": [_model_dict(tool) for tool in self.tools],
            "resources": [_model_dict(resource) for resource in self.resources],
            "resourceTemplates": [_model_dict(template) for template in self.resource_templates],
            "prompts": [_model_dict(prompt) for prompt in self.prompts],
        }


@dataclass(frozen=True, slots=True)
class CompatibilityReport:
    """Transport and primitive-catalog compatibility results."""

    transport: VerificationReport
    catalog: PrimitiveCatalog
    primitive_checks: tuple[VerificationCheck, ...]

    @property
    def checks(self) -> tuple[VerificationCheck, ...]:
        return (*self.transport.checks, *self.primitive_checks)

    @property
    def passed(self) -> bool:
        return all(check.passed for check in self.checks)

    def to_dict(self) -> dict[str, Any]:
        return {
            "serverUrl": self.transport.server_url,
            "protocolVersion": self.transport.protocol_version,
            "passed": self.passed,
            "checks": [check.to_dict() for check in self.checks],
            "transport": self.transport.to_dict(),
            "catalog": self.catalog.to_dict(),
        }


def _client(config: ClientConfig, prior_discover: DiscoverResult | None = None) -> Client:
    try:
        return Client(
            config.server_url,
            mode=config.protocol_version,
            prior_discover=prior_discover,
            client_info=Implementation(name=CLIENT_NAME, version=CLIENT_VERSION),
            read_timeout_seconds=config.request_timeout_seconds,
        )
    except ValueError as exc:
        raise ProtocolError(
            f"The installed MCP SDK cannot use protocol {config.protocol_version!r}: {exc}"
        ) from exc


def _model_dict(model: BaseModel) -> dict[str, Any]:
    return model.model_dump(by_alias=True, mode="json", exclude_none=True)


def _first_nested[T: BaseException](error: BaseException, error_type: type[T]) -> T | None:
    if isinstance(error, error_type):
        return error
    if isinstance(error, BaseExceptionGroup):
        for nested in error.exceptions:
            if (match := _first_nested(nested, error_type)) is not None:
                return match
    return None


def _run[T](operation: Coroutine[Any, Any, T]) -> T:
    try:
        return asyncio.run(operation)
    except ClientError:
        raise
    except MCPError as exc:
        raise ProtocolError(f"MCP protocol error {exc.code}: {exc.error.message}") from exc
    except ValidationError as exc:
        raise ProtocolError(f"Server response failed MCP schema validation: {exc}") from exc
    except (HttpTransportError, TimeoutError, OSError) as exc:
        raise TransportError(f"Could not communicate with the MCP server: {exc}") from exc
    except BaseExceptionGroup as exc:
        if (protocol_error := _first_nested(exc, MCPError)) is not None:
            raise ProtocolError(
                f"MCP protocol error {protocol_error.code}: {protocol_error.message}"
            ) from exc
        if (validation_error := _first_nested(exc, ValidationError)) is not None:
            raise ProtocolError(
                f"Server response failed MCP schema validation: {validation_error}"
            ) from exc
        for transport_type in (HttpTransportError, TimeoutError, OSError):
            if (transport_error := _first_nested(exc, transport_type)) is not None:
                raise TransportError(
                    f"Could not communicate with the MCP server: {transport_error}"
                ) from exc
        raise


async def _collect_pages[T](
    fetch: Callable[[str | None], Awaitable[tuple[Sequence[T], str | None]]],
) -> tuple[T, ...]:
    values: list[T] = []
    cursor: str | None = None
    seen_cursors: set[str] = set()
    while True:
        page, next_cursor = await fetch(cursor)
        values.extend(page)
        if next_cursor is None:
            return tuple(values)
        if next_cursor in seen_cursors:
            raise ProtocolError(f"Server repeated pagination cursor {next_cursor!r}")
        seen_cursors.add(next_cursor)
        cursor = next_cursor


async def _catalog(config: ClientConfig, discovery: DiscoveryObservation) -> PrimitiveCatalog:
    async with _client(config, discovery.result) as client:
        capabilities = discovery.result.capabilities

        async def tools_page(cursor: str | None) -> tuple[Sequence[Tool], str | None]:
            result = await client.list_tools(cursor=cursor)
            return result.tools, result.next_cursor

        async def resources_page(cursor: str | None) -> tuple[Sequence[Resource], str | None]:
            result = await client.list_resources(cursor=cursor)
            return result.resources, result.next_cursor

        async def templates_page(
            cursor: str | None,
        ) -> tuple[Sequence[ResourceTemplate], str | None]:
            result = await client.list_resource_templates(cursor=cursor)
            return result.resource_templates, result.next_cursor

        async def prompts_page(cursor: str | None) -> tuple[Sequence[Prompt], str | None]:
            result = await client.list_prompts(cursor=cursor)
            return result.prompts, result.next_cursor

        tools = await _collect_pages(tools_page) if capabilities.tools is not None else ()
        if capabilities.resources is not None:
            resources = await _collect_pages(resources_page)
            templates = await _collect_pages(templates_page)
        else:
            resources = ()
            templates = ()
        prompts = await _collect_pages(prompts_page) if capabilities.prompts is not None else ()

    return PrimitiveCatalog(
        discovery=discovery,
        tools=tools,
        resources=resources,
        resource_templates=templates,
        prompts=prompts,
    )


def inspect_catalog(config: ClientConfig) -> PrimitiveCatalog:
    """Discover a server and list every primitive it advertises."""
    observation = discover(config)
    return _run(_catalog(config, observation))


async def _call_tool(config: ClientConfig, name: str, arguments: dict[str, Any]) -> CallToolResult:
    async with _client(config) as client:
        return await client.call_tool(name, arguments)


def call_tool(config: ClientConfig, name: str, arguments: dict[str, Any]) -> CallToolResult:
    """Call a tool directly using the pinned stateless protocol version."""
    return _run(_call_tool(config, name, arguments))


async def _read_resource(config: ClientConfig, uri: str) -> ReadResourceResult:
    async with _client(config) as client:
        return await client.read_resource(uri)


def read_resource(config: ClientConfig, uri: str) -> ReadResourceResult:
    """Read a resource directly using the pinned stateless protocol version."""
    return _run(_read_resource(config, uri))


async def _get_prompt(
    config: ClientConfig, name: str, arguments: dict[str, str]
) -> GetPromptResult:
    async with _client(config) as client:
        return await client.get_prompt(name, arguments)


def get_prompt(config: ClientConfig, name: str, arguments: dict[str, str]) -> GetPromptResult:
    """Render a prompt directly using the pinned stateless protocol version."""
    return _run(_get_prompt(config, name, arguments))


async def _complete_argument(
    config: ClientConfig,
    ref: PromptReference | ResourceTemplateReference,
    argument_name: str,
    value: str,
) -> CompleteResult:
    async with _client(config) as client:
        return await client.complete(ref, {"name": argument_name, "value": value})


def complete_argument(
    config: ClientConfig,
    ref: PromptReference | ResourceTemplateReference,
    argument_name: str,
    value: str = "",
) -> CompleteResult:
    """Request deterministic completion for a prompt or resource argument."""
    return _run(_complete_argument(config, ref, argument_name, value))


async def listen(
    config: ClientConfig,
    *,
    tools_list_changed: bool = False,
    prompts_list_changed: bool = False,
    resources_list_changed: bool = False,
    resource_subscriptions: Sequence[str] = (),
) -> AsyncIterator[ServerEvent]:
    """Yield only the change events requested from a modern MCP server."""
    client = _client(config)
    async with client, client.listen(
        tools_list_changed=tools_list_changed,
        prompts_list_changed=prompts_list_changed,
        resources_list_changed=resources_list_changed,
        resource_subscriptions=resource_subscriptions,
    ) as subscription:
        async for event in subscription:
            yield event


def _completion_check(config: ClientConfig, catalog: PrimitiveCatalog) -> VerificationCheck:
    if catalog.discovery.result.capabilities.completions is None:
        return VerificationCheck(
            name="completion",
            passed=True,
            detail="server does not advertise completion",
        )
    target = next(
        (
            (prompt.name, argument.name)
            for prompt in catalog.prompts
            for argument in (prompt.arguments or ())
        ),
        None,
    )
    if target is None:
        return VerificationCheck(
            name="completion",
            passed=False,
            detail="completion is advertised but no prompt argument can be probed",
        )
    prompt_name, argument_name = target
    ref = PromptReference(name=prompt_name)
    first = complete_argument(config, ref, argument_name)
    second = complete_argument(config, ref, argument_name)
    stable = first.completion.values == second.completion.values
    return VerificationCheck(
        name="completion",
        passed=stable,
        detail=(
            f"stable suggestions for {prompt_name}.{argument_name}: {first.completion.values!r}"
            if stable
            else f"unstable suggestions for {prompt_name}.{argument_name}"
        ),
    )


def _primitive_checks(
    config: ClientConfig, catalog: PrimitiveCatalog
) -> tuple[VerificationCheck, ...]:
    capabilities = catalog.discovery.result.capabilities
    invalid_tool_schemas = [
        tool.name for tool in catalog.tools if tool.input_schema.get("type") != "object"
    ]
    return (
        VerificationCheck(
            name="tool_catalog",
            passed=capabilities.tools is None or bool(catalog.tools),
            detail=f"listed {len(catalog.tools)} tools",
        ),
        VerificationCheck(
            name="tool_schemas",
            passed=not invalid_tool_schemas,
            detail=(
                "all tool input schemas have an object root"
                if not invalid_tool_schemas
                else f"invalid schemas: {', '.join(invalid_tool_schemas)}"
            ),
        ),
        VerificationCheck(
            name="resource_catalog",
            passed=(
                capabilities.resources is None
                or bool(catalog.resources or catalog.resource_templates)
            ),
            detail=(
                f"listed {len(catalog.resources)} resources and "
                f"{len(catalog.resource_templates)} templates"
            ),
        ),
        VerificationCheck(
            name="prompt_catalog",
            passed=capabilities.prompts is None or bool(catalog.prompts),
            detail=f"listed {len(catalog.prompts)} prompts",
        ),
        _completion_check(config, catalog),
    )


def compatibility_report(config: ClientConfig) -> CompatibilityReport:
    """Build a machine-readable transport and primitive compatibility report."""
    transport = verify(config)
    catalog = inspect_catalog(config)
    return CompatibilityReport(
        transport=transport,
        catalog=catalog,
        primitive_checks=_primitive_checks(config, catalog),
    )
