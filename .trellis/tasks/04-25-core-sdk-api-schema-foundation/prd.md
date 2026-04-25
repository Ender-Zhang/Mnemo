# Core SDK and API schema foundation

## Goal
Expose the first stable MnemoCore integration boundary so external agents and future MCP/RuntimeAdapter work can call Mnemo through compact context, recall, run, replay, and evaluation APIs without coupling to CLI internals.

## Requirements
- Add a Python reference SDK as importable package code.
- Provide language-neutral API schema metadata for the MnemoCore surface.
- Reuse existing runtime, memory, prompt, eval, and replay services.
- Keep payloads compact and JSON-serializable.
- Do not add a network server, MCP dependency, or database migration in this task.
- Expose schema inspection through CLI for harnesses and external integrators.

## Acceptance Criteria
- [x] `MnemoClient.context()` returns prompt-ready compact context with metadata and no raw tool schemas.
- [x] `MnemoClient.recall()` returns compact associative recall cards.
- [x] `MnemoClient.run()` executes through existing local runtime and returns run ids, response, tool summary, and event summary.
- [x] `MnemoClient.replay()` and `MnemoClient.evaluate()` reuse existing harness services.
- [x] CLI can print the MnemoCore API schema as JSON or readable text.
- [x] Tests cover SDK methods, schema shape, CLI output, and package import behavior.
- [x] Checklist and backend specs reflect the new foundation and remaining MCP/RuntimeAdapter work.
