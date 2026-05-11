import "@/styles/globals.css";
import type { Metadata } from "next";
import { Providers } from "@/lib/query";

export const metadata: Metadata = {
  title: "ckg · central code knowledge graph",
  description: "Multi-repo Neo4j-backed code knowledge graph for AI agents",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body className="min-h-screen antialiased">
        <Providers>{children}</Providers>
      </body>
    </html>
  );
}
