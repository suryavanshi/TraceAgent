"use client";

import { useEffect, useState } from "react";
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

const API_BASE = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

export default function HomePage() {
  const [snapshots, setSnapshots] = useState<Snapshot[]>([]);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const load = async () => {
      try {
        const projectResponse = await fetch(`${API_BASE}/projects`);
        if (!projectResponse.ok) {
          return;
        }
        const projects = (await projectResponse.json()) as Project[];
        if (projects.length === 0) {
          return;
        }
        const snapshotResponse = await fetch(`${API_BASE}/projects/${projects[0].id}/snapshots`);
        if (!snapshotResponse.ok) {
          return;
        }
        setSnapshots((await snapshotResponse.json()) as Snapshot[]);
      } catch {
        setError("Unable to load project history.");
      }
    };

    void load();
  }, []);

  return (
    <main style={{ maxWidth: 900, margin: "0 auto", padding: "3rem 1rem" }}>
      <h1>{APP_NAME}</h1>
      <p>{APP_TAGLINE}</p>
      <section>
        <h2>Monorepo scaffold ready</h2>
        <ul>
          <li>FastAPI backend service</li>
          <li>Python worker for async jobs</li>
          <li>Shared schemas and PCB design IR packages</li>
          <li>Dockerized local development stack</li>
        </ul>
      </section>

      <section style={{ marginTop: "2rem", borderTop: "1px solid #ddd", paddingTop: "1rem" }}>
        <h2>Snapshot History</h2>
        {error ? <p>{error}</p> : null}
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
