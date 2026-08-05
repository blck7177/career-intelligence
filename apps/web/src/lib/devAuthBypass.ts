/**
 * Dev auth bypass — local/test only, never in production.
 *
 * Mirrors the backend gate in apps/api/dependencies/auth.py: the bypass only
 * activates when DEV_AUTH_BYPASS=true, and requesting it in a production-like
 * environment is a hard error rather than a silent auth-off.
 *
 * The production signal is APP_ENV, not NODE_ENV: the dev compose stack runs
 * a production Next build (web.Dockerfile sets NODE_ENV=production), so
 * NODE_ENV=production does not mean "deployed to production".
 */
export function resolveDevAuthBypass(env: {
  DEV_AUTH_BYPASS?: string;
  APP_ENV?: string;
}): boolean {
  const requested = (env.DEV_AUTH_BYPASS ?? "").toLowerCase() === "true";
  if (!requested) {
    return false;
  }
  const appEnv = (env.APP_ENV ?? "development").toLowerCase();
  if (appEnv === "production" || appEnv === "staging") {
    throw new Error(
      `DEV_AUTH_BYPASS=true is forbidden when APP_ENV=${appEnv}. ` +
        "Remove DEV_AUTH_BYPASS from the environment.",
    );
  }
  return true;
}
