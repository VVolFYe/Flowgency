import type { Metadata } from "next";
import "./globals.css";
import "maplibre-gl/dist/maplibre-gl.css";
import "./taste.css";

export const metadata: Metadata = {
  title: "Flowgency · Traffic Simulation",
  description: "Public SUMO view with protected Analyst and Operator workspaces",
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
