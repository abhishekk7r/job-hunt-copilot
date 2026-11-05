// Helpers for the Wellfound search CLI (Tier A, headless, logged out).
// Zero runtime dependencies, runs under bun.

export const DEFAULT_BASE_URL = "https://wellfound.com"

export function baseUrl(): string {
  const raw = (process.env.WELLFOUND_BASE_URL ?? "").trim()
  return (raw || DEFAULT_BASE_URL).replace(/\/+$/, "")
}

export function writeError(error: string, code: string): void {
  process.stderr.write(JSON.stringify({ error, code }) + "\n")
}

export const UA = "ai-job-search-dev/ai-job-search/1.0 (wellfound-search)"

let lastRequestTime = 0

export async function throttleRequest(): Promise<void> {
  const now = Date.now()
  const elapsed = now - lastRequestTime
  if (elapsed < 3000 && lastRequestTime !== 0) {
    await new Promise((r) => setTimeout(r, 3000 - elapsed))
  }
  lastRequestTime = Date.now()
}

export async function fetchHtml(url: string): Promise<string | null> {
  if (process.env.WELLFOUND_FIXTURE_PATH) {
    const file = Bun.file(process.env.WELLFOUND_FIXTURE_PATH)
    if (await file.exists()) {
      return await file.text()
    }
  }

  await throttleRequest()

  const maxRetries = 3
  let delay = 500

  for (let attempt = 0; attempt <= maxRetries; attempt++) {
    let response: Response
    try {
      response = await fetch(url, {
        headers: {
          "User-Agent": UA,
          Accept: "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        },
        redirect: "follow",
        signal: AbortSignal.timeout(15000),
      })
    } catch (e) {
      throw new Error(
        `could not reach Wellfound at ${url} (${e instanceof Error ? e.message : String(e)})`,
      )
    }

    if (response.status === 403 || response.status === 429) {
      throw new Error(`challenge or rate-limit detected on Wellfound: HTTP ${response.status}`)
    }

    if (response.status >= 500) {
      if (attempt === maxRetries) {
        throw new Error(`Wellfound request failed: ${response.status} ${response.statusText}`)
      }
      await new Promise((r) => setTimeout(r, delay))
      delay = Math.min(delay * 2, 4000)
      continue
    }

    if (response.status === 404) {
      return null
    }

    const text = await response.text()
    if (
      text.includes("cf-chl") ||
      text.includes("Cloudflare") ||
      text.includes("Just a moment...") ||
      text.includes("verify you are human") ||
      text.includes("unusual activity")
    ) {
      throw new Error("challenge detected on Wellfound page")
    }

    return text
  }

  throw new Error("Wellfound request failed after retries")
}

export interface WellfoundJobListing {
  id: string
  title: string
  slug: string
  liveStartAt: number | null
  locationNames: string[]
  remote: boolean
  compensation: string | null
  yearsExperienceMin: number | null
  yearsExperienceMax: number | null
  jobType: string | null
  description: string | null
}

export interface WellfoundItem {
  id: string
  title: string
  company: string | null
  location: string | null
  date: string | null
  url: string
  salary?: string | null
  remote?: boolean
  years_min?: number | null
  years_max?: number | null
  description_snippet?: string | null
  description?: string | null
}

export function parseWellfoundHtml(html: string): {
  items: WellfoundItem[]
  warnings: string[]
} {
  if (
    html.includes("cf-chl") ||
    html.includes("Cloudflare") ||
    html.includes("Just a moment...") ||
    html.includes("verify you are human")
  ) {
    throw new Error("challenge detected on Wellfound page")
  }

  const match = html.match(/<script id="__NEXT_DATA__"[^>]*>([\s\S]*?)<\/script>/)
  if (!match) {
    throw new Error("schema-changed: missing <script id=\"__NEXT_DATA__\"> in page HTML")
  }

  let parsed: any
  try {
    parsed = JSON.parse(match[1])
  } catch (err: any) {
    throw new Error(`schema-changed: malformed __NEXT_DATA__ JSON (${err.message})`)
  }

  const apolloData = parsed?.props?.pageProps?.apolloState?.data
  if (!apolloData || typeof apolloData !== "object") {
    throw new Error("schema-changed: missing props.pageProps.apolloState.data")
  }

  const startupByListingId = new Map<string, string>()

  for (const [key, val] of Object.entries<any>(apolloData)) {
    if (key.startsWith("StartupResult:") && val && typeof val === "object") {
      const companyName = String(val.name || "").trim()
      const highlights = Array.isArray(val.highlightedJobListings) ? val.highlightedJobListings : []
      for (const h of highlights) {
        const ref = h?.__ref
        if (typeof ref === "string" && ref.startsWith("JobListingSearchResult:")) {
          const listingId = ref.replace("JobListingSearchResult:", "")
          if (companyName) {
            startupByListingId.set(listingId, companyName)
          }
        }
      }
    }
  }

  const items: WellfoundItem[] = []
  let missingCompanyCount = 0

  for (const [key, val] of Object.entries<any>(apolloData)) {
    if (key.startsWith("JobListingSearchResult:") && val && typeof val === "object") {
      const id = String(val.id || key.replace("JobListingSearchResult:", ""))
      const company = startupByListingId.get(id) ?? null
      if (!company) {
        missingCompanyCount++
        continue
      }

      const title = decodeHtmlEntities(String(val.title || "")).trim() || "(untitled)"
      const slug = String(val.slug || "").trim()
      const liveStartAt = typeof val.liveStartAt === "number" ? val.liveStartAt : null
      const date = liveStartAt ? new Date(liveStartAt * 1000).toISOString().split("T")[0] : null
      const locArray: string[] = Array.isArray(val.locationNames) ? val.locationNames.map(String) : []
      const location = Array.from(new Set(locArray.filter(Boolean))).join(", ") || null
      const url = `https://wellfound.com/jobs/${id}${slug ? `-${slug}` : ""}`
      const salary = val.compensation ? decodeHtmlEntities(String(val.compensation)).trim() : null
      const remote = Boolean(val.remote)
      const years_min = typeof val.yearsExperienceMin === "number" ? val.yearsExperienceMin : null
      const years_max = typeof val.yearsExperienceMax === "number" ? val.yearsExperienceMax : null
      const rawDesc = typeof val.description === "string" ? val.description : null
      const description = cleanHtml(rawDesc)
      const description_snippet = description ? description.slice(0, 200).trim() : null

      items.push({
        id,
        title,
        company,
        location,
        date,
        url,
        salary,
        remote,
        years_min,
        years_max,
        description_snippet,
        description,
      })
    }
  }

  const warnings: string[] = []
  if (missingCompanyCount > 0) {
    warnings.push(`${missingCompanyCount} listing(s) omitted due to missing company link`)
  }

  return { items, warnings }
}

export function normalizeWellfoundUrl(input: string): { id: string; url: string } | null {
  const trimmed = input.trim()
  if (!trimmed) return null

  const match = trimmed.match(/(?:https?:\/\/wellfound\.com)?\/jobs\/([0-9]+)(?:-([a-z0-9_-]+))?/i)
  if (match) {
    const id = match[1]
    const slug = match[2] || ""
    return {
      id,
      url: `https://wellfound.com/jobs/${id}${slug ? `-${slug}` : ""}`,
    }
  }

  const bareMatch = trimmed.match(/^([0-9]+)(?:-([a-z0-9_-]+))?$/i)
  if (bareMatch) {
    const id = bareMatch[1]
    const slug = bareMatch[2] || ""
    return {
      id,
      url: `https://wellfound.com/jobs/${id}${slug ? `-${slug}` : ""}`,
    }
  }

  return null
}

function numericEntity(cp: number): string {
  return cp >= 0 && cp <= 0x10ffff ? String.fromCodePoint(cp) : ""
}

export function decodeHtmlEntities(text: string): string {
  return text
    .replace(/&amp;/g, "&")
    .replace(/&lt;/g, "<")
    .replace(/&gt;/g, ">")
    .replace(/&quot;/g, '"')
    .replace(/&#39;/g, "'")
    .replace(/&apos;/g, "'")
    .replace(/&#(\d+);/g, (_, dec) => numericEntity(parseInt(dec, 10)))
    .replace(/&#[xX]([0-9a-fA-F]+);/g, (_, hex) => numericEntity(parseInt(hex, 16)))
    .replace(/&nbsp;/g, " ")
}

const INVISIBLE_CHARS =
  /[\u0000-\u0008\u000B\u000C\u000E-\u001F\u007F-\u009F­؜᠎​-‏‪-‮⁠-⁯︀-️﻿\u{E0000}-\u{E007F}\u{E0100}-\u{E01EF}]/gu

export function stripInvisible<T>(value: T): T {
  if (typeof value === "string") return value.replace(INVISIBLE_CHARS, "") as T
  if (Array.isArray(value)) return value.map(stripInvisible) as T
  if (value !== null && typeof value === "object" && Object.getPrototypeOf(value) === Object.prototype) {
    return Object.fromEntries(Object.entries(value).map(([k, v]) => [k, stripInvisible(v)])) as T
  }
  return value
}

const VOID_TAGS = new Set(["area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "source", "track", "wbr"])

function isHiddenTag(attrs: string): boolean {
  for (const m of attrs.matchAll(/([^\s"'=/>]+)(?:\s*=\s*(?:"([^"]*)"|'([^']*)'|([^\s"'>]+)))?/g)) {
    const name = m[1].toLowerCase()
    const value = m[2] ?? m[3] ?? m[4] ?? ""
    if (name === "hidden") return true
    if (name === "style" && /(?:^|;)\s*(?:display\s*:\s*none|visibility\s*:\s*hidden|mso-hide\s*:\s*all)\b/i.test(value)) {
      return true
    }
  }
  return false
}

export function visibleHtml(html: string): string {
  const src = html
    .replace(/<!--[\s\S]*?(?:-->|$)/g, "")
    .replace(/<(script|style|template)\b[^>]*>[\s\S]*?(?:<\/\1\s*>|$)/gi, "")
  const open = /<([a-zA-Z][a-zA-Z0-9-]*)(\s[^>]*)?>/g
  const kept: string[] = []
  let from = 0
  let m: RegExpExecArray | null
  while ((m = open.exec(src)) !== null) {
    if (!m[2] || !isHiddenTag(m[2])) continue
    const tag = m[1].toLowerCase()
    let end = open.lastIndex
    if (!VOID_TAGS.has(tag) && !m[0].endsWith("/>")) {
      const same = new RegExp(`<(/?)${tag}\\b[^>]*>`, "gi")
      same.lastIndex = end
      end = src.length
      let depth = 1
      let s: RegExpExecArray | null
      while ((s = same.exec(src)) !== null) {
        if (s[1]) depth--
        else if (!s[0].endsWith("/>")) depth++
        if (depth === 0) {
          end = same.lastIndex
          break
        }
      }
    }
    kept.push(src.slice(from, m.index))
    from = end
    open.lastIndex = end
  }
  kept.push(src.slice(from))
  return kept.join("")
}

export function cleanHtml(html: string | null | undefined): string | null {
  if (!html) return null
  const withBreaks = visibleHtml(html)
    .replace(/<\s*br\s*\/?>/gi, "\n")
    .replace(/<\/(p|li|ul|ol|div|h\d)>/gi, "\n")
  const text = decodeHtmlEntities(withBreaks.replace(/<[^>]+>/g, " "))
    .replace(/[ \t]+/g, " ")
    .replace(/ *\n */g, "\n")
    .replace(/\n{3,}/g, "\n\n")
    .trim()
  return text || null
}
