# Search profile and fit rubric (EXAMPLE)

Template for `config/search_profile.local.md`. Copy this file to `config/search_profile.local.md`
and customize with your specific profile. Keep `config/search_profile.local.md` git-ignored.

## Who
- Senior software engineer / backend developer.
- Primary languages and technologies: [Your core languages, frameworks, databases, cloud].
- Notice period: 30 days.

## What the role must be (judge by the job description, never by the title)
- Core work: Distributed systems, microservices, backend services, high-throughput APIs.
- Must involve backend system design and architecture.
- Anti-signals (cheap filter drops immediately):
  - Frontend-only (React, Vue, Angular without backend).
  - Mobile-only (iOS, Android, Flutter, Swift, Kotlin app development).
  - QA / Testing / Automation Engineer.
  - Engineering Manager, Director, VP.
  - Intern, Graduate, Fresher.

## Seniority by experience asked, not by title
- Ignore title prefixes ("Senior", "Lead", "Staff", "SDE-2").
- Judge by years of experience specified in the job description:
  - Sweet spot: [Target min] to [Target max] years.
  - Hard floor: < [Min floor] years (intern/entry level).
  - Hard ceiling: > [Max ceiling] years (executive/director).

## Location
- Target cities: [e.g. Bengaluru, Hyderabad, Pune, Mumbai, Gurgaon, Noida].
- Work arrangements: Remote India, Hybrid, or On-site in target cities.
- Relocation outside target areas without remote option: FAIL location verdict.

## Compensation (only when the posting states it)
- Target: [Target CTC LPA / range].
- Minimum floor: [Floor CTC LPA].
- Below floor: Skip or mark as below threshold.
- Between floor and target: Flag for consideration.
- Unstated / not mentioned: PASS (most Indian postings do not state compensation).

## Scoring dimensions (same four as rank_state.py; each 0 to 100, from the JD text only)
- Technical (30%): Overlap with backend architecture, primary languages, frameworks, cloud.
- Experience (25%): Years asked aligns with target range, relevant problem domains.
- Behavioral (15%): Autonomy, ownership, engineering culture, thriving signals.
- Career (30%): Growth trajectory, technical depth, domain alignment.

## Notes rules
- Strengths: 1-3 bullet points grounded in the posting text.
- Gaps: 1-3 honest bullet points naming missing requirements or trade-offs.
