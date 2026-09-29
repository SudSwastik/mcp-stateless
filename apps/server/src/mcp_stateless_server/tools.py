"""Core tool registrations."""

import hashlib
import json
from typing import Annotated, Literal

from mcp.server import MCPServer
from mcp.server.mcpserver import (
    AcceptedElicitation,
    CancelledElicitation,
    Context,
    DeclinedElicitation,
    Elicit,
    ElicitationResult,
    Resolve,
)
from mcp.server.mcpserver.exceptions import ToolError
from mcp_types import (
    CallToolResult,
    ElicitRequest,
    ElicitRequestURLParams,
    ElicitResult,
    InputRequiredResult,
    ResourceLink,
    TextContent,
)
from pydantic import BaseModel, Field

from mcp_stateless_server.models import (
    AddResult,
    ConnectProviderResult,
    NoteMutationResult,
    PublishNoteResult,
    SearchNotesResult,
)
from mcp_stateless_server.pagination import CursorError
from mcp_stateless_server.store import NoteStore
from mcp_stateless_server.tasks import (
    TASKS_EXTENSION_ID,
    ReindexNotesResult,
    ReindexTaskStore,
    task_owner,
)


class NoteTitle(BaseModel):
    """Validated title requested from the user when omitted."""

    title: str = Field(min_length=1, max_length=120)


class DeleteConfirmation(BaseModel):
    """Explicit confirmation for a destructive note deletion."""

    confirm: bool


class PublishAudience(BaseModel):
    """Audience selected for a note publication."""

    audience: Literal["team", "public"]


class PublishConfirmation(BaseModel):
    """Final confirmation to publish a note."""

    confirm: bool


def register_tools(mcp: MCPServer, store: NoteStore, tasks: ReindexTaskStore) -> None:
    """Register deterministic tools on the supplied server."""

    @mcp.tool()
    def add(a: int, b: int) -> AddResult:
        """Add two integers."""
        return AddResult(result=a + b)

    def resolve_create_title(
        title: str | None,
    ) -> NoteTitle | Elicit[NoteTitle]:
        if title is not None and title.strip():
            return NoteTitle(title=title.strip())
        return Elicit(message="What title should this note have?", schema=NoteTitle)

    def resolve_delete_confirmation(
        note_id: str,
    ) -> DeleteConfirmation | Elicit[DeleteConfirmation]:
        if store.get(note_id) is None:
            return DeleteConfirmation(confirm=False)
        return Elicit(
            message=f"Delete note {note_id}? This cannot be undone.",
            schema=DeleteConfirmation,
        )

    def resolve_publish_audience(
        note_id: str,
    ) -> PublishAudience | Elicit[PublishAudience]:
        if store.get(note_id) is None:
            return PublishAudience(audience="team")
        return Elicit(
            message="Who should be able to see this note?",
            schema=PublishAudience,
        )

    def resolve_publish_confirmation(
        note_id: str,
        audience: Annotated[
            ElicitationResult[PublishAudience], Resolve(resolve_publish_audience)
        ],
    ) -> PublishConfirmation | Elicit[PublishConfirmation]:
        if store.get(note_id) is None or not isinstance(audience, AcceptedElicitation):
            return PublishConfirmation(confirm=False)
        return Elicit(
            message=f"Publish this note to the {audience.data.audience}?",
            schema=PublishConfirmation,
        )

    @mcp.tool()
    async def create_note(
        body: str,
        ctx: Context,
        resolved_title: Annotated[ElicitationResult[NoteTitle], Resolve(resolve_create_title)],
        title: str | None = None,
    ) -> NoteMutationResult:
        """Create a note, asking for a missing title through MRTR."""
        if isinstance(resolved_title, DeclinedElicitation):
            return NoteMutationResult(action="declined")
        if isinstance(resolved_title, CancelledElicitation):
            return NoteMutationResult(action="cancelled")

        idempotency_key = _request_state_key(ctx.request_state)
        note, changed = store.create(
            resolved_title.data.title,
            body,
            idempotency_key=idempotency_key,
        )
        if changed:
            await _notify_note_change(ctx, note.note_id)
        return NoteMutationResult(action="created", note=note)

    @mcp.tool()
    async def delete_note(
        note_id: str,
        ctx: Context,
        confirmation: Annotated[
            ElicitationResult[DeleteConfirmation], Resolve(resolve_delete_confirmation)
        ],
    ) -> NoteMutationResult:
        """Delete a note only after explicit MRTR confirmation."""
        if store.get(note_id) is None:
            return NoteMutationResult(action="not_found")
        if isinstance(confirmation, DeclinedElicitation):
            return NoteMutationResult(action="declined")
        if isinstance(confirmation, CancelledElicitation):
            return NoteMutationResult(action="cancelled")
        if not confirmation.data.confirm:
            return NoteMutationResult(action="declined")

        note, changed = store.delete(
            note_id,
            idempotency_key=_request_state_key(ctx.request_state),
        )
        if note is None:
            return NoteMutationResult(action="not_found")
        if changed:
            await _notify_note_change(ctx, note.note_id)
        return NoteMutationResult(action="deleted", note=note)

    @mcp.tool()
    def publish_note(
        note_id: str,
        ctx: Context,
        audience: Annotated[
            ElicitationResult[PublishAudience], Resolve(resolve_publish_audience)
        ],
        confirmation: Annotated[
            ElicitationResult[PublishConfirmation], Resolve(resolve_publish_confirmation)
        ],
    ) -> PublishNoteResult:
        """Publish a note after sequential audience selection and confirmation."""
        if store.get(note_id) is None:
            return PublishNoteResult(action="not_found", note_id=note_id)
        if isinstance(audience, DeclinedElicitation):
            return PublishNoteResult(action="declined", note_id=note_id)
        if isinstance(audience, CancelledElicitation):
            return PublishNoteResult(action="cancelled", note_id=note_id)
        if isinstance(confirmation, DeclinedElicitation):
            return PublishNoteResult(action="declined", note_id=note_id)
        if isinstance(confirmation, CancelledElicitation):
            return PublishNoteResult(action="cancelled", note_id=note_id)
        if not confirmation.data.confirm:
            return PublishNoteResult(action="declined", note_id=note_id)
        published_audience, _changed = store.publish(
            note_id,
            audience.data.audience,
            idempotency_key=_request_state_key(ctx.request_state),
        )
        if published_audience is None:
            return PublishNoteResult(action="not_found", note_id=note_id)
        return PublishNoteResult(
            action="published", note_id=note_id, audience=published_audience
        )

    @mcp.tool()
    async def connect_provider(
        provider: Literal["github", "google"],
        ctx: Context,
    ) -> ConnectProviderResult | InputRequiredResult:
        """Connect a provider using URL-mode out-of-band authorization."""
        response_key = "mcp_stateless_server.tools:connect_provider:authorization"
        request = ElicitRequest(
            params=ElicitRequestURLParams(
                message=f"Continue to {provider.title()} to authorize this demo connection.",
                url=f"https://auth.example.test/{provider}/authorize",
            )
        )
        if ctx.request_state is None:
            return InputRequiredResult(
                input_requests={response_key: request},
                request_state=json.dumps({"provider": provider}, separators=(",", ":")),
            )

        try:
            state = json.loads(ctx.request_state)
        except json.JSONDecodeError as exc:
            raise ToolError("Invalid provider authorization request state.") from exc
        if state != {"provider": provider}:
            raise ToolError("Provider authorization request state does not match this call.")

        responses = ctx.input_responses or {}
        result = responses.get(response_key)
        if not isinstance(result, ElicitResult):
            return InputRequiredResult(
                input_requests={response_key: request}, request_state=ctx.request_state
            )
        if result.action == "decline":
            return ConnectProviderResult(action="declined", provider=provider)
        if result.action == "cancel":
            return ConnectProviderResult(action="cancelled", provider=provider)

        # This deterministic demo treats navigation consent as successful external
        # completion. No authorization code or provider credential enters MCP.
        store.connect_provider(provider)
        return ConnectProviderResult(action="connected", provider=provider)

    @mcp.tool()
    def search_notes(
        query: str,
        limit: Annotated[int, Field(ge=1, le=100)] = 10,
        cursor: str | None = None,
    ) -> Annotated[CallToolResult, SearchNotesResult]:
        """Search notes by title or body text with stable cursor pagination."""
        try:
            page = store.search_page(query, limit, cursor)
        except CursorError as exc:
            raise ToolError(str(exc)) from exc
        result = SearchNotesResult(
            query=query,
            notes=list(page.notes),
            count=len(page.notes),
            total=page.total,
            next_cursor=page.next_cursor,
        )
        links = [
            ResourceLink(
                type="resource_link",
                uri=f"notes://{note.note_id}",
                name=note.title,
                description=f"Note {note.note_id}",
                mime_type="application/json",
            )
            for note in page.notes
        ]
        return CallToolResult(
            content=[
                TextContent(
                    type="text",
                    text=f"Found {page.total} matching notes; returned {len(page.notes)}.",
                ),
                *links,
            ],
            structured_content=result.model_dump(mode="json"),
        )

    @mcp.tool()
    def reindex_notes(
        ctx: Context,
        simulate_failure: bool = False,
    ) -> ReindexNotesResult:
        """Reindex notes, returning a task handle when the client supports tasks."""
        note_ids = [note.note_id for note in store.list_notes()]
        capabilities = ctx.client_capabilities
        if (
            ctx.protocol_version == "2026-07-28"
            and capabilities is not None
            and TASKS_EXTENSION_ID in (capabilities.extensions or {})
        ):
            task = tasks.create(
                task_owner(ctx.request_context), note_ids, fail=simulate_failure
            )
            return ReindexNotesResult(action="task_started", task=task)
        if simulate_failure:
            return ReindexNotesResult(action="failed", indexed_note_ids=[])
        return ReindexNotesResult(action="completed", indexed_note_ids=note_ids)


def _request_state_key(request_state: str | None) -> str | None:
    if request_state is None:
        return None
    return hashlib.sha256(request_state.encode("utf-8")).hexdigest()


async def _notify_note_change(ctx: Context, note_id: str) -> None:
    await ctx.notify_resources_changed()
    for uri in ("notes://all", "notes://stats", f"notes://{note_id}"):
        await ctx.notify_resource_updated(uri)
