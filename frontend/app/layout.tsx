import type { Metadata } from "next";
import { Manrope } from "next/font/google";
import "./globals.css";
import ClientProviders from "@/components/ClientProviders";

const manrope = Manrope({
  variable: "--font-manrope",
  subsets: ["latin"],
});

export const metadata: Metadata = {
  title: "Supa-Connect",
  description: "AI SQL and analytics landing page with Clerk authentication.",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="en">
      <body className={`${manrope.variable} antialiased`}>
        <ClientProviders>{children}</ClientProviders>
      </body>
    </html>
  );
}
