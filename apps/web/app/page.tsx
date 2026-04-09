import { APP_NAME, APP_TAGLINE } from "@traceagent/ui-shared";

export default function HomePage() {
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
    </main>
  );
}
