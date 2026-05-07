"""Crawler that prefers Mintlify-style llms.txt + .md URLs over HTML scraping.

Why: many modern docs sites (Anthropic, Supabase, Mintlify-hosted projects in general)
publish two AI-friendly artifacts:

  1. /llms.txt           a markdown manifest listing every doc page as a .md URL
  2. /<page>.md          the page itself, pre-rendered to clean markdown

Using these gives us authoritative content with no JavaScript, no chrome stripping,
and no HTML-to-markdown drift. The crawler still falls back to /sitemap.xml + HTML
conversion if llms.txt is missing, so the same module works for non-Mintlify sites.

Output is a list of `FetchedPage` rows. Embeddings are added in a later phase.
"""

from __future__ import annotations

import asyncio
import hashlib
import re
from collections.abc import Iterable
from dataclasses import dataclass

import httpx
from bs4 import BeautifulSoup
from markdownify import markdownify as md_convert
from rich.console import Console
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from doc_qa.config import settings

console = Console()
USER_AGENT = "doc-qa-agent/0.1 (+https://github.com/Tajaddin)"
CONCURRENCY = 8
TIMEOUT_S = 25.0


@dataclass(frozen=True, slots=True)
class FetchedPage:
    url: str
    title: str | None
    markdown: str
    checksum: str
    source: str  # "llms" | "sitemap"


# ---------- URL discovery ----------

_LINK_RE = re.compile(r"\[([^\]]+)\]\((https?://[^)\s]+)\)")
SITEMAP_NS_TAGS = ("sitemapindex", "sitemap", "url", "loc")


async def fetch_sitemap(client: httpx.AsyncClient, url: str) -> list[str]:
    r = await client.get(url, follow_redirects=True)
    r.raise_for_status()
    soup = BeautifulSoup(r.text, "xml")
    urls: list[str] = []
    if soup.find("sitemapindex"):
        for sm in soup.find_all("sitemap"):
            loc = sm.find("loc")
            if loc and loc.text:
                urls.extend(await fetch_sitemap(client, loc.text.strip()))
    else:
        for url_tag in soup.find_all("url"):
            loc = url_tag.find("loc")
            if loc and loc.text:
                urls.append(loc.text.strip())
    return urls


def _parse_llms_txt(text: str) -> list[str]:
    """Pull every link target out of a Mintlify-style llms.txt manifest."""
    return [m.group(2) for m in _LINK_RE.finditer(text)]


async def discover_urls(client: httpx.AsyncClient) -> tuple[list[str], str]:
    """Return (urls, source_label). Try llms.txt first, fall back to the sitemap."""
    base = settings.crawl_base_url.rstrip("/")
    llms_url = f"{base}/llms.txt"
    try:
        r = await client.get(llms_url, follow_redirects=True)
        if r.status_code == 200 and "text/plain" in r.headers.get("content-type", "").lower():
            urls = _parse_llms_txt(r.text)
            if urls:
                console.print(f"discovered {len(urls)} URLs via {llms_url}")
                return urls, "llms"
    except httpx.HTTPError:
        pass
    console.print(f"falling back to {settings.crawl_sitemap_url}")
    urls = await fetch_sitemap(client, settings.crawl_sitemap_url)
    return urls, "sitemap"


def filter_urls(urls: Iterable[str]) -> list[str]:
    base = settings.crawl_base_url.rstrip("/")
    allow = settings.path_allow_prefixes
    deny = settings.path_deny_prefixes
    out: list[str] = []
    seen: set[str] = set()
    for u in urls:
        if not u.startswith(base):
            continue
        path = u[len(base):]
        if allow and not any(path.startswith(p) for p in allow):
            continue
        if deny and any(path.startswith(p) for p in deny):
            continue
        if u in seen:
            continue
        seen.add(u)
        out.append(u)
    return out


# ---------- page fetch + parse ----------

@retry(
    retry=retry_if_exception_type((httpx.HTTPError,)),
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=0.5, min=0.5, max=4),
    reraise=True,
)
async def _http_get(client: httpx.AsyncClient, url: str) -> httpx.Response:
    r = await client.get(url, follow_redirects=True)
    r.raise_for_status()
    return r


_CHROME_SELECTORS = (
    "nav", "footer", "aside", "script", "style", "header",
    ".sidebar", ".navigation", ".breadcrumb", ".feedback",
    "[role=navigation]", "[role=banner]", "[role=contentinfo]",
)

# Mintlify wraps callouts in JSX-style tags inside the rendered .md. Strip the
# wrappers but keep the inner text so the chunker still sees the prose.
_MINTLIFY_TAGS = (
    "Tip", "Note", "Warning", "Info", "Check", "Card", "CardGroup",
    "Frame", "Steps", "Step", "AccordionGroup", "Accordion",
    "Tab", "Tabs", "CodeGroup", "ParamField", "ResponseField",
    "Expandable", "RequestExample", "ResponseExample",
)
_MINTLIFY_TAG_RE = re.compile(
    r"</?(" + "|".join(_MINTLIFY_TAGS) + r")\b[^>]*>",
    re.IGNORECASE,
)
_FRONTMATTER_RE = re.compile(r"^---\n.*?\n---\n", re.DOTALL)
_MULTI_BLANK_RE = re.compile(r"\n{3,}")


def _strip_chrome(soup: BeautifulSoup) -> None:
    for sel in _CHROME_SELECTORS:
        for tag in soup.select(sel):
            tag.decompose()


def _extract_html_title(soup: BeautifulSoup) -> str | None:
    for sel in ("h1", "title"):
        tag = soup.select_one(sel)
        if tag and tag.text.strip():
            return tag.text.strip()
    return None


def _extract_md_title(md: str) -> str | None:
    for line in md.splitlines():
        s = line.strip()
        if s.startswith("# "):
            return s[2:].strip()
    return None


def html_to_markdown(html: str) -> tuple[str | None, str]:
    soup = BeautifulSoup(html, "lxml")
    title = _extract_html_title(soup)
    _strip_chrome(soup)
    main = (
        soup.find("main")
        or soup.find("article")
        or soup.find(attrs={"role": "main"})
        or soup.body
        or soup
    )
    md = md_convert(
        str(main),
        heading_style="ATX",
        bullets="-",
        strip=["script", "style"],
    )
    md = _MULTI_BLANK_RE.sub("\n\n", md).strip()
    return title, md


def clean_markdown(md: str) -> str:
    md = _FRONTMATTER_RE.sub("", md)
    md = _MINTLIFY_TAG_RE.sub("", md)
    md = _MULTI_BLANK_RE.sub("\n\n", md)
    return md.strip()


def checksum_of(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


async def fetch_page(client: httpx.AsyncClient, url: str) -> tuple[str | None, str]:
    r = await _http_get(client, url)
    ctype = r.headers.get("content-type", "").lower()
    body = r.text
    if url.endswith(".md") or "text/plain" in ctype or "text/markdown" in ctype:
        cleaned = clean_markdown(body)
        return _extract_md_title(cleaned), cleaned
    title, md = html_to_markdown(body)
    return title, clean_markdown(md)


# ---------- orchestration ----------

async def crawl(limit: int | None = None) -> list[FetchedPage]:
    timeout = httpx.Timeout(TIMEOUT_S)
    headers = {"User-Agent": USER_AGENT, "Accept": "text/markdown,text/plain,text/html;q=0.9"}
    sem = asyncio.Semaphore(CONCURRENCY)

    async with httpx.AsyncClient(timeout=timeout, headers=headers) as client:
        all_urls, source_label = await discover_urls(client)
        urls = filter_urls(all_urls)
        if limit is None:
            limit = settings.crawl_max_pages
        urls = urls[:limit]
        console.print(
            f"after path filter and limit: {len(urls)} URLs (source={source_label})"
        )

        async def one(url: str) -> FetchedPage | None:
            async with sem:
                try:
                    title, md = await fetch_page(client, url)
                except Exception as e:
                    console.print(f"  [red]skip[/] {url}: {e}")
                    return None
                if not md or len(md) < 80:
                    console.print(f"  [yellow]empty[/] {url}")
                    return None
                return FetchedPage(
                    url=url,
                    title=title,
                    markdown=md,
                    checksum=checksum_of(md),
                    source=source_label,
                )

        results = await asyncio.gather(*(one(u) for u in urls))
        pages = [p for p in results if p is not None]
        console.print(f"fetched: {len(pages)} pages with content")
        return pages
