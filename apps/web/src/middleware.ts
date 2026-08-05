import { clerkMiddleware, createRouteMatcher } from "@clerk/nextjs/server";
import createMiddleware from "next-intl/middleware";
import { routing } from "@/i18n/routing";
import { resolveDevAuthBypass } from "@/lib/devAuthBypass";

const handleI18nRouting = createMiddleware(routing);

// Match both the bare and locale-prefixed sign-in route as public.
const isPublicRoute = createRouteMatcher(["/sign-in(.*)", "/:locale/sign-in(.*)"]);

// Evaluated once per server start. In a production-like APP_ENV this throws,
// failing every request loudly instead of silently serving without auth.
const devAuthBypass = resolveDevAuthBypass({
  DEV_AUTH_BYPASS: process.env.DEV_AUTH_BYPASS,
  APP_ENV: process.env.APP_ENV,
});

if (devAuthBypass) {
  console.warn(
    "DEV_AUTH_BYPASS is enabled — auth.protect() is skipped for every route. NOT FOR PRODUCTION.",
  );
}

export default clerkMiddleware(async (auth, request) => {
  if (!devAuthBypass && !isPublicRoute(request)) {
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
