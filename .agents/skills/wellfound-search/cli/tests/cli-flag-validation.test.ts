import { describe, expect, test } from "bun:test"
import { runCLI } from "./helpers"

function parsedStderr(stderr: string): { error?: string; code?: string } {
  try {
    return JSON.parse(stderr)
  } catch {
    return {}
  }
}

describe("Wellfound CLI flag validation", () => {
  test("unknown flag exits 1 with UNKNOWN_FLAG", async () => {
    const res = await runCLI(["search", "--bogus"])
    expect(res.exitCode).toBe(1)
    const err = parsedStderr(res.stderr)
    expect(err.code).toBe("UNKNOWN_FLAG")
  })

  test("missing --role exits 1 with BAD_ARG", async () => {
    const res = await runCLI(["search"])
    expect(res.exitCode).toBe(1)
    const err = parsedStderr(res.stderr)
    expect(err.code).toBe("BAD_ARG")
    expect(err.error).toContain("--role")
  })

  test("empty --role exits 1 with BAD_ARG", async () => {
    const res = await runCLI(["search", "--role", "   "])
    expect(res.exitCode).toBe(1)
    const err = parsedStderr(res.stderr)
    expect(err.code).toBe("BAD_ARG")
    expect(err.error).toContain("--role")
  })

  test("empty --location exits 1 with BAD_ARG", async () => {
    const res = await runCLI(["search", "--role", "backend-engineer", "--location", "  "])
    expect(res.exitCode).toBe(1)
    const err = parsedStderr(res.stderr)
    expect(err.code).toBe("BAD_ARG")
    expect(err.error).toContain("--location")
  })

  test("unsupported format exits 1 with BAD_ARG", async () => {
    const res = await runCLI(["search", "--role", "backend-engineer", "--format", "yaml"])
    expect(res.exitCode).toBe(1)
    const err = parsedStderr(res.stderr)
    expect(err.code).toBe("BAD_ARG")
    expect(err.error).toContain("--format")
  })

  test("fractional or non-numeric page exits 1 with BAD_ARG", async () => {
    const res = await runCLI(["search", "--role", "backend-engineer", "--page", "1.5"])
    expect(res.exitCode).toBe(1)
    const err = parsedStderr(res.stderr)
    expect(err.code).toBe("BAD_ARG")
    expect(err.error).toContain("--page")
  })
})
