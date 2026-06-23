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
