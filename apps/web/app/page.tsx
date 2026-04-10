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
