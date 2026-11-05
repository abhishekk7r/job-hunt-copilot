// Naukri search output normalizer conforming to /scrape Step 2 contract
export function normalizeNaukriItem(item: any): Record<string, unknown> {
  return {
    id: item.id,
    title: item.title,
    company: item.company,
    location: item.location,
    date: item.date,
    url: item.job_url || item.url,
  }
}
