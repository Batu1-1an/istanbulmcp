import { defineRailway, github, preserve, project, service } from "railway/iac";

export default defineRailway(() => {
  const istanbulmcp = service("istanbulmcp", {
    source: github("Batu1-1an/istanbulmcp", { checkSuites: false }),
    build: { builder: "DOCKERFILE" },
    healthcheck: "/healthz",
    healthcheckTimeout: 30,
    replicas: { "europe-west4-drams3a": { numReplicas: 1 } },
    deploy: {
      restartPolicyType: "ON_FAILURE",
      restartPolicyMaxRetries: 3,
    },
    env: {
      ISKI_API_BEARER_TOKEN: preserve(),
      ISKI_DAMS_SNAPSHOT_CAPTURED_AT: preserve(),
      ISKI_DAMS_SNAPSHOT_JSON: preserve(),
      ISKI_FAULTS_SNAPSHOT_CAPTURED_AT: preserve(),
      ISKI_FAULTS_SNAPSHOT_JSON: preserve(),
      ISKI_FAULTS_SNAPSHOT_JSON_PART_1: preserve(),
      ISKI_FAULTS_SNAPSHOT_JSON_PART_2: preserve(),
      ISKI_RELAY_BASE_URL: preserve(),
      ISKI_RELAY_TOKEN: preserve(),
    },
  });

  return project("istanbulmcp", {
    resources: [istanbulmcp],
  });
});
