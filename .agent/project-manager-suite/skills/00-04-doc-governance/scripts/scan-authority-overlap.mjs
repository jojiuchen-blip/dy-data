#!/usr/bin/env node

import { readFile } from "node:fs/promises";

function parseArgs(argv) {
  const args = {
    files: [],
    patterns: [],
  };

  for (let i = 0; i < argv.length; i += 1) {
    const arg = argv[i];
    if (arg === "--files") {
      args.files = (argv[i + 1] || "")
        .split(",")
        .map((item) => item.trim())
        .filter(Boolean);
      i += 1;
      continue;
    }
    if (arg === "--patterns") {
      args.patterns = (argv[i + 1] || "")
        .split(",")
        .map((item) => item.trim())
        .filter(Boolean);
      i += 1;
      continue;
    }
    if (arg === "--help" || arg === "-h") {
      args.help = true;
    }
  }

  return args;
}

function usage() {
  return [
    "Usage:",
    "  node <suite-path>/skills/00-04-doc-governance/scripts/scan-authority-overlap.mjs --files a.md,b.md --patterns \"docs/rules,S2 页面先行协议\"",
    "",
    "Options:",
    "  --files      Comma-separated file paths",
    "  --patterns   Comma-separated regex patterns",
  ].join("\n");
}

function collectHeading(line) {
  const match = /^(#{1,6})\s+(.+?)\s*$/.exec(line);
  if (!match) {
    return null;
  }
  return match[2].trim();
}

function formatMatch(file, lineNumber, text) {
  return `${file}:${lineNumber}: ${text.trim()}`;
}

async function scanFile(file, regexes) {
  const raw = await readFile(file, "utf8");
  const lines = raw.split(/\r?\n/);
  const headings = [];
  const matches = new Map();

  regexes.forEach(({ source }) => {
    matches.set(source, []);
  });

  lines.forEach((line, index) => {
    const lineNumber = index + 1;
    const heading = collectHeading(line);
    if (heading) {
      headings.push({ heading, file, lineNumber });
    }

    regexes.forEach(({ source, regex }) => {
      if (regex.test(line)) {
        matches.get(source).push(formatMatch(file, lineNumber, line));
      }
    });
  });

  return { headings, matches };
}

function printHeadingOverlap(headingIndex) {
  const repeated = [...headingIndex.entries()].filter(([, entries]) => entries.length > 1);
  if (repeated.length === 0) {
    console.log("Repeated headings: none");
    return;
  }

  console.log("Repeated headings:");
  repeated
    .sort((a, b) => a[0].localeCompare(b[0], "zh-Hans-CN"))
    .forEach(([heading, entries]) => {
      console.log(`- ${heading}`);
      entries.forEach((entry) => {
        console.log(`  - ${entry.file}:${entry.lineNumber}`);
      });
    });
}

function printPatternMatches(patternIndex) {
  const patterns = [...patternIndex.entries()];
  if (patterns.length === 0) {
    console.log("Pattern matches: no patterns supplied");
    return;
  }

  console.log("Pattern matches:");
  patterns.forEach(([pattern, entries]) => {
    console.log(`- ${pattern}`);
    if (entries.length === 0) {
      console.log("  - no matches");
      return;
    }
    entries.forEach((entry) => {
      console.log(`  - ${entry}`);
    });
  });
}

async function main() {
  const args = parseArgs(process.argv.slice(2));
  if (args.help || args.files.length === 0) {
    console.log(usage());
    process.exit(args.help ? 0 : 1);
  }

  const regexes = args.patterns.map((pattern) => ({
    source: pattern,
    regex: new RegExp(pattern),
  }));

  const headingIndex = new Map();
  const patternIndex = new Map();
  regexes.forEach(({ source }) => {
    patternIndex.set(source, []);
  });

  for (const file of args.files) {
    const { headings, matches } = await scanFile(file, regexes);

    headings.forEach((entry) => {
      if (!headingIndex.has(entry.heading)) {
        headingIndex.set(entry.heading, []);
      }
      headingIndex.get(entry.heading).push(entry);
    });

    matches.forEach((entries, pattern) => {
      patternIndex.get(pattern).push(...entries);
    });
  }

  console.log(`Files scanned: ${args.files.length}`);
  args.files.forEach((file) => console.log(`- ${file}`));
  console.log("");
  printHeadingOverlap(headingIndex);
  console.log("");
  printPatternMatches(patternIndex);
}

main().catch((error) => {
  console.error(error instanceof Error ? error.message : String(error));
  process.exit(1);
});
