import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "Streets of Rage Builder",
  description: "Build Streets of Rage from your ROM, step by step.",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
