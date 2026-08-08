import { redirect } from "@/i18n/navigation";

// The site opens on the planner: the root is a redirect, not a page, so
// "what is the default view" is decided in exactly one place. The dashboard
// this used to be lives at /home, still one click away in the nav.
export default async function RootPage({ params }: { params: Promise<{ locale: string }> }) {
  const { locale } = await params;
  redirect({ href: "/tracker", locale });
}
