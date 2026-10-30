#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
استخراج کامل نمونه‌پاسخ‌های مستندات BoxAPI با Playwright + playwright-stealth

قابلیت‌ها:
- تشخیص خودکار محیط بدون گرافیک و اجرای headless
- باز کردن هر ۳۶ اندپوینت از سایدبار مستندات
- کلیک روی دکمهٔ «نمایش Response» در بخش «نمونه پاسخ / Response example»
- انتظار چند ثانیه‌ای برای نمایش خروجی
- استخراج کامل JSON از pre/code یا شبکه
- ذخیرهٔ همهٔ پاسخ‌ها در یک فایل JSON
- نمایش خروجی کامل در ترمینال
"""

from __future__ import annotations

import asyncio
import json
import os
import platform
import re
import sys
import time
import unicodedata
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from difflib import SequenceMatcher
from hashlib import sha256
from pathlib import Path
from typing import Optional
from urllib.parse import urljoin, urlparse

# ------------------------------------------------------------
# نمایش صحیح فارسی در ویندوز
# ------------------------------------------------------------
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")


# ------------------------------------------------------------
# ایمپورت Playwright
# ------------------------------------------------------------
try:
    from playwright.async_api import async_playwright
except ModuleNotFoundError:
    raise SystemExit(
        "Playwright نصب نیست. اجرا کنید:\n"
        "  pip install -U playwright\n"
        "  playwright install chromium"
    )


# ------------------------------------------------------------
# ایمپورت playwright-stealth با سازگاری نسخهٔ ۱ و ۲
# ------------------------------------------------------------
STEALTH_CLASS = None
LEGACY_STEALTH_ASYNC = None

try:
    # نسخهٔ ۲.x
    from playwright_stealth import Stealth  # type: ignore

    STEALTH_CLASS = Stealth
except Exception:
    try:
        # نسخهٔ ۱.x
        from playwright_stealth import stealth_async as _legacy_stealth_async  # type: ignore

        LEGACY_STEALTH_ASYNC = _legacy_stealth_async
    except Exception as exc:
        raise SystemExit(
            "playwright-stealth نصب نیست یا خراب است.\n"
            "  pip install -U playwright-stealth\n"
            f"جزئیات: {exc}"
        )


STEALTH_MODE = "legacy"

if STEALTH_CLASS is not None:
    try:
        _s = STEALTH_CLASS()
        if callable(getattr(_s, "use_async", None)):
            STEALTH_MODE = "auto"
        elif callable(getattr(_s, "apply_stealth_async", None)):
            STEALTH_MODE = "manual"
    except Exception:
        pass

if STEALTH_MODE == "legacy" and LEGACY_STEALTH_ASYNC is None:
    raise SystemExit(
        "هیچ روش سازگاری با playwright-stealth پیدا نشد.\n"
        "لطفاً نسخهٔ جدید را نصب کنید: pip install -U playwright-stealth"
    )


# ------------------------------------------------------------
# تشخیص خودکار headless
# ------------------------------------------------------------
def detect_headless_default() -> bool:
    """
    اگر کاربر صریحاً HEADLESS را تنظیم کرده باشد، از آن استفاده می‌کند.
    در غیر این صورت، در لینوکس/یونیکس اگر DISPLAY وجود نداشته باشد،
    headless را True می‌کند تا از خطای XServer جلوگیری شود.
    """
    explicit = os.getenv("HEADLESS")
    if explicit is not None:
        return explicit.strip().lower() in {"1", "true", "yes", "on"}

    if platform.system() in {"Linux", "Darwin"}:
        display = os.getenv("DISPLAY", "").strip()
        if not display:
            return True

    return False


HEADLESS = detect_headless_default()


# ------------------------------------------------------------
# تنظیمات
# ------------------------------------------------------------
DEFAULT_DOCS_URL = "https://boxapi.ir/docs/instagram/data-api/"
OUTPUT_DIR = Path(__file__).resolve().parent / "boxapi_output"

PAGE_TIMEOUT_MS = 20_000
NAV_TIMEOUT_MS = 45_000
POST_CLICK_WAIT_MS = 4_500
NETWORK_WAIT_SECONDS = 2.0
PRINT_FULL_RESPONSES = os.getenv("PRINT_FULL", "1").strip().lower() not in {
    "0",
    "false",
    "no",
    "off",
}

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/131.0.0.0 Safari/537.36"
)


# ------------------------------------------------------------
# ۳۶ اندپوینت
# ------------------------------------------------------------
ENDPOINTS = [
    # User (16)
    {
        "category": "User",
        "name": "Get Info by username",
        "action": "user_get_info_by_username",
        "test": "boxapi.php?action=user_get_info_by_username&username=instagram",
    },
    {
        "category": "User",
        "name": "Get Info by id",
        "action": "user_get_info_by_id",
        "test": "boxapi.php?action=user_get_info_by_id&id=12281817",
    },
    {
        "category": "User",
        "name": "Get Web Profile Info",
        "action": "user_get_web_profile_info",
        "test": "boxapi.php?action=user_get_web_profile_info&username=instagram",
    },
    {
        "category": "User",
        "name": "Get Media",
        "action": "user_get_media",
        "test": "boxapi.php?action=user_get_media&id=12281817&count=12",
    },
    {
        "category": "User",
        "name": "Get Media by username",
        "action": "user_get_media_by_username",
        "test": "boxapi.php?action=user_get_media_by_username&username=instagram&count=12",
    },
    {
        "category": "User",
        "name": "Get Clips",
        "action": "user_get_clips",
        "test": "boxapi.php?action=user_get_clips&id=173560420&count=12",
    },
    {
        "category": "User",
        "name": "Get Guides",
        "action": "user_get_guides",
        "test": "boxapi.php?action=user_get_guides&id=25025320",
    },
    {
        "category": "User",
        "name": "Get Tags",
        "action": "user_get_tags",
        "test": "boxapi.php?action=user_get_tags&id=173560420&count=12",
    },
    {
        "category": "User",
        "name": "Get Followers",
        "action": "user_get_followers",
        "test": "boxapi.php?action=user_get_followers&id=12281817&count=12",
    },
    {
        "category": "User",
        "name": "Get Following",
        "action": "user_get_following",
        "test": "boxapi.php?action=user_get_following&id=12281817&count=12",
    },
    {
        "category": "User",
        "name": "Get Stories",
        "action": "user_get_stories",
        "test": "boxapi.php?action=user_get_stories&ids=12281817,173560420",
    },
    {
        "category": "User",
        "name": "Get Highlights",
        "action": "user_get_highlights",
        "test": "boxapi.php?action=user_get_highlights&id=12281817",
    },
    {
        "category": "User",
        "name": "Get Live",
        "action": "user_get_live",
        "test": "boxapi.php?action=user_get_live&id=12281817",
    },
    {
        "category": "User",
        "name": "Get Similar Accounts",
        "action": "user_get_similar_accounts",
        "test": "boxapi.php?action=user_get_similar_accounts&id=173560420",
    },
    {
        "category": "User",
        "name": "Search Users",
        "action": "user_search",
        "test": "boxapi.php?action=user_search&query=Boxapi",
    },
    {
        "category": "User",
        "name": "Get About",
        "action": "user_get_about",
        "test": "boxapi.php?action=user_get_about&id=7141291",
    },

    # Media (7)
    {
        "category": "Media",
        "name": "Media Get Info",
        "action": "media_get_info",
        "test": "boxapi.php?action=media_get_info&id=2967835229909923253",
    },
    {
        "category": "Media",
        "name": "Media Get Info by shortcode",
        "action": "media_get_info_by_shortcode",
        "test": "boxapi.php?action=media_get_info_by_shortcode&shortcode=Cm9DyYNooPD",
    },
    {
        "category": "Media",
        "name": "Media Get Comments",
        "action": "media_get_comments",
        "test": "boxapi.php?action=media_get_comments&id=2967835229909923253",
    },
    {
        "category": "Media",
        "name": "Media Get Likes by shortcode",
        "action": "media_get_likes_by_shortcode",
        "test": "boxapi.php?action=media_get_likes_by_shortcode&shortcode=Ckv3mrWq7W1",
    },
    {
        "category": "Media",
        "name": "Media Get id by shortcode",
        "action": "media_get_id_by_shortcode",
        "test": "boxapi.php?action=media_get_id_by_shortcode&shortcode=Ckv3mrWq7W",
    },
    {
        "category": "Media",
        "name": "Media Get shortcode by id",
        "action": "media_get_shortcode_by_id",
        "test": "boxapi.php?action=media_get_shortcode_by_id&id=2967835229909923253",
    },
    {
        "category": "Media",
        "name": "Search Clips",
        "action": "media_search_clips",
        "test": "boxapi.php?action=media_search_clips&query=زخم+کاری",
    },

    # Guide (1)
    {
        "category": "Guide",
        "name": "Guide Get Info",
        "action": "guide_get_info",
        "test": "boxapi.php?action=guide_get_info&id=123456",
    },

    # Location (3)
    {
        "category": "Location",
        "name": "Location Get Info",
        "action": "location_get_info",
        "test": "boxapi.php?action=location_get_info&id=213385402",
    },
    {
        "category": "Location",
        "name": "Location Get Media",
        "action": "location_get_media",
        "test": "boxapi.php?action=location_get_media&id=213385402",
    },
    {
        "category": "Location",
        "name": "Location Search",
        "action": "location_search",
        "test": "boxapi.php?action=location_search&query=tehran",
    },

    # Hashtag (3)
    {
        "category": "Hashtag",
        "name": "Hashtag Get Info",
        "action": "hashtag_get_info",
        "test": "boxapi.php?action=hashtag_get_info&name=catsofinstagram",
    },
    {
        "category": "Hashtag",
        "name": "Hashtag Get Media",
        "action": "hashtag_get_media",
        "test": "boxapi.php?action=hashtag_get_media&name=catsofinstagram",
    },
    {
        "category": "Hashtag",
        "name": "Hashtag Search",
        "action": "hashtag_search",
        "test": "boxapi.php?action=hashtag_search&query=cat",
    },

    # Highlight (1)
    {
        "category": "Highlight",
        "name": "Highlight Get Stories",
        "action": "highlight_get_stories",
        "test": "boxapi.php?action=highlight_get_stories&ids=17895698145014548,17895698145014549",
    },

    # Comment (2)
    {
        "category": "Comment",
        "name": "Comment Get Likes",
        "action": "comment_get_likes",
        "test": "boxapi.php?action=comment_get_likes&id=17895698145014548",
    },
    {
        "category": "Comment",
        "name": "Comment Get Replies",
        "action": "comment_get_replies",
        "test": "boxapi.php?action=comment_get_replies&id=17895698145014548&media_id=2967835229909923253",
    },

    # Audio (2)
    {
        "category": "Audio",
        "name": "Audio Get Media",
        "action": "audio_get_media",
        "test": "boxapi.php?action=audio_get_media&id=123456789",
    },
    {
        "category": "Audio",
        "name": "Audio Search",
        "action": "audio_search",
        "test": "boxapi.php?action=audio_search&query=hello",
    },

    # Account (1)
    {
        "category": "Account",
        "name": "Account Info",
        "action": "account_get_info",
        "test": "boxapi.php?action=account_get_info",
    },
]


# ------------------------------------------------------------
# ابزارهای کمکی
# ------------------------------------------------------------
SPECIFIC_RESPONSE_BUTTON_RE = re.compile(
    r"(نمایش\s*Response|Show\s*Response)", re.IGNORECASE
)
GENERIC_RESPONSE_BUTTON_RE = re.compile(r"Response", re.IGNORECASE)
RESPONSE_HEADING_RE = re.compile(
    r"(نمونه\s*پاسخ|Response\s*example)", re.IGNORECASE
)


def normalize_url(url: str) -> str:
    url = url.strip()
    if not re.match(r"^https?://", url, re.IGNORECASE):
        url = "https://" + url
    return url


def derive_docs_root(base_url: str) -> str:
    parsed = urlparse(base_url)

    if parsed.path.lower().endswith("boxapi.php"):
        return f"{parsed.scheme}://{parsed.netloc}/docs/instagram/"

    u = base_url.rstrip("/") + "/"

    for marker in ("/docs/instagram/data-api", "/docs/instagram/"):
        if marker in u:
            return u.split(marker)[0] + "/docs/instagram/"

    if parsed.netloc.endswith("boxapi.ir"):
        return f"{parsed.scheme}://{parsed.netloc}/docs/instagram/"

    return u


def norm_text(value: str) -> str:
    value = unicodedata.normalize("NFKC", value or "")
    value = value.replace("\u200c", " ").replace("\u200d", " ")
    value = re.sub(r"[^\w\u0600-\u06FF]+", " ", value, flags=re.UNICODE)
    return re.sub(r"\s+", " ", value).strip().casefold()


def slugify_name(name: str) -> str:
    value = unicodedata.normalize("NFKD", name)
    value = value.encode("ascii", "ignore").decode("ascii")
    value = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    return value


def try_parse_json(text: str):
    cleaned = (text or "").strip()
    if not cleaned:
        return None

    try:
        return json.loads(cleaned)
    except Exception:
        pass

    starts = [i for i in (cleaned.find("{"), cleaned.find("[")) if i != -1]
    if not starts:
        return None

    start = min(starts)
    try:
        obj, _ = json.JSONDecoder().raw_decode(cleaned[start:])
        return obj
    except Exception:
        return None


def clean_code_text(text: str) -> str:
    text = (text or "").strip()
    text = re.sub(
        r"^(?:JSON|json|Copy|کپی|Response)\s*",
        "",
        text,
    ).strip()
    return text


def is_response_like(text: str) -> bool:
    return '"status"' in text and '"response"' in text


def rank_candidate(item: dict) -> tuple[int, int]:
    text = item["text"]
    parsed = item.get("parsed")

    if parsed is not None and is_response_like(text):
        rank = 4
    elif parsed is not None:
        rank = 3
    elif is_response_like(text):
        rank = 2
    else:
        rank = 1

    return rank, len(text)


def choose_best_candidate(items: list[dict]) -> Optional[dict]:
    best = None
    best_key = None

    for item in items:
        key = rank_candidate(item)
        if best_key is None or key > best_key:
            best = item
            best_key = key

    return best


def sha256_text(text: str) -> str:
    return sha256(text.encode("utf-8", errors="replace")).hexdigest()


# ------------------------------------------------------------
# ساخت Playwright با stealth
# ------------------------------------------------------------
@asynccontextmanager
async def playwright_session():
    if STEALTH_MODE == "auto":
        async with STEALTH_CLASS().use_async(async_playwright()) as p:
            yield p, "auto"
        return

    async with async_playwright() as p:
        yield p, STEALTH_MODE


# ------------------------------------------------------------
# ناوبری و استخراج
# ------------------------------------------------------------
async def dismiss_overlays(page) -> None:
    for name in (r"Accept", r"قبول", r"باشه", r"Close", r"بستن"):
        try:
            loc = page.get_by_role("button", name=re.compile(name, re.IGNORECASE))
            if await loc.count():
                await loc.first.click(timeout=1_200)
                await page.wait_for_timeout(250)
        except Exception:
            pass


async def collect_doc_links(page, docs_root: str) -> list[dict]:
    try:
        await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
        await page.wait_for_timeout(900)
        await page.evaluate("window.scrollTo(0, 0)")
    except Exception:
        pass

    raw_links = await page.eval_on_selector_all(
        "a[href]",
        """
        els => els.map(a => ({
            href: a.href || '',
            text: (a.innerText || a.textContent || '').trim()
        }))
        """,
    )

    docs_parsed = urlparse(docs_root)
    docs_prefix = docs_parsed.path.rstrip("/") + "/"

    links = []
    seen = set()

    for item in raw_links:
        href = item.get("href", "").strip()
        text = item.get("text", "").strip()

        if not href or href.startswith("javascript:"):
            continue

        absolute = urljoin(page.url, href)
        parsed = urlparse(absolute)

        if parsed.netloc != docs_parsed.netloc:
            continue
        if not parsed.path.startswith(docs_prefix):
            continue

        path_clean = parsed.path.rstrip("/")
        if path_clean in {
            docs_prefix.rstrip("/"),
            "/docs/instagram/data-api",
        }:
            continue

        clean_url = absolute.split("#")[0].rstrip("/") + "/"
        if clean_url in seen:
            continue

        seen.add(clean_url)
        links.append({"url": clean_url, "text": text})

    return links


def find_link_for_endpoint(endpoint: dict, links: list[dict]) -> Optional[dict]:
    name_norm = norm_text(endpoint["name"])
    action = endpoint["action"]
    slug = slugify_name(endpoint["name"])

    if not links:
        return None

    for link in links:
        if norm_text(link["text"]) == name_norm:
            return link

    contains = [
        link for link in links
        if name_norm and name_norm in norm_text(link["text"])
    ]
    if contains:
        return min(contains, key=lambda x: len(norm_text(x["text"])))

    for link in links:
        href = link["url"].lower()
        if action.lower() in href or slug in href:
            return link

    scored = sorted(
        links,
        key=lambda link: SequenceMatcher(
            None, name_norm, norm_text(link["text"])
        ).ratio(),
        reverse=True,
    )

    if scored:
        ratio = SequenceMatcher(
            None, name_norm, norm_text(scored[0]["text"])
        ).ratio()
        if ratio >= 0.80:
            return scored[0]

    return None


def build_candidate_urls(
    endpoint: dict,
    docs_root: str,
    link: Optional[dict],
) -> list[str]:
    urls = []

    if link:
        urls.append(link["url"])

    for slug in (
        slugify_name(endpoint["name"]),
        endpoint["action"].replace("_", "-"),
    ):
        if slug:
            urls.append(urljoin(docs_root, slug + "/"))

    unique = []
    seen = set()

    for url in urls:
        if url not in seen:
            seen.add(url)
            unique.append(url)

    return unique


async def navigate_to_endpoint(page, urls: list[str]) -> tuple[str, str]:
    last_error = None

    for url in urls:
        try:
            response = await page.goto(
                url,
                wait_until="domcontentloaded",
                timeout=NAV_TIMEOUT_MS,
            )

            if response and response.status >= 400:
                last_error = f"HTTP {response.status} برای {url}"
                continue

            try:
                await page.wait_for_load_state("networkidle", timeout=8_000)
            except Exception:
                pass

            await page.wait_for_timeout(900)

            title = await page.title()

            if "404" in title.lower() or "not found" in title.lower():
                last_error = f"صفحهٔ 404: {url}"
                continue

            try:
                body_start = await page.locator("body").inner_text(timeout=5_000)
                body_start = body_start[:1_200]
            except Exception:
                body_start = ""

            if "404" in body_start or "یافت نشد" in body_start:
                last_error = f"صفحهٔ یافت نشد: {url}"
                continue

            return url, title

        except Exception as exc:
            last_error = f"{type(exc).__name__}: {exc}"
            continue

    raise RuntimeError(
        "هیچ‌کدام از آدرس‌های زیر باز نشد:\n"
        + "\n".join(f"  - {u}" for u in urls)
        + f"\nآخرین خطا: {last_error}"
    )


async def expand_details(page) -> None:
    try:
        details = page.locator("details")
        count = await details.count()
        for i in range(min(count, 12)):
            item = details.nth(i)
            if await item.get_attribute("open") is None:
                summary = item.locator("summary")
                if await summary.count():
                    try:
                        await summary.first.click(timeout=1_500)
                        await page.wait_for_timeout(150)
                    except Exception:
                        pass
    except Exception:
        pass


async def find_response_button(page):
    for regex in (SPECIFIC_RESPONSE_BUTTON_RE, GENERIC_RESPONSE_BUTTON_RE):
        try:
            loc = page.get_by_role("button", name=regex)
            if await loc.count():
                return loc.last
        except Exception:
            pass

    try:
        loc = page.get_by_text(SPECIFIC_RESPONSE_BUTTON_RE, exact=False)
        if await loc.count():
            return loc.last
    except Exception:
        pass

    return None


async def click_response_button(page) -> bool:
    button = await find_response_button(page)
    if button is None:
        return False

    try:
        await button.scroll_into_view_if_needed(timeout=5_000)
    except Exception:
        pass

    try:
        await button.click(timeout=5_000)
    except Exception:
        try:
            await button.click(force=True, timeout=5_000)
        except Exception:
            return False

    await page.wait_for_timeout(POST_CLICK_WAIT_MS)
    return True


async def wait_for_response_content(page) -> None:
    try:
        await page.wait_for_function(
            """
            () => {
                const nodes = Array.from(
                    document.querySelectorAll('pre, code, textarea')
                );
                return nodes.some(n => {
                    const t = (n.value || n.innerText || n.textContent || '').trim();
                    return t.length > 40 && (
                        t.startsWith('{') ||
                        t.startsWith('[') ||
                        /"status"\\s*:/.test(t)
                    );
                });
            }
            """,
            timeout=10_000,
        )
    except Exception:
        pass


def attach_network_capture(page):
    records = []
    pending = set()

    async def record_response(response):
        try:
            request = response.request
            if request.resource_type not in {"xhr", "fetch"}:
                return
            if "/api/" not in response.url:
                return

            content_type = response.headers.get("content-type", "").lower()
            if "json" not in content_type and "text/" not in content_type:
                return

            body = await response.text()
            if not body:
                return

            records.append(
                {
                    "url": response.url,
                    "status": response.status,
                    "content_type": content_type,
                    "body": body,
                }
            )
        except Exception:
            return

    def on_response(response):
        task = asyncio.create_task(record_response(response))
        pending.add(task)
        task.add_done_callback(pending.discard)

    page.on("response", on_response)
    return records, pending


async def extract_response_from_dom(page) -> list[dict]:
    raw_candidates = await page.evaluate(
        """
        () => {
            const out = [];
            const seen = new Set();
            const nodes = document.querySelectorAll(
                'pre, code, textarea, [class*="response"], [class*="Response"]'
            );

            for (const n of nodes) {
                let text = '';
                if ('value' in n && typeof n.value === 'string') {
                    text = n.value;
                } else {
                    text = n.innerText || n.textContent || '';
                }

                text = text.trim();
                if (text.length < 2) continue;
                if (seen.has(text)) continue;

                seen.add(text);
                out.push({
                    tag: n.tagName,
                    cls: String(n.className || ''),
                    text: text
                });
            }

            return out;
        }
        """
    )

    items = []
    for candidate in raw_candidates:
        text = clean_code_text(candidate.get("text", ""))
        if not text:
            continue
        items.append(
            {
                "text": text,
                "parsed": try_parse_json(text),
                "source": "dom",
                "tag": candidate.get("tag"),
                "class": candidate.get("cls"),
            }
        )

    return items


async def extract_response(page, network_records: list[dict]):
    await wait_for_response_content(page)

    dom_items = await extract_response_from_dom(page)
    best_dom = choose_best_candidate(dom_items)

    network_items = []
    for record in network_records:
        body = (record.get("body") or "").strip()
        if not body:
            continue
        network_items.append(
            {
                "text": body,
                "parsed": try_parse_json(body),
                "source": "network",
                "url": record.get("url"),
            }
        )

    best_network = choose_best_candidate(network_items)

    ordered = [best_dom, best_network]
    for item in ordered:
        if item and rank_candidate(item)[0] == 4:
            return item["text"], item["parsed"], item["source"]

    for item in ordered:
        if item and rank_candidate(item)[0] == 2:
            return item["text"], item["parsed"], item["source"]

    for item in ordered:
        if item and rank_candidate(item)[0] >= 3:
            return item["text"], item["parsed"], item["source"]

    for item in ordered:
        if item:
            return item["text"], item["parsed"], item["source"]

    try:
        body_text = await page.locator("body").inner_text(timeout=8_000)
    except Exception:
        body_text = ""

    if body_text:
        lower = body_text.lower()
        indexes = [
            i for i in (
                lower.find("response example"),
                body_text.find("نمونه پاسخ"),
            ) if i >= 0
        ]
        start = min(indexes) if indexes else 0
        fallback = body_text[start:start + 80_000].strip()
        return fallback, try_parse_json(fallback), "body"

    return None, None, "none"


# ------------------------------------------------------------
# اجرای اصلی
# ------------------------------------------------------------
async def main():
    print("=" * 80)
    print("استخراج نمونه‌پاسخ‌های BoxAPI")
    print("Playwright + playwright-stealth")
    print(f"حالت stealth: {STEALTH_MODE}")
    print(f"حالت مرورگر: {'headless' if HEADLESS else 'headed (نمایان)'}")

    # هشدار اگر headed است اما DISPLAY وجود ندارد
    if not HEADLESS and platform.system() == "Linux":
        display = os.getenv("DISPLAY", "").strip()
        if not display:
            print(
                "\n⚠️  هشدار: DISPLAY تنظیم نشده است. "
                "مرورگر headed بدون XServer کرش می‌کند."
            )
            print(
                "   برای اجرای headed از دستور زیر استفاده کنید:\n"
                "   xvfb-run -a python main.py\n"
                "   یا متغیر HEADLESS=1 را تنظیم کنید."
            )
            print("   به طور خودکار به headless سوییچ می‌شود.\n")

    print("=" * 80)

    raw_base = input(
        "\nآدرس صفحهٔ مستندات را وارد کنید "
        f"(پیش‌فرض: {DEFAULT_DOCS_URL}):\n> "
    ).strip()

    base_url = normalize_url(raw_base or DEFAULT_DOCS_URL)
    docs_root = derive_docs_root(base_url)

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_path = OUTPUT_DIR / f"boxapi_responses_{timestamp}.json"

    print(f"\nآدرس شروع: {base_url}")
    print(f"ریشهٔ مستندات: {docs_root}")
    print(f"فایل خروجی: {output_path}")
    print(f"تعداد اندپوینت‌ها: {len(ENDPOINTS)}")
    print("-" * 80)

    results = []
    success_count = 0

    async with playwright_session() as (p, stealth_mode):
        browser = None
        context = None

        try:
            browser = await p.chromium.launch(
                headless=HEADLESS,
                args=[
                    "--disable-blink-features=AutomationControlled",
                    "--disable-dev-shm-usage",
                    "--no-sandbox",
                ],
                ignore_default_args=["--enable-automation"],
            )

            context = await browser.new_context(
                locale="fa-IR",
                timezone_id="Asia/Tehran",
                viewport={"width": 1_440, "height": 1_000},
                user_agent=USER_AGENT,
                ignore_https_errors=True,
                extra_http_headers={
                    "Accept-Language": "fa-IR,fa;q=0.9,en;q=0.8",
                },
            )

            if stealth_mode == "manual" and STEALTH_CLASS is not None:
                try:
                    await STEALTH_CLASS().apply_stealth_async(context)
                    print("Stealth به‌صورت manual روی context اعمال شد.")
                except Exception as exc:
                    print(f"هشدار stealth manual: {exc}")

            page = await context.new_page()
            page.set_default_timeout(PAGE_TIMEOUT_MS)
            page.set_default_navigation_timeout(NAV_TIMEOUT_MS)

            if stealth_mode == "legacy" and LEGACY_STEALTH_ASYNC is not None:
                await LEGACY_STEALTH_ASYNC(page)
                print("Stealth نسخهٔ قدیمی روی page اعمال شد.")

            await page.goto(
                base_url,
                wait_until="domcontentloaded",
                timeout=NAV_TIMEOUT_MS,
            )

            try:
                await page.wait_for_load_state("networkidle", timeout=10_000)
            except Exception:
                pass

            await page.wait_for_timeout(2_000)
            await dismiss_overlays(page)

            sidebar_links = await collect_doc_links(page, docs_root)
            print(f"تعداد لینک‌های مستندات پیدا‌شده: {len(sidebar_links)}")
            print("-" * 80)

            for index, endpoint in enumerate(ENDPOINTS, start=1):
                name = endpoint["name"]
                action = endpoint["action"]
                category = endpoint["category"]

                print(
                    f"\n[{index:02d}/{len(ENDPOINTS)}] "
                    f"{category} | {name} | {action}"
                )

                started = time.monotonic()
                record = {
                    "index": index,
                    "category": category,
                    "name": name,
                    "action": action,
                    "api_test_url": endpoint["test"],
                    "status": "pending",
                    "docs_url": None,
                    "page_title": None,
                    "page_heading": None,
                    "clicked_response_button": False,
                    "response_source": None,
                    "response_length": 0,
                    "response_sha256": None,
                    "response_raw": None,
                    "response_parsed": None,
                    "network_responses": [],
                    "error": None,
                    "elapsed_seconds": None,
                }

                try:
                    link = find_link_for_endpoint(endpoint, sidebar_links)
                    candidate_urls = build_candidate_urls(
                        endpoint, docs_root, link
                    )

                    docs_url, page_title = await navigate_to_endpoint(
                        page, candidate_urls
                    )

                    record["docs_url"] = docs_url
                    record["page_title"] = page_title

                    try:
                        heading = await page.locator("h1").first.inner_text(
                            timeout=5_000
                        )
                    except Exception:
                        heading = ""

                    record["page_heading"] = heading.strip()

                    await dismiss_overlays(page)
                    await expand_details(page)

                    network_records, pending_tasks = attach_network_capture(page)

                    clicked = await click_response_button(page)
                    record["clicked_response_button"] = clicked

                    if pending_tasks:
                        try:
                            await asyncio.wait(
                                list(pending_tasks),
                                timeout=NETWORK_WAIT_SECONDS,
                            )
                        except Exception:
                            pass

                    raw, parsed, source = await extract_response(
                        page, network_records
                    )

                    record["network_responses"] = network_records

                    if raw:
                        record["status"] = "success"
                        record["response_source"] = source
                        record["response_raw"] = raw
                        record["response_length"] = len(raw)
                        record["response_sha256"] = sha256_text(raw)
                        record["response_parsed"] = parsed

                        success_count += 1

                        print(
                            f"   ✅ موفق | منبع: {source} | "
                            f"طول: {len(raw):,} کاراکتر"
                        )

                        if PRINT_FULL_RESPONSES:
                            print("-" * 80)
                            print(raw)
                            print("-" * 80)
                    else:
                        record["status"] = "no_response"
                        print("   ⚠️ خروجی‌ای پیدا نشد.")

                        try:
                            body_text = await page.locator("body").inner_text(
                                timeout=5_000
                            )
                            record["debug_page_text"] = body_text[:8_000]
                        except Exception:
                            pass

                except Exception as exc:
                    record["status"] = "error"
                    record["error"] = f"{type(exc).__name__}: {exc}"
                    print(f"   ❌ خطا: {record['error']}")

                    try:
                        screenshot_path = (
                            OUTPUT_DIR / f"error_{index:02d}_{action}.png"
                        )
                        await page.screenshot(
                            path=str(screenshot_path),
                            full_page=False,
                        )
                        record["error_screenshot"] = str(screenshot_path)
                    except Exception:
                        pass

                finally:
                    record["elapsed_seconds"] = round(
                        time.monotonic() - started, 2
                    )
                    results.append(record)

            payload = {
                "metadata": {
                    "generated_at": datetime.now(timezone.utc)
                    .astimezone()
                    .isoformat(timespec="seconds"),
                    "base_url": base_url,
                    "docs_root": docs_root,
                    "stealth_mode": stealth_mode,
                    "headless": HEADLESS,
                    "total_endpoints": len(ENDPOINTS),
                    "success_count": success_count,
                    "failed_count": len(ENDPOINTS) - success_count,
                },
                "endpoints": results,
            }

            with output_path.open(
                "w", encoding="utf-8", errors="replace"
            ) as file:
                json.dump(
                    payload,
                    file,
                    ensure_ascii=False,
                    indent=2,
                )

            print("\n" + "=" * 80)
            print("پایان عملیات")
            print(f"موفق: {success_count} از {len(ENDPOINTS)}")
            print(f"فایل ذخیره‌شده: {output_path}")
            print("=" * 80)

        finally:
            if context is not None:
                try:
                    await context.close()
                except Exception:
                    pass

            if browser is not None:
                try:
                    await browser.close()
                except Exception:
                    pass


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n\nعملیات توسط کاربر متوقف شد.")
    except Exception as exc:
        print(f"\nخطای کلی: {type(exc).__name__}: {exc}")
        raise
