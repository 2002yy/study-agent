/** Build the pinned npm library into inert source; never execute it in the host. */
import { buildSync } from "esbuild";
import type { Plugin } from "vite";
import { fileURLToPath } from "node:url";

export function threeSourcePlugin(): Plugin {
  const name = "virtual:study-three-source";
  let source: string | undefined;
  return {
    name: "study-controlled-three-source",
    resolveId(id) { if (id === name) return "\0" + name; },
    load(id) {
      if (id !== "\0" + name) return;
      source ??= buildSync({
        stdin: { contents: 'import * as THREE from "three";Object.defineProperty(globalThis,"THREE",{value:Object.freeze(THREE),writable:false,configurable:false});',
          resolveDir: fileURLToPath(new URL(".", import.meta.url)), sourcefile: "study-three-host.js" },
        bundle: true, write: false, format: "iife", platform: "browser", target: "es2020", minify: true,
        legalComments: "inline",
      }).outputFiles[0].text;
      return `export default ${JSON.stringify(source)};`;
    },
  };
}
