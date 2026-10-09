"""What reports exist, what they are keyed on when two dates are compared, and what each one's history is."""
from dataclasses import dataclass


@dataclass(frozen=True)
class ReportSpec:
    name: str
    label: str
    blurb: str
    kind: str  # "as_of": the state on one date; "range": totals over a period ending on the date
    keys: tuple[str, ...]  # identity columns when comparing two dates
    history: str  # where its history comes from, shown to the owner and to agents


CATALOG: tuple[ReportSpec, ...] = (
    ReportSpec("indexing", "Indexing", "Counts of URLs per issue for each site.", "as_of", ("project",),
               "Exact stored status from the day this change was deployed; before that, reconstructed from inspection history with today's rules."),
    ReportSpec("non-indexed", "Not indexed", "Every URL with a problem: issue, last crawl, word count.", "as_of", ("project", "url"),
               "Same as Indexing."),
    ReportSpec("urls", "All URLs", "Every sitemap URL with its status: shows pages added and removed over time.", "as_of", ("project", "url"),
               "Same as Indexing."),
    ReportSpec("rankings", "Page rankings", "Average position per page, weighted by impressions across its queries.", "as_of", ("project", "url"),
               "Weekly Search Console rollups, kept indefinitely; uses weeks that had fully ended by the date."),
    ReportSpec("striking-distance", "Striking distance", "Queries at positions 8 to 20 that are worth a push.", "as_of", ("project", "query"),
               "Weekly Search Console rollups; the last four complete weeks before the date."),
    ReportSpec("cannibalisation", "Cannibalisation", "Queries where more than one page competes.", "as_of", ("project", "query"),
               "Weekly Search Console rollups; the last four complete weeks before the date."),
    ReportSpec("traffic", "Traffic", "Clicks, impressions, CTR, position and sessions over a period ending on the date.", "range", ("project",),
               "Daily Search Console and GA4 rows, kept indefinitely (Search Console itself only offers about 16 months)."),
    ReportSpec("alerts", "Alerts", "The alerts showing on that date.", "as_of", ("project", "message"),
               "The alert state saved by every collector run since the first traffic collection."),
    ReportSpec("keywords", "Keyword candidates", "Candidates with their status as of the date.", "as_of", ("project", "keyword"),
               "Created and decided timestamps; a 'written' status is shown as of the day it was decided."),
    ReportSpec("digest", "Weekly digest", "One stored snapshot per site per week.", "as_of", ("project",),
               "Frozen when each week was built; weeks before the first stored digest do not exist."),
)

BY_NAME = {spec.name: spec for spec in CATALOG}
NAMES = tuple(spec.name for spec in CATALOG)
GRANULARITIES = ("total", "day", "week", "month")
