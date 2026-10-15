import { copyFile, mkdir, readFile, writeFile } from "node:fs/promises";
import { createHash } from "node:crypto";

const files = {
  "fullcalendar.js": "fullcalendar/index.global.min.js",
  "fullcalendar-locales.js": "@fullcalendar/core/locales-all.global.min.js",
  "fullcalendar-luxon.js": "@fullcalendar/luxon3/index.global.min.js",
  "luxon.js": "luxon/build/global/luxon.min.js",
  "lucide.js": "lucide/dist/umd/lucide.min.js",
  "LICENSE.fullcalendar": "fullcalendar/LICENSE.md",
  "LICENSE.luxon": "luxon/LICENSE.md",
  "LICENSE.lucide": "lucide/LICENSE",
};
await mkdir("web/vendor", { recursive: true });
const hashes = {};
for (const [name, source] of Object.entries(files)) {
  await copyFile(`node_modules/${source}`, `web/vendor/${name}`);
  hashes[name] = createHash("sha256").update(await readFile(`web/vendor/${name}`)).digest("hex");
}
await writeFile("web/vendor/manifest.json", `${JSON.stringify(hashes, null, 2)}\n`);
