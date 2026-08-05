import type { Metadata } from "next";
import { notFound } from "next/navigation";
import { hasLocale, NextIntlClientProvider } from "next-intl";
import { getMessages, setRequestLocale } from "next-intl/server";
import { ClerkProvider } from "@clerk/nextjs";
import { TopBar } from "@/components/TopBar";
import { TooltipProvider } from "@/components/ui/tooltip";
import { Toaster } from "@/components/ui/toaster";
import { RunToasts } from "@/components/RunToasts";
import { routing } from "@/i18n/routing";
import "./globals.css";

export const metadata: Metadata = {
  title: "Career Agent",
  description: "Your personal career intelligence agent",
};

export function generateStaticParams() {
  return routing.locales.map((locale) => ({ locale }));
}

interface Props {
  children: React.ReactNode;
  params: Promise<{ locale: string }>;
}

export default async function RootLayout({ children, params }: Props) {
  const { locale } = await params;
  if (!hasLocale(routing.locales, locale)) {
    notFound();
  }
  setRequestLocale(locale);

  const messages = await getMessages();

  return (
    <ClerkProvider>
      <html lang={locale} className="h-full">
        <body className="flex flex-col h-full overflow-hidden">
          <NextIntlClientProvider messages={messages}>
            <TooltipProvider>
              <TopBar />
              <main className="flex-1 min-w-0 flex flex-col overflow-hidden">{children}</main>
              <Toaster />
              {/* Watches runs started anywhere in the app, so finishing is
                  announced even after you have navigated away from whatever
                  button started it. */}
              <RunToasts />
            </TooltipProvider>
          </NextIntlClientProvider>
        </body>
      </html>
    </ClerkProvider>
  );
}
