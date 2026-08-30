# hermes-plugin-muninndb

A [Hermes Agent](https://github.com/NousResearch/hermes-agent) memory-provider plugin for a self-hosted [muninnDB](https://muninndb.com) instance.

The plugin uses only Python's standard library. It keeps secrets out of repository files: locked-vault credentials are read exclusively from the `MUNINN_API_KEY` environment variable.

## Features

- Store, recall, read, soft-delete, link, and update engrams
- Automatic non-blocking turn synchronization
- Relevant-memory prefetch before a turn and background prefetch for the next turn
- Pre-compression checkpoints and built-in-memory mirroring
- Configurable recall threshold
- Circuit breaker and one retry for transient connection failures
- Optional `HERMES_TENANT` tagging and concept prefixes
- Public and locked muninnDB vaults

## Requirements

- Hermes Agent with memory-provider plugin support
- A running muninnDB REST API, normally at `localhost:8475`
- An existing muninnDB vault

## Install

Hermes discovers user memory providers in `$HERMES_HOME/plugins/<name>/`.

```bash
git clone https://github.com/Jehu/hermes-plugin-muninndb.git /tmp/hermes-plugin-muninndb
mkdir -p "${HERMES_HOME:-$HOME/.hermes}/plugins/muninndb"
cp /tmp/hermes-plugin-muninndb/{__init__.py,plugin.yaml} \
  "${HERMES_HOME:-$HOME/.hermes}/plugins/muninndb/"
```

Then activate the provider:

```bash
hermes plugins
```

Select **Provider Plugins → Memory Provider → muninnDB**, or set this in your Hermes configuration:

```yaml
memory:
  provider: muninndb
```

Restart Hermes completely after installing or updating the plugin. `/reset` does not reload plugin code.

## Configure

Create `$HERMES_HOME/muninndb.json`:

```json
{
  "host": "localhost:8475",
  "vault": "hermes",
  "threshold": 0.5
}
```

`host` may include `http://` or `https://`. `threshold` is clamped to `0.0`–`1.0`.

For a locked vault, put the API key in `$HERMES_HOME/.env` or export it in the Hermes process environment:

```bash
MUNINN_API_KEY=replace-with-your-key
```

Never add `.env`, `muninndb.json`, real vault names, or memory exports to this repository.

## Tools

| Tool | Purpose |
|---|---|
| `muninn_remember` | Store an engram with optional tags, memory type, and confidence |
| `muninn_recall` | Perform semantic/associative recall |
| `muninn_read` | Retrieve an engram by ULID |
| `muninn_forget` | Soft-delete an engram |
| `muninn_link` | Add a weighted relationship between two engrams |
| `muninn_update` | Update content, confidence, or tags on supported muninnDB versions |

The `memory_type` tool argument is translated to muninnDB's integer enum and sent as the REST field `type`.

## Hooks

- `sync_turn`
- `prefetch`
- `queue_prefetch`
- `on_session_end`
- `on_memory_write`
- `on_pre_compress`

## Test

The test suite has no third-party dependencies:

```bash
python3 -m unittest discover -s tests -v
```

## Security

Before each release, scan the complete repository and Git history:

```bash
trufflehog git file://"$PWD" --only-verified --fail
```

Only source, public documentation, tests, metadata, and the license belong in Git. Runtime configuration and compiled Python files are ignored.

## Compatibility

This is a third-party community plugin, not an official Nous Research or muninnDB project. The REST endpoints for linking and updating depend on the installed muninnDB version.

## License

[MIT](LICENSE)
