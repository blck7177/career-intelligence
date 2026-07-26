import { definePluginEntry } from "openclaw/plugin-sdk/plugin-entry";

// career-intelligence's own worker builds session_key deterministically as
// "agent:{agent_id}:workspace:{workspace_id}:run:{run_id}:task:{task_id}:attempt:{attempt}"
// (packages/domain/agent_jobs/planner.py::build_session_key) and sends it as
// the x-openclaw-session-key header on every invocation. It never accepts a
// session key from the model, so run_id/task_id parsed out of it here are
// worker-authoritative ground truth, independent of anything the agent typed.
const SESSION_KEY_PATTERN = /:run:([^:]+):task:([^:]+):attempt:/;

export default definePluginEntry({
  id: "career-exec-identity-guard",
  name: "Career Exec Identity Guard",
  description:
    "Injects worker-authoritative run_id/task_id into exec env for career-intelligence wrapper calls.",
  register(api) {
    api.on("resolve_exec_env", async (event, ctx) => {
      if (event.toolName !== "exec") return {};

      const sessionKey = event.sessionKey ?? ctx.sessionKey ?? "";
      const match = SESSION_KEY_PATTERN.exec(sessionKey);
      if (!match) return {};

      const [, runId, taskId] = match;
      return {
        CAREER_TRUE_RUN_ID: runId,
        CAREER_TRUE_TASK_ID: taskId,
      };
    });
  },
});
