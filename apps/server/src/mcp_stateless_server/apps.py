"""MCP Apps presentation for the read-only note dashboard."""

from __future__ import annotations

import hashlib
from typing import Any

from mcp.server import MCPServer
from mcp.server.extension import Extension
from mcp_types import CallToolResult, TextContent

from mcp_stateless_server.store import NoteStore

APP_EXTENSION_ID = "io.modelcontextprotocol/ui"
APP_MIME_TYPE = "text/html;profile=mcp-app"

_DASHBOARD_HTML = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Notes dashboard</title>
<style>
:root { color-scheme: light dark; font: 15px system-ui, sans-serif }
body { margin: 0; padding: 24px; background: #101820; color: #f4f6f8 }
h1 { font-size: 1.25rem; margin: 0 0 4px }
.muted { color: #aebbc5 }
.summary { margin: 20px 0; padding: 16px; border: 1px solid #34434e; border-radius: 12px }
.notes { display: grid; gap: 12px }
.note { padding: 16px; border: 1px solid #34434e; border-radius: 12px; background: #182630 }
.note h2 { font-size: 1rem; margin: 0 0 8px }
.note p { white-space: pre-wrap; margin: 0; color: #d0d9df }
</style>
</head>
<body>
<h1>Notes dashboard</h1>
<div class="muted" id="status">Waiting for dashboard data…</div>
<section class="summary" id="summary" hidden></section>
<main class="notes" id="notes"></main>
<script>
const statusNode = document.querySelector('#status');
const summaryNode = document.querySelector('#summary');
const notesNode = document.querySelector('#notes');
function render(data) {
  if (!data || !Array.isArray(data.notes)) {
    statusNode.textContent = 'No dashboard data received.';
    return;
  }
  statusNode.textContent = 'Read-only snapshot';
  summaryNode.hidden = false;
  summaryNode.textContent = `${data.total_notes} notes`;
  notesNode.replaceChildren(...data.notes.map(note => {
    const card = document.createElement('article');
    card.className = 'note';
    const title = document.createElement('h2');
    title.textContent = note.title;
    const body = document.createElement('p');
    body.textContent = note.body;
    card.append(title, body);
    return card;
  }));
}
window.addEventListener('message', event => {
  const message = event.data;
  if (message?.method === 'ui/notifications/tool-result') {
    render(message.params?.structuredContent);
  }
});
if (window.parent === window) {
  statusNode.textContent = 'Open this resource in an MCP Apps host.';
}
</script>
</body>
</html>"""
_DASHBOARD_HASH = hashlib.sha256(_DASHBOARD_HTML.encode("utf-8")).hexdigest()
DASHBOARD_URI = f"ui://note-dashboard/{_DASHBOARD_HASH}.html"


class AppsExtension(Extension):
    """Advertise support for the standard MCP Apps resource profile."""

    identifier = APP_EXTENSION_ID

    def settings(self) -> dict[str, Any]:
        return {"mimeTypes": [APP_MIME_TYPE]}


def register_apps(mcp: MCPServer, store: NoteStore) -> None:
    """Register the app resource and its structured-data fallback tool."""

    @mcp.resource(
        DASHBOARD_URI,
        name="note-dashboard",
        description="Self-contained read-only note dashboard app.",
        mime_type=APP_MIME_TYPE,
        meta={
            "ui": {
                "csp": {
                    "connectDomains": [],
                    "resourceDomains": [],
                    "frameDomains": [],
                    "baseUriDomains": [],
                }
            }
        },
    )
    def note_dashboard_app() -> str:
        return _DASHBOARD_HTML

    @mcp.tool(
        meta={"ui": {"resourceUri": DASHBOARD_URI}},
        structured_output=True,
    )
    def note_dashboard() -> CallToolResult:
        """Show a read-only dashboard of all notes."""
        notes = [note.model_dump(mode="json") for note in store.list_notes()]
        result: dict[str, object] = {"notes": notes, "total_notes": len(notes)}
        # Keep a conventional content block so clients without Apps support get
        # a useful, readable result as well as structuredContent.
        return CallToolResult(
            content=[TextContent(type="text", text=f"Dashboard snapshot: {len(notes)} notes.")],
            structured_content=result,
        )
