#!/usr/bin/env bun
// Self-contained CLI for searching Wellfound public role and location pages.
// No external CLI framework and zero runtime dependencies.

import { runSearch, type SearchOpts } from "./commands/search.js"
import { runDetail, type DetailOpts } from "./commands/detail.js"
import { baseUrl } from "./helpers.js"

interface Flags {
  _: string[]
  [k: string]: string | boolean | string[]
}

const ALIAS: Record<string, string> = {
  r: "role",
  l: "location",
  q: "role",
  query: "role",
  p: "page",
  n: "limit",
}

function parseFlags(argv: string[]): Flags {
  const flags: Flags = { _: [] }
  for (let i = 0; i < argv.length; i++) {
    const a = argv[i]
    if (!a.startsWith("-")) {
      ;(flags._ as string[]).push(a)
      continue
    }
    const name = a.replace(/^-+/, "")
    const key = ALIAS[name] ?? name
    const next = argv[i + 1]
    let value: string | boolean = true
    if (next !== undefined && !next.startsWith("-")) {
      value = next
      i++
    }
    flags[key] = value
  }
  return flags
}

const HELP = `wellfound-cli — search startup and tech jobs on Wellfound

USAGE
  bun run src/cli.ts search --role <slug> [--location <slug>] [--format json|plain]
  bun run src/cli.ts detail <url|id> [--format json|plain]

SEARCH FLAGS
  --role, -r, -q <slug>    Role slug, e.g. software-engineer, backend-engineer (required).
  --location, -l <slug>   Location slug, e.g. india, bangalore-urban (optional).
  --page, -p <n>          1-indexed page. Default 1.
  --limit, -n <n>         Max results to return. Default 25.
  --format <fmt>          json (default) | plain.

DETAIL FLAGS
  <url|id>                A Wellfound job URL (https://wellfound.com/jobs/...) or ID.
  --format <fmt>          json | plain (default).

EXAMPLES
  bun run src/cli.ts search --role software-engineer --location india --format json
  bun run src/cli.ts detail https://wellfound.com/jobs/2448180-software-engineer --format plain

Source: ${baseUrl()}
`

function parseIntFlag(name: string, raw: string | boolean | string[]): number | null {
  const val = typeof raw === "string" ? Number(raw.trim()) : NaN
  if (!Number.isInteger(val) || val < 1) {
    process.stderr.write(
      JSON.stringify({ error: `--${name} must be a whole number of at least 1, got "${raw}"`, code: "BAD_ARG" }) + "\n",
    )
    return null
  }
  return val
}

const KNOWN_FLAGS: Record<string, Set<string>> = {
  search: new Set(["role", "location", "page", "limit", "format", "help", "h"]),
  detail: new Set(["format", "help", "h"]),
}

async function main(): Promise<number> {
  const argv = process.argv.slice(2)
  const flags = parseFlags(argv)
  const cmd = (flags._ as string[])[0]

  if (!cmd || flags.help || flags.h) {
    process.stdout.write(HELP)
    return cmd ? 0 : 1
  }

  const knownFlags = KNOWN_FLAGS[cmd]
  if (knownFlags) {
    for (const key of Object.keys(flags)) {
      if (key === "_" || knownFlags.has(key)) continue
      process.stderr.write(
        JSON.stringify({
          error: `unknown flag --${key} for '${cmd}' - flags are never silently ignored`,
          code: "UNKNOWN_FLAG",
        }) + "\n",
      )
      return 1
    }
  }

  if (cmd === "search") {
    const role = flags.role
    if (role === undefined || typeof role !== "string" || !role.trim()) {
      process.stderr.write(
        JSON.stringify({ error: "--role requires a non-empty value", code: "BAD_ARG" }) + "\n",
      )
      return 1
    }

    if (flags.location !== undefined && (typeof flags.location !== "string" || !flags.location.trim())) {
      process.stderr.write(
        JSON.stringify({ error: "--location requires a non-empty value", code: "BAD_ARG" }) + "\n",
      )
      return 1
    }

    const fmt = flags.format !== undefined ? String(flags.format) : "json"
    if (!["json", "plain"].includes(fmt)) {
      process.stderr.write(
        JSON.stringify({ error: `--format must be one of json|plain, got "${fmt}"`, code: "BAD_ARG" }) + "\n",
      )
      return 1
    }

    for (const name of ["page", "limit"] as const) {
      if (flags[name] !== undefined) {
        const v = parseIntFlag(name, flags[name])
        if (v === null) return 1
        flags[name] = String(v)
      }
    }

    const opts: SearchOpts = {
      role: String(flags.role),
      location: flags.location ? String(flags.location) : undefined,
      page: flags.page ? Math.max(1, parseInt(flags.page as string, 10)) : 1,
      limit: flags.limit ? Math.max(1, parseInt(flags.limit as string, 10)) : 25,
      format: fmt as SearchOpts["format"],
    }
    return runSearch(opts)
  }

  if (cmd === "detail") {
    const id = (flags._ as string[])[1]
    if (!id) {
      process.stderr.write(JSON.stringify({ error: "detail requires a <url|id>", code: "NO_ID" }) + "\n")
      return 1
    }
    const fmt = flags.format !== undefined ? String(flags.format) : "plain"
    if (!["json", "plain"].includes(fmt)) {
      process.stderr.write(
        JSON.stringify({ error: `--format must be one of json|plain, got "${fmt}"`, code: "BAD_ARG" }) + "\n",
      )
      return 1
    }
    const opts: DetailOpts = { id, format: fmt as DetailOpts["format"] }
    return runDetail(opts)
  }

  process.stderr.write(JSON.stringify({ error: `Unknown command "${cmd}"`, code: "BAD_CMD" }) + "\n")
  return 1
}

main()
  .then((code) => process.exit(code))
  .catch((e) => {
    process.stderr.write(
      JSON.stringify({
        error: e instanceof Error ? e.message : String(e),
        code: "INTERNAL_ERROR",
      }) + "\n",
    )
    process.exit(1)
  })
