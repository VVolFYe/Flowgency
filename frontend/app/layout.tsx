import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "Flowgency Traffic Control",
  description: "Live SUMO traffic simulation control center",
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
