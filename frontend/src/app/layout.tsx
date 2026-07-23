import { Libre_Baskerville, Source_Sans_3 } from "next/font/google";
import type { Metadata, Viewport } from "next";
import "./globals.css";

const display = Libre_Baskerville({
  subsets: ["latin"],
  weight: ["400", "700"],
  variable: "--font-display",
});

const body = Source_Sans_3({
  subsets: ["latin"],
  weight: ["400", "600", "700"],
  variable: "--font-body",
});

export const metadata: Metadata = {
  title: "Observatoire de la désinformation",
  description:
    "Palmarès roulant des médias français selon les Community Notes de X (densité CN / Posts).",
  applicationName: "desinfo",
  icons: {
    icon: [
      { url: "/icon.svg", type: "image/svg+xml" },
      { url: "/favicon.ico", sizes: "any" },
    ],
    apple: [{ url: "/apple-icon.png", sizes: "180x180", type: "image/png" }],
  },
};

export const viewport: Viewport = {
  themeColor: "#0f6b4c",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="fr">
      <body className={`${display.variable} ${body.variable}`}>{children}</body>
    </html>
  );
}
