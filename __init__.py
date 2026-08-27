"""muninnDB memory provider plugin for Hermes Agent.

Integrates with a locally running muninnDB cognitive database via its REST API.
No external dependencies — uses urllib from the standard library.

Config:
  - host (default: localhost:8475)
  - vault (default: hermes)
  - api_key (secret, env var: MUNINN_API_KEY)

Non-secret config is saved to $HERMES_HOME/muninndb.json.
Secrets go to $HERMES_HOME/.env.
"""

from __future__ import annotations

import json
import logging
import os
import threading
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any, Dict, List, Optional

from agent.memory_provider import MemoryProvider
from tools.registry import tool_error

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Tool schemas (OpenAI function-calling format)
# ---------------------------------------------------------------------------

_REMEMBER_SCHEMA = {
    "name": "muninn_remember",
    "description": (
        "Store a new memory (engram) in muninnDB. "
        "Use this to persist important facts, insights, or observations for future recall. "
        "Provide a concise concept (label) and the full content. "
        "Optional: add tags for easier filtering, set memory_type for categorization, "
        "and confidence for reliability scoring."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "concept": {
                "type": "string",
                "description": "Short label / title for the memory (e.g. 'client-preference', 'project-astro').",
            },
            "content": {
                "type": "string",
                "description": "Full textual content to store.",
            },
            "tags": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Optional tags for categorisation.",
            },
            "memory_type": {
                "type": "string",
                "enum": ["Fact", "Decision", "Observation", "Preference", "Issue", "Task"],
                "description": "Semantic category of the memory. Default: Fact.",
            },
            "confidence": {
                "type": "number",
                "minimum": 0,
                "maximum": 1,
                "description": "Reliability score (0.0–1.0). Default: 0.8.",
            },

        },
        "required": ["concept", "content"],
    },
}

_RECALL_SCHEMA = {
    "name": "muninn_recall",
    "description": (
        "Search memories in muninnDB using semantic / associative recall (ACTIVATE). "
        "Returns the most cognitively relevant engrams for the given query. "
        "Cheaper than LLM synthesis — use when you want to find past facts."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "What to search for in the memory store.",
            },
            "limit": {
                "type": "integer",
                "description": "Maximum results to return (default 5, max 20).",
            },
        },
        "required": ["query"],
    },
}

_READ_SCHEMA = {
    "name": "muninn_read",
    "description": "Retrieve a single memory by its muninnDB ULID.",
    "parameters": {
        "type": "object",
        "properties": {
            "id": {
                "type": "string",
                "description": "The ULID of the engram to read.",
            },
        },
        "required": ["id"],
    },
}

_FORGET_SCHEMA = {
    "name": "muninn_forget",
    "description": (
        "Soft-delete (forget) a memory from muninnDB by its ULID. "
        "The engram is retained but marked deleted — it will not appear in recall."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "id": {
                "type": "string",
                "description": "The ULID of the engram to forget.",
            },
        },
        "required": ["id"],
    },
}

_LINK_SCHEMA = {
    "name": "muninn_link",
    "description": (
        "Create an explicit weighted association between two engrams in muninnDB. "
        "Links are bidirectional and traversed during recall to surface related memories. "
        "Use this to connect related facts, tasks, or decisions."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "source_id": {
                "type": "string",
                "description": "ULID of the source engram.",
            },
            "target_id": {
                "type": "string",
                "description": "ULID of the target engram.",
            },
            "rel_type": {
                "type": "integer",
                "description": (
                    "Relationship type: 1=supports, 2=contradicts, 3=depends_on, "
                    "4=supersedes, 5=relates_to, 6=is_part_of, 7=causes, "
                    "8=preceded_by, 9=followed_by, 10=created_by_person, "
                    "11=belongs_to_project, 12=references, 13=implements, "
                    "14=blocks, 15=resolves"
                ),
            },
            "weight": {
                "type": "number",
                "minimum": 0,
                "maximum": 1,
                "description": "Association strength (0.0–1.0). Default: 0.8.",
            },
        },
        "required": ["source_id", "target_id", "rel_type"],
    },
}

_UPDATE_SCHEMA = {
    "name": "muninn_update",
    "description": (
        "Update an existing engram in muninnDB. "
        "Change content, state, confidence, or tags. "
        "Use this for lifecycle management (e.g., Task: PLANNING → COMPLETED) "
        "or confidence updates after verification."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "id": {
                "type": "string",
                "description": "ULID of the engram to update.",
            },
            "content": {
                "type": "string",
                "description": "New content (optional).",
            },

            "confidence": {
                "type": "number",
                "minimum": 0,
                "maximum": 1,
                "description": "New confidence score (optional).",
            },
            "tags": {
                "type": "array",
                "items": {"type": "string"},
                "description": "New tags — replaces existing tags (optional).",
            },
        },
        "required": ["id"],
    },
}

_SCHEMAS = [_REMEMBER_SCHEMA, _RECALL_SCHEMA, _READ_SCHEMA, _FORGET_SCHEMA, _LINK_SCHEMA, _UPDATE_SCHEMA]


# ---------------------------------------------------------------------------
# REST client helpers
# ---------------------------------------------------------------------------

def _json_request(
    base_url: str,
    api_key: str,
    method: str,
    endpoint: str,
    payload: Optional[Dict[str, Any]] = None,
    timeout: float = 3.0,
    max_retries: int = 1,
) -> Dict[str, Any]:
    """Make a JSON HTTP request and return the parsed response.

    Retries once on timeout/connection errors with exponential backoff.
    """
    url = f"{base_url}{endpoint}" if endpoint.startswith("/") else f"{base_url}/{endpoint}"
    data = json.dumps(payload).encode("utf-8") if payload else None
    last_exc: Optional[Exception] = None

    for attempt in range(max_retries + 1):
        req = urllib.request.Request(url, data=data, method=method)
        req.add_header("Content-Type", "application/json")
        if api_key:
            req.add_header("Authorization", f"Bearer {api_key}")
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                body = resp.read().decode("utf-8")
                return json.loads(body) if body else {}
        except urllib.error.HTTPError as exc:
            # HTTP errors (4xx/5xx) are not retried — fail fast
            body = exc.read().decode("utf-8") if exc.fp else ""
            try:
                parsed = json.loads(body)
                detail = parsed.get("message", body)
                if parsed.get("code") == "VAULT_LOCKED":
                    detail += "  Set MUNINN_API_KEY or run: muninn vault create <vault> --public"
            except Exception:
                detail = body or str(exc)
            raise RuntimeError(f"muninnDB API error ({exc.code}): {detail}") from exc
        except Exception as exc:
            last_exc = exc
            if attempt < max_retries:
                import time
                time.sleep(0.5 * (2 ** attempt))  # 0.5s, then 1.0s
                continue
            raise RuntimeError(f"muninnDB request failed after {max_retries + 1} attempts: {exc}") from last_exc
    return {}


# ---------------------------------------------------------------------------
# Provider class
# ---------------------------------------------------------------------------

class MuninnDBProvider(MemoryProvider):
    """MemoryProvider implementation for muninnDB."""

    # Circuit-breaker constants
    _CB_FAILURE_THRESHOLD = 5
    _CB_COOLDOWN_SECONDS = 120

    @property
    def name(self) -> str:
        return "muninndb"

    # -- Config --------------------------------------------------------------

    def get_config_schema(self) -> List[Dict[str, Any]]:
        return [
            {
                "key": "host",
                "description": "muninnDB REST API host:port",
                "default": "localhost:8475",
            },
            {
                "key": "vault",
                "description": "Vault name for memories (per-profile isolation)",
                "default": "hermes",
            },
            {
                "key": "threshold",
                "description": "Semantic recall threshold (0.0–1.0). Lower = more results, higher = stricter matching.",
                "default": 0.5,
            },
            {
                "key": "api_key",
                "description": "muninnDB API key (only needed for locked vaults; create with: muninn api-key create --vault <vault> --mode full)",
                "secret": True,
                "required": False,
                "env_var": "MUNINN_API_KEY",
            },
        ]

    def save_config(self, values: Dict[str, Any], hermes_home: str) -> None:
        """Persist non-secret config to muninndb.json."""
        config_path = Path(hermes_home) / "muninndb.json"
        config_path.write_text(json.dumps(values, indent=2), encoding="utf-8")

    # -- Availability check --------------------------------------------------

    def is_available(self) -> bool:
        """Check whether muninnDB appears configured.  No network calls."""
        if self._get_api_key_from_env():
            return True
        hermes_home = os.environ.get("HERMES_HOME", str(Path.home() / ".hermes"))
        return (Path(hermes_home) / "muninndb.json").exists()

    # -- Lifecycle -----------------------------------------------------------

    def initialize(self, session_id: str, **kwargs) -> None:
        self._session_id = session_id
        self._hermes_home = kwargs.get("hermes_home", "")
        self._platform = kwargs.get("platform", "cli")
        self._agent_context = kwargs.get("agent_context", "primary")

        # Circuit-breaker state
        self._cb_failures = 0
        self._cb_open_until = 0.0

        # Tenant isolation (set by Kanban dispatcher for multi-tenant boards)
        self._tenant = os.environ.get("HERMES_TENANT", "")

        # Load non-secret config
        config: Dict[str, str] = {}
        if self._hermes_home:
            config_path = Path(self._hermes_home) / "muninndb.json"
            if config_path.exists():
                try:
                    config = json.loads(config_path.read_text(encoding="utf-8"))
                except Exception as e:
                    logger.warning("Failed to load muninndb.json: %s", e)

        self._host = config.get("host", "localhost:8475")
        self._vault = config.get("vault", "hermes")
        self._threshold = float(config.get("threshold", 0.5))
        self._base_url = f"http://{self._host}"
        self._api_key = self._get_api_key_from_env() or ""

        # Ensure http:// prefix for base_url if user omitted it
        if not self._base_url.startswith("http"):
            self._base_url = f"http://{self._base_url}"

        self._sync_thread: Optional[threading.Thread] = None

    def system_prompt_block(self) -> str:
        lines = [
            f"Memory provider: muninnDB (vault={self._vault}, host={self._host}).",
        ]
        if self._tenant:
            lines.append(f"Tenant: {self._tenant}. All memory writes are scoped to this tenant.")
        lines.extend([
            "You have six tools: muninn_remember, muninn_recall, muninn_read, muninn_forget, muninn_link, muninn_update.",
            "Use muninn_remember to persist facts. Set memory_type (Fact/Decision/Observation/Preference/Issue/Task), ",
                "confidence (0.0-1.0), and memory_type (Fact/Decision/Observation/Preference/Issue/Task) for better organization.",
            "Use muninn_link to connect related memories (e.g., a Task that depends_on a Decision).",
            "Use muninn_update to change a memory's confidence, content, or tags.",
            "Use muninn_recall for semantic search. Every turn is automatically synced to muninnDB.",
        ])
        return "\n".join(lines)

    # -- Prefetch / recall ---------------------------------------------------

    def _format_activations(self, activations: List[Dict[str, Any]]) -> str:
        """Format a list of activation dicts into the system-prompt block."""
        if not activations:
            return ""
        lines = ["Relevant memories from muninnDB:"]
        for a in activations:
            concept = a.get("concept", "")
            content = a.get("content", "")[:200]
            score = a.get("score", 0)
            engram_id = a.get("id", "")
            try:
                score_fmt = f"{float(score):.2f}"
            except (TypeError, ValueError):
                score_fmt = str(score)
            lines.append(f"- [{engram_id}] {concept} (score: {score_fmt}): {content}")
        return "\n".join(lines)

    def prefetch(self, query: str, *, session_id: str = "") -> str:
        """Background recall before each turn. Fast — strict 2s timeout.

        If a queue_prefetch() result is cached from the previous turn,
        return it immediately without a network call.
        """
        if self._agent_context != "primary":
            return ""

        # Check for queued prefetch cache first
        cached = getattr(self, "_prefetch_cache", None)
        if cached:
            self._prefetch_cache = None
            return cached

        def _do_prefetch():
            return _json_request(
                self._base_url,
                self._api_key,
                "POST",
                "/api/activate",
                payload={
                    "vault": self._vault,
                    "context": [query],
                    "max_results": 3,
                    "threshold": self._threshold,
                },
                timeout=2.0,
            )

        ok, result = self._cb_wrap(_do_prefetch)
        if not ok:
            logger.debug("muninnDB prefetch skipped: %s", result)
            return ""

        return self._format_activations(result.get("activations", []))

    def queue_prefetch(self, query: str, *, session_id: str = "") -> None:
        """Background prefetch for the NEXT turn.

        Called after the agent has responded.  Fires a non-blocking
        recall so that memories are already cached when the user types
        their next message.
        """
        if self._agent_context != "primary":
            return

        def _do_prefetch():
            return _json_request(
                self._base_url,
                self._api_key,
                "POST",
                "/api/activate",
                payload={
                    "vault": self._vault,
                    "context": [query],
                    "max_results": 5,
                    "threshold": self._threshold,
                },
                timeout=3.0,
            )

        def _bg():
            ok, result = self._cb_wrap(_do_prefetch)
            if not ok:
                logger.debug("muninnDB queue_prefetch skipped: %s", result)
                return
            # Store in a simple instance cache for the next prefetch() call
            self._prefetch_cache = self._format_activations(result.get("activations", []))

        t = threading.Thread(target=_bg, daemon=True)
        t.start()

    # -- Turn sync -----------------------------------------------------------

    def sync_turn(self, user_content: str, assistant_content: str, *, session_id: str = "") -> None:
        """Persist a completed turn to muninnDB. Non-blocking."""
        if self._agent_context != "primary":
            return

        def _do_sync():
            concept = f"turn:{self._session_id[:8]}" if self._session_id else "turn"
            content = f"USER: {user_content}\nASSISTANT: {assistant_content}"
            # Truncate if excessively long to avoid payload issues
            if len(content) > 50000:
                content = content[:50000] + "\n...[truncated]"
            _json_request(
                self._base_url,
                self._api_key,
                "POST",
                "/api/engrams",
                payload={
                    "vault": self._vault,
                    "concept": self._tenant_prefix(concept),
                    "content": content,
                    "tags": self._tenant_tags(["auto-sync", self._platform]),
                },
                timeout=5.0,
            )

        def _sync():
            ok, err = self._cb_wrap(_do_sync)
            if not ok:
                logger.warning("muninnDB sync_turn skipped: %s", err)

        if self._sync_thread and self._sync_thread.is_alive():
            self._sync_thread.join(timeout=5.0)
        self._sync_thread = threading.Thread(target=_sync, daemon=True)
        self._sync_thread.start()

    # -- Tools ---------------------------------------------------------------

    def get_tool_schemas(self) -> List[Dict[str, Any]]:
        return list(_SCHEMAS)

    def handle_tool_call(self, tool_name: str, args: Dict[str, Any], **kwargs) -> str:
        def _do_remember():
            # Map string memory_type to muninnDB integer enum
            memory_type_str = args.get("memory_type", "Fact")
            memory_type_int = {"Fact": 0, "Decision": 1, "Observation": 2, "Preference": 3, "Issue": 4, "Task": 5}.get(memory_type_str, 0)
            payload = {
                "vault": self._vault,
                "concept": self._tenant_prefix(args["concept"]),
                "content": args["content"],
                "tags": self._tenant_tags(args.get("tags", [])),
                "memory_type": memory_type_int,
                "confidence": float(args.get("confidence", 0.8)),
            }
            return _json_request(
                self._base_url,
                self._api_key,
                "POST",
                "/api/engrams",
                payload=payload,
                timeout=5.0,
            )

        def _do_recall():
            raw_limit = args.get("limit", 5)
            try:
                limit = max(1, min(int(raw_limit), 20))
            except (TypeError, ValueError):
                limit = 5
            return _json_request(
                self._base_url,
                self._api_key,
                "POST",
                "/api/activate",
                payload={
                    "vault": self._vault,
                    "context": [args["query"]],
                    "max_results": limit,
                    "threshold": 0.5,
                },
                timeout=3.0,
            )

        def _do_read():
            engram_id = args["id"]
            return _json_request(
                self._base_url,
                self._api_key,
                "GET",
                f"/api/engrams/{urllib.parse.quote(engram_id)}?vault={urllib.parse.quote(self._vault)}",
                timeout=3.0,
            )

        def _do_forget():
            engram_id = args["id"]
            _json_request(
                self._base_url,
                self._api_key,
                "DELETE",
                f"/api/engrams/{urllib.parse.quote(engram_id)}?vault={urllib.parse.quote(self._vault)}",
                timeout=3.0,
            )
            return {"forgotten": True, "id": engram_id}

        try:
            if tool_name == "muninn_remember":
                ok, result = self._cb_wrap(_do_remember)
                if not ok:
                    return tool_error(f"muninnDB error: {result}")
                return json.dumps({"stored": True, "id": result.get("id"), "vault": self._vault})

            elif tool_name == "muninn_recall":
                ok, result = self._cb_wrap(_do_recall)
                if not ok:
                    return tool_error(f"muninnDB error: {result}")
                activations = result.get("activations", [])
                simplified = []
                for a in activations:
                    simplified.append({
                        "id": a.get("id"),
                        "concept": a.get("concept"),
                        "content": a.get("content", "")[:500],
                        "score": a.get("score"),
                        "summary": a.get("summary", ""),
                    })
                return json.dumps({
                    "query": args["query"],
                    "total_found": result.get("total_found", 0),
                    "results": simplified,
                })

            elif tool_name == "muninn_read":
                ok, result = self._cb_wrap(_do_read)
                if not ok:
                    return tool_error(f"muninnDB error: {result}")
                # Reverse-map memory_type integer back to string for readability
                _REVERSE_MEMORY_TYPE = {0: "Fact", 1: "Decision", 2: "Observation", 3: "Preference", 4: "Issue", 5: "Task"}
                memory_type_int = result.get("memory_type")
                return json.dumps({
                    "id": result.get("id"),
                    "concept": result.get("concept"),
                    "content": result.get("content"),
                    "confidence": result.get("confidence"),
                    "memory_type": _REVERSE_MEMORY_TYPE.get(memory_type_int, memory_type_int) if memory_type_int is not None else None,
                    "summary": result.get("summary", ""),
                    "key_points": result.get("key_points", []),
                })

            elif tool_name == "muninn_forget":
                ok, result = self._cb_wrap(_do_forget)
                if not ok:
                    return tool_error(f"muninnDB error: {result}")
                return json.dumps(result)

            elif tool_name == "muninn_link":
                def _do_link():
                    return _json_request(
                        self._base_url,
                        self._api_key,
                        "POST",
                        "/api/link",
                        payload={
                            "vault": self._vault,
                            "source_id": args["source_id"],
                            "target_id": args["target_id"],
                            "rel_type": int(args["rel_type"]),
                            "weight": float(args.get("weight", 0.8)),
                        },
                        timeout=3.0,
                    )
                ok, result = self._cb_wrap(_do_link)
                if not ok:
                    return tool_error(f"muninnDB error: {result}")
                return json.dumps({"linked": True, "source_id": args["source_id"], "target_id": args["target_id"]})

            elif tool_name == "muninn_update":
                def _do_update():
                    payload = {"vault": self._vault}
                    if "content" in args:
                        payload["content"] = args["content"]

                    if "confidence" in args:
                        payload["confidence"] = float(args["confidence"])
                    if "tags" in args:
                        payload["tags"] = args["tags"]
                    engram_id = args["id"]
                    return _json_request(
                        self._base_url,
                        self._api_key,
                        "PATCH",
                        f"/api/engrams/{urllib.parse.quote(engram_id)}",
                        payload=payload,
                        timeout=3.0,
                    )
                ok, result = self._cb_wrap(_do_update)
                if not ok:
                    return tool_error(f"muninnDB error: {result}")
                return json.dumps({"updated": True, "id": args["id"]})

            else:
                return tool_error(f"Unknown muninnDB tool: {tool_name}")
        except Exception as e:
            logger.warning("muninnDB tool %s failed: %s", tool_name, e)
            return tool_error(f"muninnDB error: {e}")

    # -- Session end ---------------------------------------------------------

    def on_session_end(self, messages: List[Dict[str, Any]]) -> None:
        """Store a session summary engram."""
        if self._agent_context != "primary":
            return

        def _do_sync():
            turn_count = len([m for m in messages if m.get("role") == "user"])
            content = f"Session ended. Turns: {turn_count}. Last session ID: {self._session_id}"
            _json_request(
                self._base_url,
                self._api_key,
                "POST",
                "/api/engrams",
                payload={
                    "vault": self._vault,
                    "concept": self._tenant_prefix(f"session-end:{self._session_id[:8]}"),
                    "content": content,
                    "tags": self._tenant_tags(["session-summary", self._platform]),
                },
                timeout=5.0,
            )

        def _sync():
            ok, err = self._cb_wrap(_do_sync)
            if not ok:
                logger.warning("muninnDB on_session_end skipped: %s", err)

        t = threading.Thread(target=_sync, daemon=True)
        t.start()

    # -- Memory write mirror --------------------------------------------------

    def on_memory_write(
        self,
        action: str,
        target: str,
        content: str,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Mirror built-in Hermes memory writes to muninnDB.

        On 'add' or 'replace', stores the fact as an engram so it is
        discoverable via recall/prefetch in future sessions. On 'remove',
        does nothing (we lack the ULID to soft-delete).

        This is a synchronous background write — fast, no blocking.
        """
        if self._agent_context != "primary":
            return
        if action not in ("add", "replace"):
            return

        def _do_mirror():
            # Extract optional provenance from metadata
            session_tag = ""
            if metadata:
                session_tag = metadata.get("session_id", "")[:8]
                if not session_tag:
                    session_tag = metadata.get("execution_context", "")[:8]

            concept = self._tenant_prefix(f"memory-mirror:{target}")
            tags = self._tenant_tags(["memory-mirror", target, self._platform])
            if action == "replace":
                tags.append("replacement")
            tag_list = [t for t in tags if t]

            _json_request(
                self._base_url,
                self._api_key,
                "POST",
                "/api/engrams",
                payload={
                    "vault": self._vault,
                    "concept": concept,
                    "content": content,
                    "tags": tag_list,
                },
                timeout=5.0,
            )

        def _mirror():
            ok, err = self._cb_wrap(_do_mirror)
            if not ok:
                logger.debug("muninnDB on_memory_write (%s/%s) skipped: %s", action, target, err)

        t = threading.Thread(target=_mirror, daemon=True)
        t.start()

    def on_pre_compress(self, messages: List[Dict[str, Any]]) -> None:
        """Store key insights before context compression discards them.

        Called right before the context compressor runs.  We extract
        the last user + assistant pair and persist it as a 'compress-insight'
        engram so nothing important is lost.
        """
        if self._agent_context != "primary":
            return
        if not messages:
            return

        # Grab the last turn (user + assistant) if present
        last_turn = messages[-2:] if len(messages) >= 2 else messages[-1:]
        content_parts = []
        for m in last_turn:
            role = m.get("role", "unknown")
            text = m.get("content", "") or ""
            # Truncate very long messages
            if len(text) > 2000:
                text = text[:2000] + "\n...[truncated]"
            content_parts.append(f"{role.upper()}: {text}")

        if not content_parts:
            return

        content = "\n".join(content_parts)

        def _do_compress():
            _json_request(
                self._base_url,
                self._api_key,
                "POST",
                "/api/engrams",
                payload={
                    "vault": self._vault,
                    "concept": self._tenant_prefix(f"compress-insight:{self._session_id[:8]}"),
                    "content": content,
                    "tags": self._tenant_tags(["compress-insight", self._platform]),
                },
                timeout=5.0,
            )

        def _bg():
            ok, err = self._cb_wrap(_do_compress)
            if not ok:
                logger.debug("muninnDB on_pre_compress skipped: %s", err)

        t = threading.Thread(target=_bg, daemon=True)
        t.start()

    # -- Shutdown ------------------------------------------------------------

    def shutdown(self) -> None:
        if self._sync_thread and self._sync_thread.is_alive():
            self._sync_thread.join(timeout=5.0)

    # -- Circuit breaker -------------------------------------------------------

    def _cb_check(self) -> bool:
        """Return True if the circuit is closed (requests allowed)."""
        import time
        if time.time() < self._cb_open_until:
            return False
        return True

    def _cb_record_success(self) -> None:
        """Reset failure counter on success."""
        self._cb_failures = 0

    def _cb_record_failure(self) -> None:
        """Increment failure counter; open circuit if threshold reached."""
        import time
        self._cb_failures += 1
        if self._cb_failures >= self._CB_FAILURE_THRESHOLD:
            self._cb_open_until = time.time() + self._CB_COOLDOWN_SECONDS
            logger.warning(
                "muninnDB circuit breaker OPEN for %ds after %d consecutive failures",
                self._CB_COOLDOWN_SECONDS,
                self._cb_failures,
            )

    def _cb_wrap(self, fn, *args, **kwargs):
        """Execute fn with circuit-breaker protection. Returns (ok, result_or_error)."""
        if not self._cb_check():
            return False, "Circuit breaker open — muninnDB temporarily disabled"
        try:
            result = fn(*args, **kwargs)
            self._cb_record_success()
            return True, result
        except Exception as e:
            self._cb_record_failure()
            return False, str(e)

    # -- Helpers -------------------------------------------------------------

    def _tenant_tag(self) -> str:
        return f"tenant:{self._tenant}" if self._tenant else ""

    def _tenant_tags(self, base_tags: list) -> list:
        """Append tenant tag to a base tag list if tenant is active."""
        if self._tenant:
            return base_tags + [self._tenant_tag()]
        return base_tags

    def _tenant_prefix(self, concept: str) -> str:
        """Prefix concept with tenant for tenant-scoped isolation."""
        if self._tenant:
            return f"{self._tenant}:{concept}"
        return concept

    def _get_api_key_from_env(self) -> str:
        return os.environ.get("MUNINN_API_KEY", "")


# ---------------------------------------------------------------------------
# Plugin entry point
# ---------------------------------------------------------------------------

def register(ctx) -> None:
    """Called by the memory plugin discovery system."""
    ctx.register_memory_provider(MuninnDBProvider())
