import type { Metadata } from "next";
import { Nav } from "@/components/Nav";
import "./globals.css";

export const metadata: Metadata = {
  title: "Career OpenClaw",
  description: "Job intelligence platform",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" className="h-full">
      <body className="flex flex-col h-full">
        <Nav />
        <main className="flex-1 min-h-0 overflow-hidden">{children}</main>
      </body>
    </html>
  );
}
