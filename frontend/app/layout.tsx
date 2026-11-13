import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "Flowgency · Traffic Simulation",
  description: "Public live SUMO view and protected Operator control center",
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
