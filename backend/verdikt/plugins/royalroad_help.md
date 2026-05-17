# Royal Road

Fetch web fictions from [Royal Road](https://www.royalroad.com). Long works are sampled at two stages — first a subset of chapters is selected, then a subset of paragraphs is retained — keeping your database compact while covering the breadth of a work for preference learning.

## Setting up sources

You can combine any mix of the three source types in a single project.

### Fiction URLs

Paste one or more direct links to specific Royal Road fiction pages (e.g. `https://www.royalroad.com/fiction/12345/my-story`). These are always fetched regardless of other settings.

### Search / Browse URLs

Go to Royal Road, search or browse to a tag, genre, or ranking page, and copy the URL. Each entry has its own **Max** cap (how many fictions to fetch from that page).

### Following list (requires login)

Enable **Import followed fictions** and provide your Royal Road email and password. The plugin logs in, scrapes your following list, and adds every followed fiction as a source. The credential is stored encrypted in your project config and never sent anywhere except Royal Road.

## Content sampling

Royal Road fictions can run to hundreds of chapters. The plugin uses two-stage Gaussian sampling to avoid fetching everything while still covering the shape of each work:

1. **Chapter selection** — a Gaussian-weighted selection picks roughly 30% of chapters (biased toward the middle of the work). Only the selected chapters are downloaded.
2. **Paragraph sampling** — from the downloaded chapters, roughly 20% of paragraphs are retained, again with a Gaussian bias toward the centre.

Sampling is deterministic per fiction ID so re-fetching the same fiction always produces the same excerpt.

Two pairs of environment variables tune each stage server-wide:

| Variable | Default | Effect |
|---|---|---|
| `VERDIKT_RR_CHAPTER_RATE` | `0.30` | Fraction of chapters to download (0.05–1.0) |
| `VERDIKT_RR_CHAPTER_STDDEV` | `1.5` | Gaussian spread for chapter selection; higher = more even coverage |
| `VERDIKT_RR_SAMPLE_RATE` | `0.20` | Fraction of paragraphs to retain from downloaded chapters |
| `VERDIKT_RR_SAMPLE_STDDEV` | `1.5` | Gaussian spread for paragraph sampling |

## Rate limiting

The plugin enforces a delay between requests (default 2 seconds; hard minimum 1 second). Royal Road does not publish an official API or rate-limit policy, but excessive crawling causes problems for their servers and risks IP blocks. Do not lower the delay without good reason.

Configurable via `VERDIKT_RR_REQUEST_DELAY` (seconds).

## Updating

The **Update** button re-checks each fetched fiction for a newer `updated_at` timestamp before deciding whether to re-download. Fictions that have not changed since the last fetch are skipped. New fictions matching search/browse URLs are fetched and added.
