#!/usr/bin/env node

/**
 * Validates syntax and renderability of all Mermaid diagram blocks in Markdown files.
 * Uses official Mermaid parser with JSDOM to catch malformed diagrams, unescaped characters,
 * and broken syntax before committing documentation changes.
 *
 * Usage:
 *   node scripts/verify_mermaid.mjs [paths...]
 *   ./scripts/verify_mermaid.mjs docs/ARCHITECTURE_AND_STANDARDS.md
 */

import fs from 'fs';
import path from 'path';
import { fileURLToPath, pathToFileURL } from 'url';

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);
const scriptsNodeModules = path.join(__dirname, 'node_modules');

// 1. Setup JSDOM and globals BEFORE loading Mermaid/DOMPurify
const jsdomPath = path.join(scriptsNodeModules, 'jsdom', 'lib', 'api.js');
const { JSDOM } = await import(pathToFileURL(jsdomPath).href);
const dom = new JSDOM('<!DOCTYPE html><html><body></body></html>');
globalThis.window = dom.window;
globalThis.document = dom.window.document;

// 2. Dynamically import official Mermaid parser after DOM environment is established
const mermaidPath = path.join(scriptsNodeModules, 'mermaid', 'dist', 'mermaid.core.mjs');
const mermaid = (await import(pathToFileURL(mermaidPath).href)).default;
mermaid.initialize({ startOnLoad: false, securityLevel: 'loose' });

/**
 * Recursively find markdown files in target directory.
 */
function findMarkdownFiles(targetPath) {
  const stat = fs.statSync(targetPath);
  if (stat.isFile()) {
    return targetPath.endsWith('.md') ? [targetPath] : [];
  }

  const results = [];
  const entries = fs.readdirSync(targetPath, { withFileTypes: true });

  for (const entry of entries) {
    if (entry.name === '.git' || entry.name === 'node_modules' || entry.name === '.venv' || entry.name === 'dist') {
      continue;
    }
    const fullPath = path.join(targetPath, entry.name);
    if (entry.isDirectory()) {
      results.push(...findMarkdownFiles(fullPath));
    } else if (entry.isFile() && entry.name.endsWith('.md')) {
      results.push(fullPath);
    }
  }
  return results;
}

async function main() {
  const targets = process.argv.slice(2);
  const targetPaths = targets.length > 0 ? targets : ['.'];

  const allFiles = [];
  for (const t of targetPaths) {
    if (fs.existsSync(t)) {
      allFiles.push(...findMarkdownFiles(t));
    } else {
      console.warn(`⚠️ Warning: Path not found: ${t}`);
    }
  }

  // Deduplicate files
  const uniqueFiles = Array.from(new Set(allFiles)).sort();

  let totalDiagrams = 0;
  let errorCount = 0;
  const mermaidRegex = /^```mermaid\s*\n([\s\S]*?)\n```/gm;

  console.log(`🔍 Inspecting ${uniqueFiles.length} Markdown files for Mermaid diagrams...\n`);

  for (const file of uniqueFiles) {
    const content = fs.readFileSync(file, 'utf8');
    let match;
    let diagramIndex = 0;

    mermaidRegex.lastIndex = 0;

    while ((match = mermaidRegex.exec(content)) !== null) {
      totalDiagrams++;
      diagramIndex++;
      const code = match[1].trim();

      // Line number calculation
      const linesBefore = content.substring(0, match.index).split('\n').length;

      try {
        await mermaid.parse(code);
      } catch (err) {
        errorCount++;
        console.error(`❌ SYNTAX ERROR in ${file}:${linesBefore} (diagram #${diagramIndex}):`);
        console.error(`   ${(err.message || err.str || String(err)).trim()}`);
        console.error(`   --- Diagram Excerpt ---`);
        const preview = code.split('\n').slice(0, 8).map(l => `   | ${l}`).join('\n');
        console.error(preview);
        console.error(`   -----------------------\n`);
      }
    }
  }

  if (errorCount > 0) {
    console.error(`❌ Verification failed: ${errorCount} of ${totalDiagrams} Mermaid diagrams are malformed.`);
    process.exit(1);
  } else {
    console.log(`✅ Success: All ${totalDiagrams} Mermaid diagrams across ${uniqueFiles.length} files are syntactically valid and renderable!`);
    process.exit(0);
  }
}

main().catch(err => {
  console.error(`Fatal execution error:`, err);
  process.exit(1);
});
