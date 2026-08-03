import { clerkMiddleware, createRouteMatcher } from "@clerk/nextjs/server";
import createMiddleware from "next-intl/middleware";
import { routing } from "@/i18n/routing";

const handleI18nRouting = createMiddleware(routing);

// Match both the bare and locale-prefixed sign-in route as public.
const isPublicRoute = createRouteMatcher(["/sign-in(.*)", "/:locale/sign-in(.*)"]);

export default clerkMiddleware(async (auth, request) => {
  if (!isPublicRoute(request)) {
    await auth.protect();
  }
  // API/health routes are proxied to the FastAPI backend via next.config.ts
  // rewrites and must stay unprefixed — running them through next-intl's
  // locale routing would redirect e.g. /api/app/runs to /zh/api/app/runs (404).
  const { pathname } = request.nextUrl;
  if (pathname.startsWith("/api") || pathname === "/healthz") {
    return;
  }
  return handleI18nRouting(request);
});

export const config = {
  matcher: [
    // Skip Next.js internals and static files
    "/((?!_next|[^?]*\\.(?:html?|css|js(?!on)|jpe?g|webp|png|gif|svg|ttf|woff2?|ico|csv|docx?|xlsx?|zip|webmanifest)).*)",
    // Always run for API routes
    "/(api|trpc)(.*)",
  ],
};
