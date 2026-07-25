import Script from "next/script";

/** Même site GoatCounter qu’ElectronLibre ; path préfixé par host. */
export default function GoatCounter() {
  return (
    <>
      <Script id="goatcounter-init" strategy="afterInteractive">
        {`window.goatcounter={path:function(p){return location.host+p}}`}
      </Script>
      <Script
        src="https://gc.zgo.at/count.js"
        strategy="afterInteractive"
        data-goatcounter="https://electronlibre.goatcounter.com/count"
      />
    </>
  );
}
