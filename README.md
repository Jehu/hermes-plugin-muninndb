# muninnDB Memory Provider Plugin

Integrates [muninnDB](https://muninndb.com) — a local cognitive database — with Hermes Agent via its REST API.

## What It Does

- **remember** — Persist facts/insights as engrams in your local muninnDB.
- **recall** — Semantic search through stored memories (no LLM cost).
- **read** — Retrieve a single memory by its ULID.
- **forget** — Soft-delete a memory.
- **Auto-sync** — Every user/assistant turn is automatically stored.
- **Prefetch** — Relevant memories are injected into context before each turn.

## Prerequisites

1. [Install muninnDB](https://muninndb.com/docs/getting-started/installation) locally.
2. Start the server: `muninn start`
3. Create a vault (two modes):
   - **Public** (no API key): `muninn vault create hermes --public`
   - **Locked** (requires API key): `muninn vault create hermes`

   For locked vaults, create an API key:
   ```bash
   muninn api-key create --vault hermes --label "hermes-agent" --mode full
   ```
   Copy the token — it will NOT be shown again.

## Setup

### Quick Setup (recommended)

```bash
python3 ~/.hermes/scripts/setup_muninndb.py
```

This interactive script detects your running server, creates/configures the vault,
and writes all config files. It supports both public (no-key) and locked vaults.

### Manual Setup

1. **Activate the plugin**

   ```bash
   hermes plugins
   # Navigate to: Provider Plugins → Memory Provider → muninnDB
   ```

   Or edit your `~/.hermes/config.yaml`:

   ```yaml
   memory:
     provider: muninndb
   ```

2. **Configure**

   Create `~/.hermes/muninndb.json`:
   ```json
   {
     "host": "localhost:8475",
     "vault": "hermes"
   }
   ```

   For locked vaults, also set the API key in `~/.hermes/.env`:
   ```bash
   MUNINN_API_KEY=mk_xxxxxxxxxxxxxxxx
   ```

### 3. Verify

Start Hermes and check that the provider is loaded:

```bash
hermes
# Look for: "Memory provider: muninnDB" in the startup banner
```

## Tools

The plugin exposes four tools to the agent:

| Tool | Purpose |
|------|---------|
| `muninn_remember` | Store a new memory with concept, content, and optional tags |
| `muninn_recall` | Search memories by semantic relevance |
| `muninn_read` | Retrieve a single memory by ULID |
| `muninn_forget` | Soft-delete a memory by ULID |

## Architecture

```
Hermes Agent
    └── MemoryManager
            └── muninnDB Provider (this plugin)
                        └── HTTP/JSON ──→ muninnDB REST API (:8475)
```

- Uses only Python stdlib (`urllib`) — no external dependencies.
- `sync_turn()` is non-blocking (daemon thread, 5s timeout).
- `prefetch()` has a strict 2s timeout — never blocks the agent.
- Profile isolation: each Hermes profile can use its own vault.

## Troubleshooting

| Issue | Fix |
|-------|-----|
| "muninnDB not configured" | Run `python3 ~/.hermes/scripts/setup_muninndb.py` or create `~/.hermes/muninndb.json` |
| "Connection refused" | Ensure `muninn start` is running |
| "VAULT_LOCKED" / "invalid api key" | Vault requires a key. Either create one (`muninn api-key create --vault <vault> --mode full`) or recreate the vault as public (`muninn vault create <vault> --public`) |
| High latency on recall | Check if Ollama embedding is running (if configured) |
| Memory not persisting | Verify vault exists: `muninn show vaults` |

## License

Same as Hermes Agent.
