import {
  baseUrl,
  fetchHtml,
  parseWellfoundHtml,
  stripInvisible,
  writeError,
  type WellfoundItem,
} from "../helpers.js"

export interface SearchOpts {
  role: string
  location?: string
  page: number
  limit: number
  format: "json" | "plain"
}

// Wellfound search output normalizer conforming to /scrape Step 2 contract
export function normalizeWellfoundItem(item: any): Record<string, unknown> {
  return {
    id: item.id,
    title: item.title,
    company: item.company,
    location: item.location,
    date: item.date,
    url: item.job_url || item.url,
  }
}

export async function runSearch(opts: SearchOpts): Promise<number> {
  const roleSlug = opts.role.trim().toLowerCase()
  const locSlug = opts.location ? opts.location.trim().toLowerCase() : ""

  const path = locSlug ? `/role/l/${roleSlug}/${locSlug}` : `/role/r/${roleSlug}`
  const url = `${baseUrl()}${path}`

  let html: string | null
  try {
    html = await fetchHtml(url)
  } catch (err: any) {
    writeError(err.message || String(err), "FETCH_FAILED")
    return 1
  }

  if (html === null) {
    writeError(`role not found: ${roleSlug}`, "ROLE_NOT_FOUND")
    return 1
  }

  let parsed: { items: WellfoundItem[]; warnings: string[] }
  try {
    parsed = parseWellfoundHtml(html)
  } catch (err: any) {
    writeError(err.message || String(err), "PARSE_FAILED")
    return 1
  }

  let items = parsed.items
  if (opts.limit > 0 && items.length > opts.limit) {
    items = items.slice(0, opts.limit)
  }

  const results = items.map((item) => stripInvisible({
    id: item.id,
    title: item.title,
    company: item.company,
    location: item.location,
    date: item.date,
    url: item.url,
    salary: item.salary,
    remote: item.remote,
    years_min: item.years_min,
    years_max: item.years_max,
    description_snippet: item.description_snippet,
  }))

  if (opts.format === "plain") {
    if (results.length === 0) {
      process.stdout.write("No matching jobs found on Wellfound.\n")
      return 0
    }
    const lines: string[] = []
    for (const r of results) {
      lines.push(`${r.title}`)
      lines.push(`${r.company || "—"} · ${r.location || "—"}`)
      if (r.date) lines.push(`Date: ${r.date}`)
      if (r.salary) lines.push(`Salary: ${r.salary}`)
      if (r.url) lines.push(`URL: ${r.url}`)
      lines.push("")
    }
    process.stdout.write(lines.join("\n") + "\n")
  } else {
    const output: Record<string, any> = {
      meta: {
        count: results.length,
        page: opts.page,
        role: roleSlug,
        location: locSlug || null,
      },
      results,
    }
    if (parsed.warnings.length > 0) {
      output.meta.warnings = parsed.warnings
    }
    process.stdout.write(JSON.stringify(output, null, 2) + "\n")
  }

  return 0
}
