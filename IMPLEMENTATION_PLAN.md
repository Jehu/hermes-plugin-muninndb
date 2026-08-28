# Implementierungsplan: muninnDB-Fähigkeiten voll ausschöpfen

## Ziel
Das Hermes muninnDB Memory Plugin von v1.1.0 auf v2.0.0 heben, um alle kognitiven Primitive von muninnDB zu nutzen: MemoryType, Confidence, States, Links/Associations, SSE Streaming, und Vault Stats.

---

## Phase 1: Foundation — Plugin-Struktur verbessern (1–2 Tage)

### 1.1 Plugin in eigenes Repository auslagern
**Warum:** Aktuell liegt es unter `~/.hermes/plugins/muninndb/` — das ist nicht versionierbar und schwer zu teilen.

**Aufgaben:**
- [ ] Neues Repo `hermes-muninndb-provider` erstellen
- [ ] `__init__.py`, `plugin.yaml`, `README.md`, `CHANGELOG.md` migrieren
- [ ] `setup.py` oder `pyproject.toml` für pip-Installation
- [ ] Release als GitHub Release mit Version Tags

**Nutzen:** Professionelles Plugin-Management, einfache Updates, Community-Sharing.

### 1.2 Testsuite aufbauen
**Warum:** Keine Tests aktuell — jede Änderung ist blind.

**Aufgaben:**
- [ ] `tests/test_provider.py` — Mock-Tests für alle MemoryProvider-Methoden
- [ ] `tests/test_circuit_breaker.py` — CB-Logik testen
- [ ] `tests/test_json_request.py` — Retry-Logik testen
- [ ] `pytest` Integration mit `pytest-asyncio` für async-Tests

**Nutzen:** Sichere Refactoring-Grundlage, Regressionsschutz.

---

## Phase 2: Core Features — muninnDB-Primitive nutzen (3–4 Tage)

### 2.1 MemoryType & Confidence in Tool-Schemas
**Warum:** muninnDB unterstützt 6 MemoryTypes und Bayesian Confidence. Aktuell nutzt das Plugin nur `concept` + `content`.

**Aufgaben:**
- [x] `muninn_remember` Schema erweitern:
  ```json
  {
    "memory_type": {"type": "string", "enum": ["Fact", "Decision", "Observation", "Preference", "Issue", "Task"]},
    "confidence": {"type": "number", "minimum": 0, "maximum": 1}
  }
  ```
- [x] `handle_tool_call` anpassen, um `memory_type` als Integer-Enum an muninnDB weiterzugeben
- [x] Default-Werte: `memory_type: "Fact"`, `confidence: 0.8`
- [ ] ~~`state` wurde entfernt~~ — muninnDB verwaltet State intern (immer ACTIVE bei Erstellung)

**Nutzen:** Semantische Kategorisierung, bessere Filterung.

### 2.2 `muninn_link` Tool hinzufügen
**Warum:** Hebbian Learning passiert automatisch, aber **explizite Links** (z.B. "depends_on", "supersedes") sind nicht automatisch.

**Aufgaben:**
- [ ] Neues Tool-Schema:
  ```json
  {
    "name": "muninn_link",
    "parameters": {
      "source_id": "string",
      "target_id": "string",
      "rel_type": {"type": "integer", "description": "1=supports, 2=contradicts, 3=depends_on, 4=supersedes, 5=relates_to, ..."},
      "weight": {"type": "number", "minimum": 0, "maximum": 1}
    }
  }
  ```
- [ ] `handle_tool_call` implementieren: POST `/link`
- [ ] System Prompt Block erweitern: "Use muninn_link to connect related memories"

**Nutzen:** Strukturiertes Wissen, Graph-Traversal in ACTIVATE, bessere Kontext-Verknüpfung.

### 2.3 `muninn_update` — Ausgesetzt / Wartet auf muninnDB API
**Status:** ⚠️ Ausgesetzt — muninnDB REST API (Port 8475) unterstützt aktuell kein Update von Engrams.

**Was wir wissen:**
- PATCH/PUT auf `/api/engrams/{id}` gibt **405 Method Not Allowed**
- `state` wird von muninnDB intern verwaltet (immer ACTIVE bei Erstellung)
- Confidence, Content, Tags können nicht nachträglich geändert werden

**Workaround aktuell:**
- Engram ändern = `muninn_forget` (altes → SOFT_DELETED) + `muninn_remember` (neues)

**Zukunft:**
- Prüfen ob muninnDB MCP-Interface (Port 8750) `muninn_update` unterstützt
- Oder: Auf neues muninnDB Release warten, das REST Update ermöglicht

### 2.4 `muninn_list` Tool hinzufügen
**Warum:** Der Agent hat keine Übersicht über den Vault — nur punktuelles Recall.

**Aufgaben:**
- [ ] Neues Tool-Schema:
  ```json
  {
    "name": "muninn_list",
    "parameters": {
      "limit": {"type": "integer", "default": 20},
      "offset": {"type": "integer", "default": 0},
      "tags": {"type": "array", "description": "Filter by tags"},
      "state": {"type": "string", "description": "Filter by state"}
    }
  }
  ```
- [ ] `handle_tool_call` implementieren: GET `/engrams?vault=...&limit=...`

**Nutzen:** Agent kann den Vault explorieren, Orphans finden, Stale-Memories identifizieren.

---

## Phase 3: Advanced Features — Kognitive Pipeline erweitern (4–5 Tage)

### 3.1 Tag-Filterung in `muninn_recall` und `prefetch`
**Warum:** Aktuell filtert ACTIVATE nur nach `threshold`. Tags werden ignoriert beim Retrieval.

**Aufgaben:**
- [ ] Prüfen, ob muninnDB REST API Tag-Filter in `/activate` unterstützt (Doku prüfen)
- [ ] Falls ja: `tags` Parameter in `_RECALL_SCHEMA` und `_do_prefetch` hinzufügen
- [ ] Falls nein: Client-side Filterung nach Recall implementieren (suboptimal, aber möglich)

**Nutzen:** Profil-basierte Isolation innerhalb eines Shared Vaults (z.B. `tags: ["office"]`).

### 3.2 Predictive Activation / SSE Streaming
**Warum:** muninnDB kann Push-Notifications senden, wenn Memories relevant werden. Das Plugin pollt nicht — es wartet.

**Aufgaben:**
- [ ] Background-Thread in `initialize()` starten: SSE-Client für `/subscribe`
- [ ] Callback-Handler: Wenn relevante Engram aktiviert wird → in `_prefetch_cache` speichern
- [ ] `system_prompt_block` erweitern: "New relevant memories may arrive automatically"

**Nutzen:** Echtzeit-Updates, andere Agents können Memories "pushen", die dann im nächsten Turn sichtbar sind.

### 3.3 Vault Stats Integration
**Warum:** Der Agent hat keine Sicht auf Vault-Health (Engram-Count, Confidence-Distribution, Storage).

**Aufgaben:**
- [ ] Neues Tool `muninn_stats`:
  ```json
  {
    "name": "muninn_stats",
    "parameters": {}
  }
  ```
- [ ] `handle_tool_call` implementieren: GET `/stats?vault=...`
- [ ] Agent kann Vault-Größe, Confidence-Distribution, Coherence Score abfragen

**Nutzen:** Monitoring, Capacity-Planning, Agent kann selbst aufräumen (z.B. "Vault ist 80% voll → archiviere alte Memories").

### 3.4 Auto-Summary & KeyPoints (LLM Enrichment)
**Warum:** muninnDB hat ein Plugin-System für LLM Enrichment. Wenn aktiviert, werden `summary` und `key_points` auto-generiert.

**Aufgaben:**
- [ ] Prüfen, ob LLM Enrichment Plugin in muninnDB aktiviert ist
- [ ] Falls ja: `muninn_read` gibt bereits `summary` und `key_points` zurück — nutzen!
- [ ] In `prefetch` und `recall`: Summary statt Content anzeigen (kürzer, prägnanter)

**Nutzen:** Kürzere Prompts, bessere Lesbarkeit, Token-Einsparung.

---

## Phase 4: Integration — Hermes-Native Features (2–3 Tage)

### 4.1 `on_memory_write` mit MemoryType-Mapping
**Warum:** Built-in Hermes memory writes (MEMORY.md, USER.md) werden gespiegelt — aber ohne Semantik.

**Aufgaben:**
- [ ] Mapping in `on_memory_write`:
  - `target: "memory"` → `memory_type: "Fact"`, `tags: ["memory-mirror", "environment"]`
  - `target: "user"` → `memory_type: "Preference"`, `tags: ["memory-mirror", "user-profile"]`
- [ ] Confidence aus Content-Länge ableiten (länger = höhere Confidence?)

**Nutzen:** Semantisch angereicherte Mirrors, besseres Recall.

### 4.2 `queue_prefetch` mit Context-Enrichment
**Warun:** Aktueller `queue_prefetch` nutzt nur den letzten User-Prompt. Besser: Gesamtkontext der Session.

**Aufgaben:**
- [ ] `queue_prefetch` Signatur ändern: `query: str` → `messages: List[Dict]`
- [ ] Context-Extraction: Letzte 3 Turns zusammenfassen (statt nur letzter Prompt)
- [ ] Cache-Invalidation: Wenn neue Engram geschrieben wird, Cache löschen

**Nutzen:** Relevanteres Prefetching, bessere Hit-Rate.

### 4.3 Curator-Integration
**Warum:** Hermes Curator archiviert Skills. Aber Memories im Vault werden nie geprüft.

**Aufgaben:**
- [ ] Curator-Review-Pass erweitern: Auch muninnDB-Engrams prüfen
- [ ] Oder: Neuer `muninn_curator` Tool im Plugin:
  - Liste alle Engrams mit `state: ACTIVE` und `last_access > 90 Tage`
  - Schlage Archivierung vor
- [ ] `muninn_update` nutzen, um Engrams zu modifizieren (ausgesetzt bis API verfügbar)

**Nutzen:** Vault bleibt schlank, Stale-Memories werden aus ACTIVATE ausgeschlossen.

---

## Phase 5: Performance & Robustheit (2–3 Tage)

### 5.1 MBP-Protokoll (Port 8474) als Alternative zu REST
**Warum:** MBP ist 2× schneller als REST, niedrigere Latenz.

**Aufgaben:**
- [ ] Prüfen, ob Python MBP-Client verfügbar (muninn-python SDK?)
- [ ] Falls ja: `protocol` Config-Option hinzufügen (`rest` vs `mbp`)
- [ ] Falls nein: REST bleibt Default, MBP als Future-Feature dokumentieren

**Nutzen:** Schnelleres Prefetching, geringere Latenz.

### 5.2 Connection Pooling
**Warum:** Aktuell wird pro Request eine neue HTTP-Connection aufgemacht.

**Aufgaben:**
- [ ] `urllib` durch `http.client.HTTPConnection` ersetzen (persistent)
- [ ] Oder: `requests` als optional Dependency (wenn verfügbar)
- [ ] Connection-Keep-Alive für <50ms Requests

**Nutzen:** 30–50% Latenz-Reduktion bei hoher Request-Rate.

### 5.3 Batch-Operations
**Warun:** `sync_turn` schreibt 1 Engram pro Turn. Bei 80 Turns = 80 HTTP-Requests.

**Aufgaben:**
- [ ] Prüfen, ob muninnDB Batch-Write API hat (POST `/engrams/batch`?)
- [ ] Falls ja: `sync_turn` sammelt Engrams, flusht alle 5 Turns oder bei Session-End
- [ ] Falls nein: Client-side Batching implementieren

**Nutzen:** Weniger HTTP-Overhead, bessere Throughput.

---

## Priorisierung & Reihenfolge

| Phase | Aufwand | Impact | Priorität |
|-------|---------|--------|-----------|
| 1.1 Repo + Setup | 1 Tag | Hoch | 🔴 P0 |
| 1.2 Tests | 2 Tage | Hoch | 🔴 P0 |
| 2.1 MemoryType + Confidence | 1 Tag | Sehr hoch | 🔴 P0 |
| 2.2 `muninn_link` | 1 Tag | Hoch | 🟡 P1 |
| 2.3 `muninn_update` | 1 Tag | Hoch | 🟡 P1 |
| 2.4 `muninn_list` | 0.5 Tage | Mittel | 🟢 P2 |
| 3.1 Tag-Filter | 1 Tag | Hoch | 🟡 P1 |
| 3.2 SSE Streaming | 2 Tage | Mittel | 🟢 P2 |
| 3.3 Vault Stats | 0.5 Tage | Mittel | 🟢 P2 |
| 3.4 Auto-Summary | 0.5 Tage | Mittel | 🟢 P2 |
| 4.1–4.3 Integration | 2 Tage | Hoch | 🟡 P1 |
| 5.1–5.3 Performance | 2 Tage | Mittel | 🟢 P2 |

**Empfohlene Reihenfolge:**
1. Phase 1 (Foundation)
2. Phase 2.1 (MemoryType + Confidence)
3. Phase 4.1 (on_memory_write Mapping)
4. Phase 2.2 + 2.3 (Link + Update)
5. Phase 3.1 (Tag-Filter)
6. Rest nach Bedarf

---

## Akzeptanzkriterien v2.0.0

- [ ] Plugin ist als pip-Paket installierbar
- [ ] 90%+ Test-Coverage
- [ ] MemoryType + Confidence werden in allen Writes genutzt (State ist intern)
- [ ] `muninn_link` + `muninn_list` sind verfügbar (`muninn_update` ausgesetzt bis API es unterstützt)
- [ ] Tag-Filterung funktioniert (API-seitig oder client-side)
- [ ] Agent kann Vault-Stats abfragen
- [ ] `on_memory_write` mapped semantisch korrekt
- [ ] README dokumentiert alle Features mit Beispielen

---

## Nächster Schritt?

Soll ich mit **Phase 1.1** (Repo-Setup) anfangen? Oder willst du erst eine Teilmenge priorisieren?
