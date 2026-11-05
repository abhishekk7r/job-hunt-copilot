# Naukri URL Reference

## Search URLs
- Allowed slug path: `https://www.naukri.com/<keywords>-jobs-in-<location>` (optionally `?experience=<n>`)
- Allowed detail path: `https://www.naukri.com/job-listings*`
- Disallowed paths: `/jobsearch/`, `/candidate/`

## Robots.txt Directives
- Robots URL: `https://www.naukri.com/robots.txt`
- Disallow: `/jobsearch/`
- Disallow: `/candidate/`
- Allow: `/job-listings*`
- Allow: `/*-jobs*`

## In-Chrome Reading
Read rendered page text and accessibility tree directly; never rely on brittle CSS selectors.
