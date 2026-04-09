export const APP_NAME = "TraceAgent";
export const APP_TAGLINE = "AI-native PCB design orchestration";

export type HealthStatus = {
  status: "ok" | "degraded";
  service: string;
  version: string;
};
