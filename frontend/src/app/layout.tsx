import type { Metadata } from "next";
import { WorkspaceProvider } from "@/components/workspace-provider";
import { AppShell } from "@/components/app-shell";
import "katex/dist/katex.min.css";
import "./globals.css";
export const metadata: Metadata = {
  title: "LearnLoop · A little progress, every day",
  description: "A source-grounded adaptive learning workspace. Upload course materials and learn with source-grounded practice.",
};
export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="en">
      <body>
        <WorkspaceProvider>
          <AppShell>{children}</AppShell>
        </WorkspaceProvider>
      </body>
    </html>
  );
}
