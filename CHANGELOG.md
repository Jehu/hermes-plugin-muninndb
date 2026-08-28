# muninnDB Memory Provider Plugin v1.1.0 — Changelog

## Neue Features

### 1. Circuit Breaker (wie mem0)
- Nach **5 aufeinanderfolgenden Fehlern**: 120s Pause
- Alle API-Calls sind geschützt: `prefetch`, `sync_turn`, `handle_tool_call`, `on_session_end`, `on_memory_write`
- Bei offenem Circuit: graceful degradation, Agent läuft weiter

### 2. Retry mit Exponential Backoff
- `_json_request` retryt 1x bei Timeout/Connection-Errors
- 0.5s, dann 1.0s Wartezeit
- HTTP-Errors (4xx/5xx) werden **nicht** retryt — fail fast

### 3. `queue_prefetch()` — Background Prefetch für nächsten Turn
- Wird nach jeder Agent-Antwort aufgerufen
- Lädt relevante Memories im Hintergrund (non-blocking)
- Ergebnis wird gecacht für den nächsten `prefetch()`-Aufruf
- Zero-Latency für den Nutzer

### 4. `on_pre_compress()` — Insights vor Context-Compression
- Wird aufgerufen, bevor der Context Compressor läuft
- Speichert das letzte User+Assistant-Paar als "compress-insight" Engram
- Verhindert, dass wichtige Informationen beim Compress verloren gehen

### 5. Konfigurierbarer Threshold
- Neuer Config-Parameter: `threshold` (0.0–1.0)
- Steuert die Striktheit der semantischen Suche
- Default: 0.5 (wie bisher)
- Konfigurierbar via `~/.hermes/muninndb.json` oder `hermes memory setup`

## Vault-Konfigurierbarkeit

Ja, der Vault ist **vollständig konfigurierbar**:

| Parameter | Ort | Beschreibung |
|-----------|-----|--------------|
| `vault` | `~/.hermes/muninndb.json` | Vault-Name (Default: `hermes`) |
| `host` | `~/.hermes/muninndb.json` | Server-Adresse (Default: `localhost:8475`) |
| `threshold` | `~/.hermes/muninndb.json` | Recall-Threshold (Default: `0.5`) |
| `api_key` | `~/.hermes/.env` (`MUNINN_API_KEY`) | Für locked Vaults |

### Deine aktuelle Konfiguration:

```json
// ~/.hermes/muninndb.json
{
  "host": "localhost:8475",
  "vault": "hermes"
}
```

**Wichtig:** Du hast **keinen API-Key** in `.env` konfiguriert. Das bedeutet, dein `hermes`-Vault muss **public** sein, damit das Plugin funktioniert.

### Verfügbare Vaults auf deinem System:

```
default
  minime
  dev_huginn
  nanoclawd-dev
  dev_citigrund
  project_keyword-cluster-clone
  hermes          ← aktuell verwendet
  huginn
  dev_sanft-schoen
  meta-schadensersatz_dev
```

Du hast **10 Vaults** — das ist eine saubere Trennung pro Projekt/Kunde.

### Empfohlene Konfiguration für Multi-Client-Setup:

Wenn du für verschiedene Kunden/Projekte unterschiedliche Memory-Isolation willst:

```json
// ~/.hermes/muninndb.json (Default)
{
  "host": "localhost:8475",
  "vault": "hermes",
  "threshold": 0.5
}
```

Für projektspezifische Isolation könntest du in Zukunft pro Projekt-Profil einen eigenen Vault nutzen (z.B. `vault: "dev_sanft-schoen"`).

## Aktualisierte Hooks (plugin.yaml)

```yaml
name: muninndb
version: 1.1.0
description: "Local cognitive memory via muninnDB REST API"
hooks:
  - sync_turn
  - prefetch
  - queue_prefetch        ← NEU
  - on_session_end
  - on_memory_write
  - on_pre_compress       ← NEU
```

## Vergleich mit mem0 Integration

| Feature | mem0 | muninnDB (v1.1.0) |
|---------|------|-------------------|
| Semantic Search | ✅ + Reranking | ✅ (ACTIVATE) |
| Auto-Sync Turns | ✅ Background | ✅ Background |
| Prefetch vor Antwort | ✅ Gecacht | ✅ + Cache |
| **queue_prefetch** | ✅ | ✅ **NEU** |
| **on_pre_compress** | ❌ | ✅ **NEU** |
| Server-side Extraction | ✅ mem0 LLM | ❌ (lokale DB) |
| Circuit Breaker | ✅ | ✅ **NEU** |
| Retry | ✅ | ✅ **NEU** |
| Memory Mirror | ❌ | ✅ |
| **Konfigurierbarer Threshold** | ❌ | ✅ **NEU** |
| **Multi-Vault Support** | ❌ | ✅ |
| Soft-Delete | ❌ | ✅ |
| Direktes Speichern | ✅ | ✅ |
| Kosten | API-Kosten | **Kostenlos** (lokal) |

## Nächste Schritte

1. **Plugin neu laden:** Hermes neu starten
2. **API-Key prüfen:** Wenn der `hermes`-Vault locked ist, füge `MUNINN_API_KEY` zu `~/.hermes/.env` hinzu
3. **Threshold anpassen:** Falls zu viele/zu wenige Ergebnisse, `threshold` in `muninndb.json` ändern

## Dateien geändert

- `/Users/marco/.hermes/plugins/muninndb/__init__.py`
- `/Users/marco/.hermes/plugins/muninndb/plugin.yaml`
