import type { Map as MapLibreMap } from "maplibre-gl";

export function registerVehicleIcons(map: MapLibreMap) {
  const colors: Record<string, string> = {
    car: "#f03232", ambulance: "#fff6e8", police: "#4a8de3", fire_brigade: "#ed5a41", bus: "#e6b853",
  };
  for (const [type, color] of Object.entries(colors)) {
    const canvas = document.createElement("canvas");
    canvas.width = 40;
    canvas.height = 64;
    const ctx = canvas.getContext("2d");
    if (!ctx) continue;
    ctx.fillStyle = "#141b20";
    for (const x of [5, 29]) for (const y of [13, 43]) ctx.fillRect(x, y, 6, 10);
    ctx.beginPath();
    ctx.roundRect(9, 4, 22, 56, 7);
    ctx.fillStyle = color;
    ctx.fill();
    ctx.strokeStyle = "#18232b";
    ctx.lineWidth = 2;
    ctx.stroke();
    ctx.fillStyle = "#254b5b";
    ctx.beginPath();
    ctx.roundRect(12, 15, 16, 12, 3);
    ctx.fill();
    ctx.fillRect(13, 45, 14, 7);
    ctx.fillStyle = "#fff7ce";
    ctx.fillRect(11, 7, 5, 3); ctx.fillRect(24, 7, 5, 3);
    ctx.fillStyle = "#bd3838";
    ctx.fillRect(11, 55, 5, 3); ctx.fillRect(24, 55, 5, 3);
    if (type === "ambulance") {
      ctx.fillStyle = "#e63946";
      ctx.fillRect(17, 30, 6, 13); ctx.fillRect(13, 34, 14, 5);
    }
    if (["ambulance", "police", "fire_brigade"].includes(type)) {
      ctx.fillStyle = "#ff4f63"; ctx.fillRect(11, 27, 9, 4);
      ctx.fillStyle = "#459aff"; ctx.fillRect(20, 27, 9, 4);
    }
    map.addImage(`flowgency-${type}`, ctx.getImageData(0, 0, 40, 64), { pixelRatio: 2 });
  }
}
