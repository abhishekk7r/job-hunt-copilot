import {
  cleanHtml,
  fetchHtml,
  normalizeWellfoundUrl,
  stripInvisible,
  writeError,
  type WellfoundItem,
} from "../helpers.js"

export interface DetailOpts {
  id: string
  format: "json" | "plain"
}

export async function runDetail(opts: DetailOpts): Promise<number> {
  const norm = normalizeWellfoundUrl(opts.id)
  if (!norm) {
    writeError(`could not parse a Wellfound job URL or ID from "${opts.id}"`, "BAD_ID")
    return 1
  }

  let html: string | null
  try {
    html = await fetchHtml(norm.url)
  } catch (err: any) {
    writeError(err.message || String(err), "FETCH_FAILED")
    return 1
  }

  if (html === null) {
    writeError("job not found", "NOT_FOUND")
    return 1
  }

  let title = "Job Details"
  let company: string | null = null
  let location: string | null = null
  let date: string | null = null
  let salary: string | null = null
  let description: string | null = null
  let remote = false
  let years_min: number | null = null
  let years_max: number | null = null

  // Try extracting from __NEXT_DATA__ if present
  const nextDataMatch = html.match(/<script id="__NEXT_DATA__"[^>]*>([\s\S]*?)<\/script>/)
  if (nextDataMatch) {
    try {
      const data = JSON.parse(nextDataMatch[1])
      const apollo = data?.props?.pageProps?.apolloState?.data
      if (apollo && typeof apollo === "object") {
        for (const [k, v] of Object.entries<any>(apollo)) {
          if (k.startsWith(`JobListing:${norm.id}`) || k.startsWith(`JobListingSearchResult:${norm.id}`)) {
            if (v.title) title = String(v.title)
            if (v.description) description = cleanHtml(v.description)
            if (v.compensation) salary = String(v.compensation)
            if (v.liveStartAt) date = new Date(v.liveStartAt * 1000).toISOString().split("T")[0]
            if (Array.isArray(v.locationNames)) location = Array.from(new Set(v.locationNames)).join(", ")
            if (v.remote !== undefined) remote = Boolean(v.remote)
            if (typeof v.yearsExperienceMin === "number") years_min = v.yearsExperienceMin
            if (typeof v.yearsExperienceMax === "number") years_max = v.yearsExperienceMax
          }
          if (k.startsWith("StartupResult:") && v?.name) {
            company = String(v.name)
          }
        }
      }
    } catch {
      // Fall through to HTML fallback
    }
  }

  // Fallback if description still not found: parse readable body text
  if (!description) {
    description = cleanHtml(html)
  }

  const result: WellfoundItem = stripInvisible({
    id: norm.id,
    title,
    company,
    location,
    date,
    url: norm.url,
    salary,
    remote,
    years_min,
    years_max,
    description,
  })

  if (opts.format === "plain") {
    process.stdout.write((result.description || "(no description)") + "\n")
  } else {
    process.stdout.write(JSON.stringify(result, null, 2) + "\n")
  }

  return 0
}
