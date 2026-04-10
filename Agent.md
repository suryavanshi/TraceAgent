Locked-in implementation rules I will enforce
IR-first pipeline with strict schemas for:

CircuitSpec

SchematicIR

BoardIR

PatchPlan

VerificationReport

KiCad artifacts are compiled from IR; IR remains source of truth.

No direct LLM writes to raw KiCad files.

Every design-changing action will require:

structured JSON output

schema validation

compiler step to KiCad artifacts

verification stage

visual + machine-readable diffs

Provider abstraction for both OpenAI and Anthropic.

Tool-calling + structured outputs for model-driven design actions.

Stack assumptions:

Backend: Python/FastAPI

Frontend: React/TypeScript

Execution backend: KiCad-first

Monorepo, typed production code, tests (unit + integration), package READMEs, Docker/devcontainer.

Each milestone will end with:

files changed

commands run

test status

TODOs/blockers

Do not invent APIs, file formats, or tool outputs.
When an interface is uncertain, isolate it behind an adapter with a TODO and a mocked test.
Preserve architecture cleanliness even if a feature must be stubbed.
