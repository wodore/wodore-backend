// Validate dumped map style documents with the AUTHORITATIVE MapLibre
// style-spec validator — the exact package the frontend gates styles
// with (@maplibre/maplibre-gl-style-spec validateStyleMin).
//
// Why this exists alongside styl: styl v0.0.6's ruleset does not
// implement every expression rule — the 2026-11-06 staging incident
// shipped an icon-size ["*", zoom-ladder, count-scale] product that
// MapLibre rejects ("zoom expression may only be used as input to a
// top-level step or interpolate") but styl passed. The frontend's own
// gate is the ground truth; CI runs the same call.
//
// Usage: node scripts/validate_map_styles_spec.mjs <dir-or-file>...
//   - validates every *.json against validateStyleMin
//   - fails (exit 1) on any severity === "error" — warnings pass
//     (parity with the frontend's isUsableStyle)
//
// Input documents must be parameter-RESOLVED (dump_map_styles resolves
// seed parameter tokens with their defaults; {{env:…}} tokens embedded
// in URL strings are fine — any string is a valid URL).

import { readdirSync, readFileSync } from "node:fs";
import { join } from "node:path";
import { validateStyleMin } from "@maplibre/maplibre-gl-style-spec";

const targets = process.argv.slice(2);
if (targets.length === 0) {
  console.error("usage: node validate_map_styles_spec.mjs <dir-or-file>...");
  process.exit(2);
}

const files = [];
for (const target of targets) {
  try {
    const stat = readdirSync(target, { withFileTypes: true });
    for (const entry of stat) {
      if (
        entry.isFile() &&
        entry.name.endsWith(".json") &&
        !entry.name.startsWith("_")
      ) {
        files.push(join(target, entry.name));
      }
    }
  } catch {
    files.push(target); // not a directory — treat as a file
  }
}

let failed = 0;
for (const file of files) {
  let doc;
  try {
    doc = JSON.parse(readFileSync(file, "utf8"));
  } catch (error) {
    console.error(`✗ ${file}: not valid JSON (${error.message})`);
    failed += 1;
    continue;
  }
  const errors = validateStyleMin(doc).filter((e) => e.severity === "error");
  if (errors.length > 0) {
    failed += 1;
    console.error(`✗ ${file}`);
    for (const error of errors) {
      console.error(`   ${error.message}`);
    }
  }
}

if (failed > 0) {
  console.error(`${failed} of ${files.length} style document(s) invalid`);
  process.exit(1);
}
console.log(`${files.length} style document(s) valid (maplibre style-spec)`);
