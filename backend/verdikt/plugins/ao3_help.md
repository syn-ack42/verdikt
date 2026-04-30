# AO3

Fetch fan fiction from [Archive of Our Own](https://archiveofourown.org). Works are fetched in full, but only a representative sample of paragraphs is retained. The primary reason is respect for authors: AO3 creators retain full copyright over their work and have not consented to having it stored wholesale in a third-party database. Verdikt keeps just enough to learn your preferences, not a copy of the work. A secondary benefit is that smaller excerpts also keep your database compact.

## Setting up a search

1. Go to [AO3](https://archiveofourown.org) and search or browse to a tag, fandom, or filtered list
2. Copy the URL from the browser — for example:  
   `https://archiveofourown.org/tags/Original%20Work/works?work_search[sort_column]=kudos`
3. Paste it into the **Search URLs** list in the plugin config
4. Set the **Max works** limit for that URL (how many results to fetch)

You can add multiple search URLs to a single project. Each URL has its own max-works cap.

## Authentication (optional)

Leave the username and password fields empty to fetch only publicly available works. If you have an AO3 account you can provide your credentials to access works visible to registered users.

Credentials are stored encrypted in your project's plugin config. They are never sent to any server other than AO3.

## Content sampling

AO3 works can be very long. By default the plugin keeps about 20% of paragraphs, sampled with a Gaussian distribution centred on the middle of the work — enough to learn preferences, not enough to serve as a substitute for reading the original. The beginning and end of a work are sampled more lightly than the core. Sampling is deterministic per work ID so re-fetching the same work always produces the same excerpt.

Two environment variables tune sampling server-wide:

| Variable | Default | Effect |
|---|---|---|
| `VERDIKT_AO3_SAMPLE_RATE` | `0.20` | Fraction of paragraphs to retain (0.05–1.0) |
| `VERDIKT_AO3_SAMPLE_STDDEV` | `1.5` | Spread of the Gaussian; higher = more even coverage |

## Rate limiting

AO3 is a community-run site. The plugin enforces a minimum delay between requests (default 5 seconds; hard minimum 3 seconds). This is intentional and cannot be configured below 3 seconds.

The delay is controlled by the `VERDIKT_AO3_REQUEST_DELAY` environment variable. Do not set it below the default without a good reason.

## Updating

The **Update** button re-checks each fetched work for a newer `updated_at` timestamp before deciding whether to re-download. Works that have not changed since the last fetch are skipped. New works matching the search URL are fetched and added.
