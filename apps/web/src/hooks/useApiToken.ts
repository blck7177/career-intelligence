"use client";

/**
 * Auth provider abstraction for API token retrieval.
 *
 * All components should import getToken from this hook instead of
 * calling @clerk/nextjs directly. If the auth provider changes
 * (e.g. NextAuth, Supabase Auth), only this file needs to be updated.
 */
import { useAuth } from "@clerk/nextjs";

export function useApiToken(): () => Promise<string | null> {
  const { getToken } = useAuth();
  return getToken;
}

/**
 * The signed-in user's id, or null while auth is still resolving.
 *
 * Any client-side state that OUTLIVES a component — module scope, sessionStorage
 * — has to be keyed by this. Clerk routes a sign-out through the Next router
 * rather than reloading the page, so the JS module survives the account switch
 * and unkeyed state carries one user's decisions into the next user's session.
 */
export function useApiUserId(): string | null {
  const { userId } = useAuth();
  return userId ?? null;
}
