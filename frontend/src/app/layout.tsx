import type { Metadata } from "next";
import { Inter } from "next/font/google";
import Nav from "../components/Nav";
import "./globals.css";

const inter = Inter({
  subsets: ["latin"],
  display: "swap",
  variable: "--font-inter",
});

export const metadata: Metadata = {
  title: "Vesper",
  description: "Second-brain dashboard — relationships, journal, finance, study.",
};

export const viewport = {
  themeColor: "#0a0c12",
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="en" className={inter.variable} data-theme="dark">
      <body>
        <Nav />
        <main className="main">{children}</main>
      </body>
    </html>
  );
}
