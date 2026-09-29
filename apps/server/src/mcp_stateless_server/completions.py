"""Deterministic completion registration for note resources and prompts."""

from mcp.server import MCPServer
from mcp_types import (
    Completion,
    CompletionArgument,
    CompletionContext,
    PromptReference,
    ResourceTemplateReference,
)

from mcp_stateless_server.store import NoteStore

SUMMARY_STYLES = ("brief", "detailed")


def register_completions(mcp: MCPServer, store: NoteStore) -> None:
    """Register stable prefix completion for known primitive arguments."""

    @mcp.completion()  # type: ignore[no-untyped-call,untyped-decorator]
    async def complete_argument(
        ref: PromptReference | ResourceTemplateReference,
        argument: CompletionArgument,
        context: CompletionContext | None,
    ) -> Completion | None:
        del context
        candidates: tuple[str, ...] | None = None
        if isinstance(ref, PromptReference) and ref.name == "summarize_note":
            if argument.name == "note_id":
                candidates = tuple(note.note_id for note in store.list_notes())
            elif argument.name == "style":
                candidates = SUMMARY_STYLES
        elif (
            isinstance(ref, ResourceTemplateReference)
            and ref.uri == "notes://{note_id}"
            and argument.name == "note_id"
        ):
            candidates = tuple(note.note_id for note in store.list_notes())

        if candidates is None:
            return None
        prefix = argument.value.casefold()
        matches = [value for value in candidates if value.casefold().startswith(prefix)]
        return Completion(values=matches[:100], total=len(matches), has_more=len(matches) > 100)
