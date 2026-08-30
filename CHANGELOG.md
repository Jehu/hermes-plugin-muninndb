# Changelog

All notable changes to this project are documented here.

## 1.2.1 - 2026-08-28

- Publish the muninnDB provider as an independent repository.
- Add memory types and confidence values to `muninn_remember`.
- Add explicit engram linking and update tools.
- Add configurable recall threshold.
- Add circuit-breaker protection and retry transient network errors.
- Add background prefetch and pre-compression persistence hooks.
- Add optional `HERMES_TENANT` scoping.
- Send the memory type through the muninnDB REST field `type`.
- Support hosts with explicit `http://` or `https://` schemes.

## 1.0.0

- Initial Hermes Agent memory-provider implementation.
- Add remember, recall, read, and forget tools.
- Add turn synchronization, prefetch, session-end persistence, and memory mirroring.
