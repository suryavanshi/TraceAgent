"use client";

import { FormEvent, useEffect, useMemo, useState } from "react";
import { APP_NAME, APP_TAGLINE } from "@traceagent/ui-shared";

type Project = {
  id: string;
  name: string;
};

type Snapshot = {
  id: string;
  title: string;
  git_commit_hash: string;
  created_at: string;
};

type RequirementsResponse = {
  proposed_circuit_spec: Record<string, unknown>;
  summary: string;
  open_questions: string[];
};


type SchematicSynthesisResponse = {
  schematic_ir: {
    component_instances: Array<{ instance_id: string; reference: string; value?: string | null }>;
    nets: Array<{ net_id: string; name?: string | null; nodes: Array<{ instance_id: string; pin_number: string }> }>;
  };
  warnings: Array<{ code: string; message: string; severity: string }>;
  schematic_svg: string;
  schematic_svg_path: string;
  schematic_pdf_path: string;
  board_ir_path: string;
  kicad_pcb_path: string;
  board_metadata: Record<string, unknown> & {
    routing_state?: {
      routed_count?: number;
      unrouted_count?: number;
      eligible_autoroute_nets?: string[];
      verification_required?: boolean;
    };
  };
};

type VerificationFinding = {
  code: string;
  message: string;
  details: {
    severity?: string;
    probable_cause?: string;
    affected_nets?: string[];
    affected_components?: string[];
    suggested_fixes?: string[];
  };
};

type VerificationRunDetail = {
  id: string;
  status: string;
  normalized_output: {
    findings: VerificationFinding[];
  };
  explanations: Array<{ code: string; plain_english: string }>;
};

const API_BASE = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

export default function HomePage() {
  const [projects, setProjects] = useState<Project[]>([]);
  const [selectedProjectId, setSelectedProjectId] = useState<string>("");
  const [snapshots, setSnapshots] = useState<Snapshot[]>([]);
  const [requirements, setRequirements] = useState<RequirementsResponse | null>(null);
  const [chatHistory, setChatHistory] = useState<string>("User: Need low-power data logging\nAssistant: Noted, what MCU family?");
  const [latestPrompt, setLatestPrompt] = useState<string>(
    "Make an ESP32 environmental sensor board with USB-C power and I2C sensors.",
  );
  const [loadingRequirements, setLoadingRequirements] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [synthesis, setSynthesis] = useState<SchematicSynthesisResponse | null>(null);
  const [loadingSynthesis, setLoadingSynthesis] = useState(false);
  const [activeTab, setActiveTab] = useState<"summary" | "schematic" | "pcb">("summary");
  const [verification, setVerification] = useState<VerificationRunDetail | null>(null);
  const [loadingVerification, setLoadingVerification] = useState(false);
  const [highlightedObject, setHighlightedObject] = useState<string | null>(null);

  useEffect(() => {
    const load = async () => {
      try {
        const projectResponse = await fetch(`${API_BASE}/projects`);
        if (!projectResponse.ok) {
          return;
        }
        const loadedProjects = (await projectResponse.json()) as Project[];
        setProjects(loadedProjects);
        if (loadedProjects.length > 0) {
          setSelectedProjectId(loadedProjects[0].id);
        }
      } catch {
        setError("Unable to load project history.");
      }
    };

    void load();
  }, []);

  useEffect(() => {
    const loadSnapshots = async () => {
      if (!selectedProjectId) {
        setSnapshots([]);
        return;
      }
      const snapshotResponse = await fetch(`${API_BASE}/projects/${selectedProjectId}/snapshots`);
      if (!snapshotResponse.ok) {
        setSnapshots([]);
        return;
      }
      setSnapshots((await snapshotResponse.json()) as Snapshot[]);
    };

    void loadSnapshots();
  }, [selectedProjectId]);

  const parsedHistory = useMemo(() => {
    return chatHistory
      .split("\n")
      .map((line) => line.trim())
      .filter(Boolean)
      .map((line) => {
        if (line.toLowerCase().startsWith("assistant:")) {
          return { role: "assistant", content: line.replace(/^assistant:\s*/i, "") };
        }
        return { role: "user", content: line.replace(/^user:\s*/i, "") };
      });
  }, [chatHistory]);



  const onSynthesizeSchematic = async () => {
    setError(null);
    setLoadingSynthesis(true);
    try {
      if (!selectedProjectId || !requirements) {
        setError("Derive requirements first before schematic synthesis.");
        return;
      }

      const response = await fetch(`${API_BASE}/projects/${selectedProjectId}/schematic/synthesize`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          circuit_spec: requirements.proposed_circuit_spec,
          selected_parts: [],
        }),
      });

      if (!response.ok) {
        setError("Schematic synthesis failed.");
        return;
      }

      setSynthesis((await response.json()) as SchematicSynthesisResponse);
    } catch {
      setError("Schematic synthesis failed.");
    } finally {
      setLoadingSynthesis(false);
    }
  };

  const onDeriveRequirements = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    setError(null);
    setLoadingRequirements(true);

    try {
      if (!selectedProjectId) {
        setError("Create a project first to derive requirements.");
        return;
      }

      const response = await fetch(`${API_BASE}/projects/${selectedProjectId}/requirements/derive`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          latest_user_request: latestPrompt,
          chat_history: parsedHistory,
        }),
      });

      if (!response.ok) {
        setError("Requirements derivation failed.");
        return;
      }

      setRequirements((await response.json()) as RequirementsResponse);
    } catch {
      setError("Requirements derivation failed.");
    } finally {
      setLoadingRequirements(false);
    }
  };

  const onRunVerification = async () => {
    setError(null);
    if (!selectedProjectId) {
      setError("Select a project first.");
      return;
    }
    setLoadingVerification(true);
    try {
      const response = await fetch(`${API_BASE}/projects/${selectedProjectId}/verification-runs`, { method: "POST" });
      if (!response.ok) {
        setError("Verification run failed.");
        return;
      }
      setVerification((await response.json()) as VerificationRunDetail);
      setActiveTab("summary");
    } catch {
      setError("Verification run failed.");
    } finally {
      setLoadingVerification(false);
    }
  };

  const findingsBySeverity = useMemo(() => {
    const grouped: Record<string, VerificationFinding[]> = {};
    for (const finding of verification?.normalized_output.findings ?? []) {
      const severity = finding.details?.severity ?? "info";
      grouped[severity] = grouped[severity] ?? [];
      grouped[severity].push(finding);
    }
    return grouped;
  }, [verification]);

  return (
    <main style={{ maxWidth: 960, margin: "0 auto", padding: "3rem 1rem" }}>
      <h1>{APP_NAME}</h1>
      <p>{APP_TAGLINE}</p>

      <section>
        <h2>Requirements Agent</h2>
        <p>Convert natural-language PCB requests into a proposed CircuitSpec and clarification questions.</p>
        <form onSubmit={onDeriveRequirements} style={{ display: "grid", gap: "0.75rem" }}>
          <label>
            Project
            <select
              value={selectedProjectId}
              onChange={(event) => setSelectedProjectId(event.target.value)}
              style={{ display: "block", width: "100%" }}
            >
              <option value="">Select project</option>
              {projects.map((project) => (
                <option key={project.id} value={project.id}>
                  {project.name}
                </option>
              ))}
            </select>
          </label>
          <label>
            Chat history (one line per message, prefix with User:/Assistant:)
            <textarea
              value={chatHistory}
              onChange={(event) => setChatHistory(event.target.value)}
              rows={4}
              style={{ display: "block", width: "100%" }}
            />
          </label>
          <label>
            Latest request
            <textarea
              value={latestPrompt}
              onChange={(event) => setLatestPrompt(event.target.value)}
              rows={3}
              style={{ display: "block", width: "100%" }}
            />
          </label>
          <button type="submit" disabled={loadingRequirements}>
            {loadingRequirements ? "Deriving…" : "Derive CircuitSpec"}
          </button>
        </form>
      </section>

      <section style={{ marginTop: "2rem" }}>
        <h2>Extraction result</h2>
        {error ? <p>{error}</p> : null}
        {!requirements ? (
          <p>No derived requirements yet.</p>
        ) : (
          <>
            <h3>Summary</h3>
            <p>{requirements.summary}</p>
            <h3>Open questions</h3>
            {requirements.open_questions.length === 0 ? (
              <p>None.</p>
            ) : (
              <ul>
                {requirements.open_questions.map((question) => (
                  <li key={question}>{question}</li>
                ))}
              </ul>
            )}
            <h3>Proposed CircuitSpec</h3>
            <pre style={{ background: "#f6f8fa", padding: "1rem", overflowX: "auto" }}>
              {JSON.stringify(requirements.proposed_circuit_spec, null, 2)}
            </pre>
          </>
        )}
      </section>

      <section style={{ marginTop: "2rem" }}>
        <h2>Schematic Synthesis</h2>
        <div style={{ display: "flex", gap: "0.5rem", marginBottom: "0.75rem" }}>
          <button type="button" onClick={() => setActiveTab("summary")}>Summary</button>
          <button type="button" onClick={() => setActiveTab("schematic")}>Schematic</button>
          <button type="button" onClick={() => setActiveTab("pcb")}>PCB</button>
        </div>
        <p>Generate textual schematic structure from CircuitSpec and selected parts.</p>
        <button type="button" onClick={onSynthesizeSchematic} disabled={loadingSynthesis || !requirements}>
          {loadingSynthesis ? "Synthesizing…" : "Generate SchematicIR"}
        </button>

        {!synthesis ? (
          <p style={{ marginTop: "0.75rem" }}>No schematic generated yet.</p>
        ) : activeTab === "summary" ? (
          <div style={{ marginTop: "1rem", display: "grid", gap: "1rem" }}>
            <div>
              <h3>Components</h3>
              <ul>
                {synthesis.schematic_ir.component_instances.map((component) => (
                  <li key={component.instance_id}>
                    <code>{component.reference}</code> — {component.value ?? component.instance_id}
                    {highlightedObject && highlightedObject === component.reference ? " ⭐" : ""}
                  </li>
                ))}
              </ul>
            </div>
            <div>
              <h3>Nets</h3>
              <ul>
                {synthesis.schematic_ir.nets.map((net) => (
                  <li key={net.net_id}>
                    <strong>{net.name ?? net.net_id}</strong> ({net.nodes.length} nodes)
                    {highlightedObject && highlightedObject === (net.name ?? net.net_id) ? " ⭐" : ""}
                  </li>
                ))}
              </ul>
            </div>
            <div>
              <h3>Warnings</h3>
              {synthesis.warnings.length === 0 ? (
                <p>No lint warnings.</p>
              ) : (
                <ul>
                  {synthesis.warnings.map((warning, index) => (
                    <li key={`${warning.code}-${index}`}>
                      <code>{warning.code}</code> — {warning.message}
                    </li>
                  ))}
                </ul>
              )}
            </div>
          </div>
        ) : activeTab === "schematic" ? (
          <div style={{ marginTop: "1rem" }}>
            <h3>Schematic Preview (SVG)</h3>
            <div style={{ border: "1px solid #ddd", padding: "0.5rem", overflowX: "auto" }} dangerouslySetInnerHTML={{ __html: synthesis.schematic_svg }} />
            <p style={{ marginTop: "0.5rem" }}>
              SVG artifact: <code>{synthesis.schematic_svg_path}</code><br />
              PDF artifact: <code>{synthesis.schematic_pdf_path}</code>
            </p>
          </div>
        ) : (
          <div style={{ marginTop: "1rem" }}>
            <h3>PCB Preview (Placeholder)</h3>
                        <div style={{ border: "1px solid #ddd", borderRadius: 8, padding: "0.75rem", marginBottom: "0.75rem" }}>
              <h4 style={{ marginTop: 0 }}>Routing Status</h4>
              <p style={{ margin: "0.25rem 0" }}>
                Routed: <strong>{synthesis.board_metadata.routing_state?.routed_count ?? 0}</strong> / Unrouted: <strong>{synthesis.board_metadata.routing_state?.unrouted_count ?? 0}</strong>
              </p>
              <p style={{ margin: "0.25rem 0" }}>
                Autorouting policy: <code>non-critical-only</code>
                {synthesis.board_metadata.routing_state?.verification_required ? " (verification required)" : ""}
              </p>
            </div>
            <div style={{ border: "1px dashed #999", borderRadius: 8, padding: "1rem", background: "#fafafa" }}>
              <p style={{ margin: 0 }}>Initial board template generated. Autorouting assistance is optional.</p>
              <ul>
                {Object.entries(synthesis.board_metadata).map(([key, value]) => (
                  <li key={key}>
                    <code>{key}</code>: {typeof value === "object" ? JSON.stringify(value) : String(value)}
                  </li>
                ))}
              </ul>
            </div>
            {Array.isArray((synthesis.board_metadata.placement_overlay as { overlays?: Array<Record<string, unknown>> } | undefined)?.overlays) ? (
              <div style={{ marginTop: "1rem", border: "1px solid #ddd", borderRadius: 8, padding: "0.75rem" }}>
                <h4 style={{ marginTop: 0 }}>Placement Overlays</h4>
                <ul>
                  {((synthesis.board_metadata.placement_overlay as { overlays: Array<Record<string, unknown>> }).overlays).map((overlay, idx) => (
                    <li key={`${overlay.instance_id ?? "overlay"}-${idx}`}>
                      <strong>{String(overlay.instance_id ?? "unknown")}</strong> @
                      ({String(overlay.x_mm ?? "?")}, {String(overlay.y_mm ?? "?")}) —
                      {String(overlay.group ?? "ungrouped")}
                    </li>
                  ))}
                </ul>
              </div>
            ) : null}
            <p style={{ marginTop: "0.5rem" }}>
              BoardIR artifact: <code>{synthesis.board_ir_path}</code><br />
              KiCad PCB artifact: <code>{synthesis.kicad_pcb_path}</code>
            </p>
          </div>
        )}
      </section>

      <section style={{ marginTop: "2rem", borderTop: "1px solid #ddd", paddingTop: "1rem" }}>
        <h2>Verification Issues (ERC)</h2>
        <button type="button" onClick={onRunVerification} disabled={loadingVerification}>
          {loadingVerification ? "Running ERC…" : "Run ERC"}
        </button>
        {!verification ? (
          <p style={{ marginTop: "0.75rem" }}>No verification runs yet.</p>
        ) : (
          <div style={{ marginTop: "0.75rem" }}>
            <p>Status: <strong>{verification.status}</strong></p>
            {Object.entries(findingsBySeverity).map(([severity, findings]) => (
              <div key={severity} style={{ marginBottom: "0.75rem" }}>
                <h3>{severity.toUpperCase()}</h3>
                <ul>
                  {findings.map((finding, index) => {
                    const firstObject =
                      finding.details?.affected_components?.[0] ?? finding.details?.affected_nets?.[0] ?? null;
                    const explainer = verification.explanations.find((item) => item.code === finding.code)?.plain_english;
                    return (
                      <li key={`${finding.code}-${index}`}>
                        <button
                          type="button"
                          onClick={() => setHighlightedObject(firstObject)}
                          style={{ marginRight: "0.5rem" }}
                        >
                          Highlight
                        </button>
                        <code>{finding.code}</code> — {finding.message}
                        {explainer ? <p style={{ margin: "0.25rem 0" }}>{explainer}</p> : null}
                      </li>
                    );
                  })}
                </ul>
              </div>
            ))}
          </div>
        )}
      </section>

      <section style={{ marginTop: "2rem", borderTop: "1px solid #ddd", paddingTop: "1rem" }}>
        <h2>Snapshot History</h2>
        {snapshots.length === 0 ? (
          <p>No snapshots yet.</p>
        ) : (
          <ul>
            {snapshots.map((snapshot) => (
              <li key={snapshot.id}>
                <strong>{snapshot.title}</strong> — {new Date(snapshot.created_at).toLocaleString()} —
                <code> {snapshot.git_commit_hash.slice(0, 12)}</code>
              </li>
            ))}
          </ul>
        )}
      </section>
    </main>
  );
}
