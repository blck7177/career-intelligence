/**
 * Server-only token resolver for React Server Components and Route Handlers.
 *
 * This file must ONLY be imported from server-side code (RSC pages, route
 * handlers, server actions). Never import it from "use client" modules or
 * from shared files that are imported by client components.
 *
 * Client Components obtain a token via the useApiToken() hook instead.
 */

import { auth } from "@clerk/nextjs/server";

export async function getServerToken(): Promise<string | null> {
  try {
    const { getToken } = await auth();
    return await getToken();
  } catch {
    return null;
  }
}
