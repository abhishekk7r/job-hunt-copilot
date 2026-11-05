import { describe, expect, test } from "bun:test"
import { join } from "path"
import { parseWellfoundHtml } from "../src/helpers"
import { runCLI, parseJSON } from "./helpers"

const FIXTURE_PATH = join(import.meta.dir, "fixtures/role-page.html")

describe("Challenge pages and schema change handling", () => {
  test("challenge page detected in parseWellfoundHtml throws clear error", () => {
    const challengeHtml = "<html><body><title>Just a moment...</title><div class=\"cf-chl-widget\"></div></body></html>"
    expect(() => parseWellfoundHtml(challengeHtml)).toThrow("challenge detected")
  })

  test("missing __NEXT_DATA__ throws schema-changed error", () => {
    const missingScriptHtml = "<html><body><h1>Jobs</h1></body></html>"
    expect(() => parseWellfoundHtml(missingScriptHtml)).toThrow("schema-changed: missing <script id=\"__NEXT_DATA__\">")
  })

  test("missing apolloState.data throws schema-changed error", () => {
    const brokenDataHtml = "<html><body><script id=\"__NEXT_DATA__\" type=\"application/json\">{\"props\":{}}</script></body></html>"
    expect(() => parseWellfoundHtml(brokenDataHtml)).toThrow("schema-changed: missing props.pageProps.apolloState.data")
  })

  test("CLI search runs offline against fixture via WELLFOUND_FIXTURE_PATH", async () => {
    const res = await runCLI(
      ["search", "--role", "software-engineer", "--location", "india"],
      { WELLFOUND_FIXTURE_PATH: FIXTURE_PATH },
    )
    expect(res.exitCode).toBe(0)
    const json = parseJSON<{ meta: { count: number }; results: Array<{ id: string; company: string }> }>(res)
    expect(json.meta.count).toBe(3)
    expect(json.results[0].company).toBe("Initech")
    expect(json.results[1].company).toBe("DC Tech Consulting")
  })

  test("CLI detail runs offline against fixture via WELLFOUND_FIXTURE_PATH", async () => {
    const res = await runCLI(
      ["detail", "https://wellfound.com/jobs/2448180-software-engineer", "--format", "plain"],
      { WELLFOUND_FIXTURE_PATH: FIXTURE_PATH },
    )
    expect(res.exitCode).toBe(0)
    expect(res.stdout).toContain("Become an Initecher")
  })
})
