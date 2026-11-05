import { describe, expect, test } from "bun:test"
import { join } from "path"
import { parseWellfoundHtml } from "../src/helpers"

const FIXTURE_PATH = join(import.meta.dir, "fixtures/role-page.html")

describe("Wellfound HTML and Apollo data parsing", () => {
  test("extracts job listings and maps startups correctly from fixture", async () => {
    const html = await Bun.file(FIXTURE_PATH).text()
    const { items, warnings } = parseWellfoundHtml(html)

    expect(items.length).toBe(3)
    expect(warnings.length).toBe(0)

    const first = items[0]
    expect(first.id).toBe("2448180")
    expect(first.title).toBe("Software Engineer")
    expect(first.company).toBe("Initech")
    expect(first.location).toContain("Bengaluru")
    expect(first.date).toBe("2026-10-28")
    expect(first.url).toBe("https://wellfound.com/jobs/2448180-software-engineer")
    expect(first.salary).toContain("$40k")
    expect(first.remote).toBe(true)
    expect(first.years_min).toBe(4)
    expect(first.years_max).toBeNull()
    expect(first.description).toContain("Become an Initecher")

    const second = items[1]
    expect(second.id).toBe("4903437")
    expect(second.company).toBe("DC Tech Consulting")

    const third = items[2]
    expect(third.id).toBe("4903436")
    expect(third.title).toBe("Senior Software Engineer")
    expect(third.company).toBe("DC Tech Consulting")
    expect(third.years_min).toBe(6)
  })

  test("handles listings with missing company by omitting and warning", () => {
    const sampleHtml = `
      <!DOCTYPE html><html><body>
      <script id="__NEXT_DATA__" type="application/json">
      {
        "props": {
          "pageProps": {
            "apolloState": {
              "data": {
                "JobListingSearchResult:999": {
                  "id": "999",
                  "title": "Orphan Job",
                  "slug": "orphan-job",
                  "liveStartAt": 1793169764
                }
              }
            }
          }
        }
      }
      </script>
      </body></html>
    `
    const { items, warnings } = parseWellfoundHtml(sampleHtml)
    expect(items.length).toBe(0)
    expect(warnings.length).toBe(1)
    expect(warnings[0]).toContain("1 listing(s) omitted due to missing company link")
  })
})
