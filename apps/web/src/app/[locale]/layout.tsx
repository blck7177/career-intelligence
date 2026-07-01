import type { Metadata } from "next";
import { Suspense } from "react";
import { notFound } from "next/navigation";
import { hasLocale, NextIntlClientProvider } from "next-intl";
import { getMessages, setRequestLocale } from "next-intl/server";
import { ClerkProvider } from "@clerk/nextjs";
import { Nav } from "@/components/Nav";
import { LanguageSwitcher } from "@/components/LanguageSwitcher";
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
        <body className="flex h-full overflow-hidden">
          <NextIntlClientProvider messages={messages}>
            <Nav />
            <main className="flex-1 min-w-0 flex flex-col overflow-hidden">{children}</main>
            {/* Language switcher — floats top-right-of-center on every page */}
            <div className="fixed top-3 right-[220px] z-50 shadow-md rounded-lg">
              <Suspense fallback={null}>
                <LanguageSwitcher />
              </Suspense>
            </div>
          </NextIntlClientProvider>
        </body>
      </html>
    </ClerkProvider>
  );
}
