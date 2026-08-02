import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "Vesper",
  description: "Second-brain dashboard — relationships, journal, finance, study.",
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="en">
      <body>
        <nav className="nav">
          <a href="/" className="brand">
            Vesper
          </a>
          <div className="nav-links">
            <a href="/">Dashboard</a>
            <a href="/graph">Graph</a>
            <a href="/people">People</a>
            <a href="/journal">Journal</a>
            <a href="/finance">Finance</a>
            <a href="/study">Study</a>
            <a href="/calendar">Calendar</a>
          </div>
        </nav>
        <main className="main">{children}</main>
      </body>
    </html>
  );
}
