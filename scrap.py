# /// script
# requires-python = ">=3.11"
# dependencies = [
#     "playwright",
#     "playwright-stealth",
# ]
# ///
"""
Scraper pencarian X (Twitter) pakai Playwright.

CATATAN PENTING:
Scraping X tanpa izin tertulis melanggar Terms of Service mereka, dan X
pernah menggugat pihak yang melakukan scraping (termasuk lewat akun yang
sudah login, seperti skrip ini). Pakai untuk riset pribadi/skala kecil,
dengan akun yang siap kamu terima risikonya kalau kena suspend, dan jangan
jalankan agresif (limit besar, banyak query berturut-turut, dsb).

Alternatif resmi: X API (berbayar, tapi tidak melanggar ToS).

Cara pakai:
    # sekali jalan, berhenti setelah dapat 30 tweet
    uv run scrape_x.py --query "teknologi" --limit 30 --once

    # mode kontinu (default): scrape 30, jeda acak, scrape 30 baru lagi, dst,
    # sampai dihentikan manual dengan Ctrl+C. Data terus ditambahkan (append)
    # ke file CSV yang sama, tidak menghapus data lama - aman dijalankan ulang.
    uv run scrape_x.py --url "https://x.com/username/status/123..." --limit 30 --reply-sort top

    # ganti target? Ctrl+C dulu untuk stop, baru jalankan lagi dengan --url/--query baru
    uv run scrape_x.py --query "banjir aceh" --filter top --limit 20 --cycle-pause-min 90 --cycle-pause-max 240
"""

import argparse
import asyncio
import csv
import json
import logging
import os
import random
import re
import sys
import time
import urllib.parse
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from playwright.async_api import Page, BrowserContext, async_playwright

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("x_scraper")


# ---------------------------------------------------------------------------
# Konfigurasi
# ---------------------------------------------------------------------------
@dataclass
class ScraperConfig:
    query: str
    limit: int = 20
    search_filter: str = "live"          # "live" atau "top"
    output_csv: str = "hasil_scrape_x.csv"
    also_json: bool = False
    headless: bool = False
    browser_path: Optional[str] = None
    profile_dir: str = "brave_profile"   # folder profil persisten (nyimpen sesi login)
    max_idle_scrolls: int = 10
    max_total_scrolls: int = 200         # jaring pengaman biar tidak infinite loop
    min_delay: float = 1.5
    max_delay: float = 3.5
    exclude_retweets: bool = False
    stealth: bool = False
    tweet_url: Optional[str] = None      # kalau diisi, --query diabaikan
    reply_sort: Optional[str] = None     # "top" | "latest" | "liked" | None (best-effort, UI dropdown)
    once: bool = False                   # True = 1 siklus lalu keluar (perilaku lama)
    cycle_pause_min: float = 180.0       # jeda minimum antar siklus, detik (default 3 menit)
    cycle_pause_max: float = 420.0       # jeda maksimum antar siklus, detik (default 7 menit)
    max_cycles: int = 0                  # 0 = tanpa batas, jalan terus sampai Ctrl+C


CSV_FIELDS = [
    "id", "name", "handle", "date", "text", "permalink",
    "is_retweet", "reply_count", "retweet_count", "like_count",
    "view_count", "media_urls",
]


# ---------------------------------------------------------------------------
# Util kecil
# ---------------------------------------------------------------------------
def find_browser_executable(custom_path: Optional[str]) -> Optional[str]:
    """Cari executable Brave. None -> fallback ke Chromium bawaan Playwright."""
    if custom_path:
        return custom_path if Path(custom_path).exists() else None

    candidates = [
        r"C:\Program Files\BraveSoftware\Brave-Browser\Application\brave.exe",
        r"C:\Program Files (x86)\BraveSoftware\Brave-Browser\Application\brave.exe",
        str(Path.home() / "AppData/Local/BraveSoftware/Brave-Browser/Application/brave.exe"),
        # jaga-jaga kalau dijalankan di Linux/Mac
        "/usr/bin/brave-browser",
        "/Applications/Brave Browser.app/Contents/MacOS/Brave Browser",
    ]
    for c in candidates:
        if Path(c).exists():
            return c
    return None


def parse_count(text: str) -> Optional[int]:
    """'1.2K' -> 1200, '3M' -> 3000000, '45' -> 45."""
    if not text:
        return None
    text = text.strip().lower().replace(",", "")
    try:
        if text.endswith("k"):
            return int(float(text[:-1]) * 1_000)
        if text.endswith("m"):
            return int(float(text[:-1]) * 1_000_000)
        if text.endswith("b"):
            return int(float(text[:-1]) * 1_000_000_000)
        return int(float(text))
    except ValueError:
        return None


_METRIC_RE = re.compile(r"([\d.,]+\s?[kKmMbB]?)\s+(repl(?:y|ies)|repost|retweet|like|view)")


def parse_metrics_from_aria(aria_label: str) -> dict:
    """
    X biasanya nulis aria-label di grup tombol aksi seperti:
    '12 replies, 34 reposts, 56 likes, 7890 views'.
    Kalau X ubah formatnya, fungsi ini tinggal disesuaikan regex-nya.
    """
    metrics = {"reply_count": None, "retweet_count": None, "like_count": None, "view_count": None}
    for value, kind in _METRIC_RE.findall(aria_label or ""):
        n = parse_count(value.replace(" ", ""))
        kind = kind.lower()
        if kind.startswith("repl"):
            metrics["reply_count"] = n
        elif kind in ("repost", "retweet"):
            metrics["retweet_count"] = n
        elif kind == "like":
            metrics["like_count"] = n
        elif kind == "view":
            metrics["view_count"] = n
    return metrics


def load_existing_ids(path: str) -> set:
    """Baca id yang sudah pernah tersimpan (dari sesi-sesi sebelumnya) supaya
    tidak menimpa/menduplikasi data lama."""
    ids = set()
    if os.path.exists(path) and os.path.getsize(path) > 0:
        try:
            with open(path, "r", encoding="utf-8-sig", newline="") as f:
                for row in csv.DictReader(f):
                    if row.get("id"):
                        ids.add(row["id"])
        except Exception as e:
            log.warning(f"[!] Gagal membaca data lama dari {path}: {e}")
    return ids


class IncrementalCsvWriter:
    """Nulis CSV baris-per-baris & flush terus (append, bukan menimpa), jadi:
    - kalau proses crash/dihentikan di tengah jalan, data yang sudah diambil tidak hilang.
    - sesi baru (misalnya setelah Ctrl+C lalu jalan lagi) menyambung ke file yang sama,
      tidak menghapus data lama."""

    def __init__(self, path: str, fieldnames: list):
        file_has_data = os.path.exists(path) and os.path.getsize(path) > 0
        self._file = open(path, "a", newline="", encoding="utf-8-sig")
        self._writer = csv.DictWriter(self._file, fieldnames=fieldnames)
        if not file_has_data:
            self._writer.writeheader()
            self._file.flush()

    def write_rows(self, rows: list):
        for row in rows:
            self._writer.writerow(row)
        self._file.flush()

    def close(self):
        self._file.close()


# ---------------------------------------------------------------------------
# Ekstraksi data dari satu elemen tweet
# ---------------------------------------------------------------------------
async def extract_tweet(element) -> Optional[dict]:
    try:
        time_elem = await element.query_selector("time")
        link_elem = await element.query_selector('a[href*="/status/"]')
        if not (time_elem and link_elem):
            return None

        href = await link_elem.get_attribute("href") or ""
        tweet_id = href.split("/status/")[-1].split("?")[0] if "/status/" in href else None
        if not tweet_id:
            return None
        permalink = href if href.startswith("http") else f"https://x.com{href}"
        date_str = await time_elem.get_attribute("datetime") or "N/A"

        user_elem = await element.query_selector('[data-testid="User-Name"]')
        user_text = await user_elem.inner_text() if user_elem else ""
        lines = [l for l in user_text.split("\n") if l.strip()]
        name = lines[0] if len(lines) > 0 else "N/A"
        handle = lines[1] if len(lines) > 1 else "N/A"

        text_elem = await element.query_selector('[data-testid="tweetText"]')
        text = await text_elem.inner_text() if text_elem else ""
        text_cleaned = text.replace("\n", " ").strip()

        # retweet/repost?
        is_rt = False
        social_ctx = await element.query_selector('[data-testid="socialContext"]')
        if social_ctx:
            ctx_text = (await social_ctx.inner_text() or "").lower()
            is_rt = "repost" in ctx_text or "retweet" in ctx_text

        # metrik (reply/retweet/like/view)
        metrics = {"reply_count": None, "retweet_count": None, "like_count": None, "view_count": None}
        group = await element.query_selector('[role="group"][aria-label]')
        if group:
            aria = await group.get_attribute("aria-label") or ""
            metrics = parse_metrics_from_aria(aria)

        # media (gambar)
        media_urls = []
        imgs = await element.query_selector_all('[data-testid="tweetPhoto"] img')
        for img in imgs:
            src = await img.get_attribute("src")
            if src:
                media_urls.append(src)

        return {
            "id": tweet_id,
            "name": name,
            "handle": handle,
            "date": date_str,
            "text": text_cleaned,
            "permalink": permalink,
            "is_retweet": is_rt,
            "reply_count": metrics["reply_count"],
            "retweet_count": metrics["retweet_count"],
            "like_count": metrics["like_count"],
            "view_count": metrics["view_count"],
            "media_urls": "; ".join(media_urls),
        }
    except Exception as e:
        log.debug(f"Gagal ekstrak satu elemen tweet: {e}")
        return None


async def try_set_reply_sort(page: Page, desired: str):
    """
    Coba ubah urutan balasan di halaman POST TUNGGAL (bukan search).
    X mengatur ini lewat dropdown UI, bukan parameter URL, dan labelnya
    pernah berubah-ubah ("Top", "Relevant", dsb) tergantung versi/wilayah X,
    serta TIDAK persist antar tweet - harus diklik ulang tiap buka post baru.

    Best-effort: kalau tombol/opsi tidak ketemu (karena X ubah UI-nya),
    cuma di-log sebagai warning, scraping tetap lanjut dengan urutan default.
    """
    label_candidates = {
        "top": ["Top", "Most relevant", "Relevant"],
        "latest": ["Latest", "Most recent", "Recent"],
        "liked": ["Most liked", "Liked"],
    }.get(desired.lower(), [])
    if not label_candidates:
        return

    try:
        pattern = re.compile("|".join(label_candidates + ["Latest", "Top", "Relevant", "Liked"]), re.IGNORECASE)
        sort_button = page.locator('[role="button"]', has_text=pattern).first
        if await sort_button.count() == 0:
            log.warning("[!] Tombol sortir balasan tidak ketemu - mungkin UI X berubah, atau post ini "
                        "tidak menampilkan opsi sortir. Lanjut dengan urutan default.")
            return

        await sort_button.click()
        await page.wait_for_timeout(600)

        for label in label_candidates:
            option = page.get_by_role("menuitem", name=re.compile(label, re.IGNORECASE))
            if await option.count() > 0:
                await option.first.click()
                log.info(f"[*] Urutan balasan diset ke '{label}'.")
                await page.wait_for_timeout(800)
                return

        log.warning(f"[!] Opsi sortir '{desired}' tidak ketemu di menu dropdown. Cek manual apakah "
                    f"label tombolnya berubah, lalu sesuaikan try_set_reply_sort().")
    except Exception as e:
        log.warning(f"[!] Gagal mengubah urutan balasan ({e}). Lanjut dengan urutan default.")


async def check_for_blockers(page: Page) -> Optional[str]:
    """Deteksi tanda-tanda rate limit / halaman error / butuh verifikasi."""
    try:
        body_text = (await page.inner_text("body"))[:3000].lower()
    except Exception:
        return None
    if "something went wrong" in body_text and "try reloading" in body_text:
        return "error_page"
    if "confirm your identity" in body_text or "unusual login activity" in body_text:
        return "challenge"
    if "rate limit exceeded" in body_text:
        return "rate_limited"
    return None


async def human_scroll(page: Page, min_delay: float, max_delay: float):
    """Scroll dengan jarak & jeda acak, sesekali sedikit scroll balik ke atas,
    supaya polanya tidak seragam seperti bot yang scroll dengan interval tetap."""
    amount = random.randint(600, 1400)
    await page.mouse.wheel(0, amount)
    await page.wait_for_timeout(int(random.uniform(min_delay, max_delay) * 1000))
    if random.random() < 0.15:
        await page.mouse.wheel(0, -random.randint(100, 300))
        await page.wait_for_timeout(int(random.uniform(300, 800)))


# ---------------------------------------------------------------------------
# Alur utama
# ---------------------------------------------------------------------------
async def run_scraper(config: ScraperConfig) -> list:
    scraped_ids: set = load_existing_ids(config.output_csv)
    if scraped_ids:
        log.info(f"[*] Ditemukan {len(scraped_ids)} tweet lama di {config.output_csv} - "
                 f"disambung, bukan ditimpa.")
    tweets_data: list = []  # tweet baru yang didapat proses (sesi) ini saja

    browser_path = find_browser_executable(config.browser_path)
    if config.browser_path and not browser_path:
        log.warning(f"[!] Path browser '{config.browser_path}' tidak ditemukan, pakai deteksi otomatis...")
    if not browser_path:
        log.info("[*] Brave tidak ditemukan di lokasi umum, pakai Chromium bawaan Playwright.")
    else:
        log.info(f"[*] Menggunakan browser: {browser_path}")

    async with async_playwright() as p:
        launch_kwargs = dict(
            user_data_dir=config.profile_dir,
            headless=config.headless,
            viewport={"width": 1366, "height": 768},
            locale="id-ID",
            timezone_id="Asia/Jakarta",
            args=["--disable-blink-features=AutomationControlled"],
        )
        if browser_path:
            launch_kwargs["executable_path"] = browser_path

        context: BrowserContext = await p.chromium.launch_persistent_context(**launch_kwargs)

        if config.stealth:
            try:
                from playwright_stealth import Stealth
                await Stealth().apply_stealth_async(context)
                log.info("[*] Stealth patches diaktifkan (playwright-stealth) - hanya menyamarkan "
                         "sinyal fingerprint dasar, bukan proteksi penuh.")
            except ImportError:
                log.warning("[!] playwright-stealth belum terinstall, lanjut tanpa stealth mode.")

        page = context.pages[0] if context.pages else await context.new_page()

        if config.tweet_url:
            # Mode: post spesifik (mengabaikan --query sepenuhnya)
            url = config.tweet_url if config.tweet_url.startswith("http") \
                else f"https://x.com/i/web/status/{config.tweet_url}"
        else:
            encoded_query = urllib.parse.quote_plus(config.query)
            filter_param = "&f=live" if config.search_filter == "live" else ""
            url = f"https://x.com/search?q={encoded_query}{filter_param}"

        writer = IncrementalCsvWriter(config.output_csv, CSV_FIELDS)
        cycle_num = 0
        overall_start = time.perf_counter()

        # Untuk mengganti target (--query / --url), hentikan proses ini dengan Ctrl+C
        # lalu jalankan lagi dengan argumen baru - data lama di --output tidak akan hilang.
        try:
            while True:
                cycle_num += 1
                if config.max_cycles and cycle_num > config.max_cycles:
                    log.info(f"[*] Mencapai batas --max-cycles ({config.max_cycles}), berhenti.")
                    break
                log.info(f"\n===== Siklus #{cycle_num}: {url} =====")

                try:
                    await page.goto(url, timeout=30000)
                except Exception as e:
                    log.error(f"[!] Gagal membuka halaman: {e}. Coba lagi dalam 30 detik...")
                    await asyncio.sleep(30)
                    continue

                if cycle_num == 1:
                    log.info("[!] Kalau belum login, silakan login manual di jendela browser yang terbuka.")
                log.info("[*] Menunggu tweet pertama muncul...")

                try:
                    await page.wait_for_selector('[data-testid="tweet"]', timeout=30000)
                except Exception:
                    log.error(
                        "[!] Tidak ada tweet yang termuat dalam 30 detik. Kemungkinan: belum login, "
                        "tidak ada hasil baru, atau X menampilkan halaman verifikasi/rate-limit."
                    )
                    blocker = await check_for_blockers(page)
                    if blocker:
                        log.error(f"[!] Terdeteksi kondisi: {blocker}")
                    log.info("[*] Menunggu 60 detik, lalu coba siklus berikutnya...")
                    await asyncio.sleep(60)
                    continue

                await page.wait_for_timeout(int(random.uniform(1500, 3000)))

                if config.tweet_url and config.reply_sort:
                    await try_set_reply_sort(page, config.reply_sort)

                idle_counter = 0
                total_scrolls = 0
                cycle_new = 0
                cycle_start = time.perf_counter()
                stop_reason = "target tercapai"

                while True:
                    if cycle_new >= config.limit:
                        stop_reason = f"target {config.limit} tweet baru tercapai"
                        break
                    if idle_counter >= config.max_idle_scrolls:
                        stop_reason = (f"tidak ada tweet baru setelah {config.max_idle_scrolls}x scroll "
                                       f"(feed kemungkinan sudah habis untuk saat ini)")
                        break
                    if total_scrolls >= config.max_total_scrolls:
                        stop_reason = f"mencapai batas keamanan {config.max_total_scrolls}x scroll"
                        break

                    elements = await page.query_selector_all('[data-testid="tweet"]')
                    new_rows = []

                    for element in elements:
                        if cycle_new >= config.limit:
                            break
                        parsed = await extract_tweet(element)
                        if not parsed or parsed["id"] in scraped_ids:
                            continue
                        if config.exclude_retweets and parsed["is_retweet"]:
                            scraped_ids.add(parsed["id"])  # tetap tandai biar tidak dicek ulang
                            continue

                        scraped_ids.add(parsed["id"])
                        tweets_data.append(parsed)
                        new_rows.append(parsed)
                        cycle_new += 1
                        log.info(f"[siklus {cycle_num} | {cycle_new}/{config.limit}] "
                                 f"@{parsed['handle']}: {parsed['text'][:60]}...")

                    if new_rows:
                        writer.write_rows(new_rows)
                        idle_counter = 0
                    else:
                        idle_counter += 1
                        log.info(f"[*] Tidak ada tweet baru di scroll ini "
                                 f"({idle_counter}/{config.max_idle_scrolls})...")

                    if cycle_new >= config.limit:
                        continue  # loop top akan menangkap ini dan set stop_reason

                    total_scrolls += 1
                    if total_scrolls % 5 == 0:
                        blocker = await check_for_blockers(page)
                        if blocker == "rate_limited":
                            stop_reason = "terdeteksi rate limit dari X - berhenti lebih awal untuk aman"
                            break
                        if blocker == "challenge":
                            log.warning("[!] X meminta verifikasi identitas di jendela browser. "
                                        "Browser TIDAK akan ditutup otomatis.")
                            await asyncio.to_thread(
                                input,
                                "    Selesaikan verifikasi di jendela browser, lalu tekan ENTER di sini "
                                "untuk lanjut scraping (Ctrl+C untuk berhenti total)... ",
                            )
                            log.info("[*] Melanjutkan scraping...")
                            continue
                        if blocker == "error_page":
                            log.warning("[!] Halaman menampilkan error. Mencoba reload...")
                            await page.reload()
                            await page.wait_for_timeout(3000)

                    await human_scroll(page, config.min_delay, config.max_delay)

                cycle_elapsed = time.perf_counter() - cycle_start
                log.info(f"[*] Siklus #{cycle_num} berhenti karena: {stop_reason}")
                log.info(f"[+] +{cycle_new} tweet baru siklus ini ({cycle_elapsed:.1f} detik). "
                         f"Total sesi ini: {len(tweets_data)} tweet baru, {len(scraped_ids)} id unik "
                         f"sepanjang waktu, tersimpan di {config.output_csv}.")

                if config.once:
                    break

                pause_s = random.uniform(config.cycle_pause_min, config.cycle_pause_max)
                if "rate limit" in stop_reason.lower():
                    pause_s *= 3  # kena rate limit -> mundur lebih jauh dari biasanya, bukan cuma jeda standar
                    log.warning(f"[!] Karena kena rate limit, jeda dilipatgandakan jadi {pause_s / 60:.1f} menit.")
                log.info(f"[*] Jeda {pause_s / 60:.1f} menit sebelum siklus berikutnya "
                         f"(Ctrl+C untuk berhenti & tutup browser)...")
                await asyncio.sleep(pause_s)

        except KeyboardInterrupt:
            log.warning("[!] Dihentikan manual (Ctrl+C).")
        except Exception:
            log.exception("[!] Error tak terduga. Data yang sudah terkumpul tetap tersimpan.")
        finally:
            writer.close()

        overall_elapsed = time.perf_counter() - overall_start
        log.info(f"[+] Selesai. Total {len(tweets_data)} tweet baru ditambahkan sesi ini ke "
                 f"{config.output_csv} ({overall_elapsed / 60:.1f} menit, "
                 f"{len(scraped_ids)} id unik sepanjang waktu).")

        try:
            await context.close()
        except Exception:
            pass  # sudah tertutup (mis. browser crash/ditutup sistem) - aman diabaikan

        if config.also_json:
            json_path = str(Path(config.output_csv).with_suffix(".json"))
            try:
                with open(config.output_csv, "r", encoding="utf-8-sig", newline="") as f:
                    all_rows = list(csv.DictReader(f))
                with open(json_path, "w", encoding="utf-8") as f:
                    json.dump(all_rows, f, ensure_ascii=False, indent=2)
                log.info(f"[+] Seluruh data ({len(all_rows)} baris, semua sesi) "
                         f"juga diekspor sebagai {json_path}")
            except Exception as e:
                log.warning(f"[!] Gagal membuat export JSON: {e}")

    return tweets_data


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def parse_args() -> ScraperConfig:
    parser = argparse.ArgumentParser(
        description="Scraper pencarian X (Twitter) pakai Playwright.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument("--query", default="teknologi", help="Kata kunci pencarian (default: 'teknologi')")
    parser.add_argument("--url", dest="tweet_url", default=None,
                        help="Link (atau ID) postingan spesifik untuk diambil balasannya - mengabaikan --query")
    parser.add_argument("--reply-sort", choices=["top", "latest", "liked"], default=None,
                        help="Urutan balasan saat pakai --url (best-effort, klik dropdown UI X, lihat catatan skrip)")
    parser.add_argument("--limit", type=int, default=20, help="Jumlah tweet yang diambil (default: 20)")
    parser.add_argument("--filter", dest="search_filter", choices=["live", "top"], default="live",
                        help="Tab pencarian: 'live' (terbaru) atau 'top' (teratas) - hanya berlaku untuk --query")
    parser.add_argument("--output", dest="output_csv", default="hasil_scrape_x.csv", help="Nama file CSV output")
    parser.add_argument("--json", dest="also_json", action="store_true", help="Simpan juga sebagai .json")
    parser.add_argument("--headless", action="store_true",
                        help="Jalankan tanpa tampilan browser (butuh sesi login yang sudah tersimpan)")
    parser.add_argument("--browser-path", default=None, help="Path custom ke executable browser Chromium-based")
    parser.add_argument("--profile-dir", default="brave_profile",
                        help="Folder profil persisten untuk menyimpan sesi login")
    parser.add_argument("--max-idle-scrolls", type=int, default=10,
                        help="Berhenti setelah sekian kali scroll tanpa tweet baru")
    parser.add_argument("--min-delay", type=float, default=1.5, help="Jeda minimum antar scroll (detik)")
    parser.add_argument("--max-delay", type=float, default=3.5, help="Jeda maksimum antar scroll (detik)")
    parser.add_argument("--exclude-retweets", action="store_true", help="Lewati tweet yang merupakan repost")
    parser.add_argument("--stealth", action="store_true",
                        help="Aktifkan playwright-stealth (patch fingerprint dasar, opsional)")
    parser.add_argument("--once", action="store_true",
                        help="Berhenti & tutup browser setelah 1 siklus (perilaku lama). Default: jalan terus "
                             "(kontinu) sampai Ctrl+C.")
    parser.add_argument("--cycle-pause-min", type=float, default=180.0,
                        help="Jeda MINIMUM antar siklus, dalam detik (default: 180 = 3 menit)")
    parser.add_argument("--cycle-pause-max", type=float, default=420.0,
                        help="Jeda MAKSIMUM antar siklus, dalam detik (default: 420 = 7 menit)")
    parser.add_argument("--max-cycles", type=int, default=0,
                        help="Batas jumlah siklus untuk keperluan tes (default: 0 = tanpa batas)")
    args = parser.parse_args()

    return ScraperConfig(
        query=args.query,
        limit=args.limit,
        search_filter=args.search_filter,
        output_csv=args.output_csv,
        also_json=args.also_json,
        headless=args.headless,
        browser_path=args.browser_path,
        profile_dir=args.profile_dir,
        max_idle_scrolls=args.max_idle_scrolls,
        min_delay=args.min_delay,
        max_delay=args.max_delay,
        exclude_retweets=args.exclude_retweets,
        stealth=args.stealth,
        tweet_url=args.tweet_url,
        reply_sort=args.reply_sort,
        once=args.once,
        cycle_pause_min=args.cycle_pause_min,
        cycle_pause_max=args.cycle_pause_max,
        max_cycles=args.max_cycles,
    )


if __name__ == "__main__":
    cfg = parse_args()
    print("=== X SEARCH SCRAPER ===")
    if cfg.tweet_url:
        print(f"Mode           : postingan spesifik ({cfg.tweet_url})")
        print(f"Reply sort     : {cfg.reply_sort or 'default (tidak diubah)'}")
    else:
        print(f"Query          : {cfg.query}")
        print(f"Filter         : {cfg.search_filter}")
    print(f"Limit          : {cfg.limit}")
    print(f"Output CSV     : {cfg.output_csv}")
    print(f"Profile dir    : {cfg.profile_dir} (sesi login akan tersimpan di sini)")
    print(f"Headless       : {cfg.headless}")
    print(f"Stealth        : {cfg.stealth}")
    print("")
    try:
        asyncio.run(run_scraper(cfg))
    except KeyboardInterrupt:
        print("\n[!] Dihentikan oleh pengguna.")
        sys.exit(1)