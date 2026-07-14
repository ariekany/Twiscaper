---

# 🐦 Twitter (X) Comment Scraper

A powerful yet simple command-line tool to scrape comments, replies, and search results from Twitter/X posts using Python and `uv`.

---

## ✨ Features

* **Targeted Scraping:** Extract replies directly from a specific tweet URL.
* **Search Queries:** Scrape tweets and replies based on specific keywords or hashtags.
* **Flexible Sorting:** Filter results by "top" interactions or use best-effort reply sorting.
* **Configurable Limits:** Control exactly how many replies you want to retrieve.

---

## 🛠️ Requirements

Before running the scraper, ensure you have the following installed:

* **Python 3.11+**
* **`uv`** (A fast Python package installer and resolver)
* *If you don't have it, install it via:* `pip install uv` or `curl -LsSf [https://astral.sh/uv/install.sh](https://astral.sh/uv/install.sh) | sh`



---

## 🚀 Getting Started & Usage

### 1. Installation

Clone this repository and navigate to the project directory:

```bash
git clone https://github.com/your-username/twitter-comment-scraper.git
cd twitter-comment-scraper

```

### 2. Running the Scraper

You can run the script instantly using `uv run`. It will automatically handle the environment and dependencies for you.

#### A. Scrape Replies from a Specific Post

Extract a specific number of replies from a tweet:

```bash
uv run scrape_x.py --url "https://x.com/username/status/1234567890123456789" --limit 30

```

#### B. Scrape and Sort Replies by "Top"

Try to prioritize top replies from a specific post (best-effort):

```bash
uv run scrape_x.py --url "https://x.com/username/status/1234567890123456789" --reply-sort top

```

#### C. Search Tweets by Keywords (Reliable Top Sort)

Search for a specific topic and get the top-performing tweets/replies:

```bash
uv run scrape_x.py --query "banjir aceh" --filter top

```

---

## ⚙️ CLI Arguments Reference

| Flag | Type | Description | Default / Example |
| --- | --- | --- | --- |
| `--url` | `string` | The full URL of the Twitter/X post you want to scrape. | `"[https://x.com/.../status/](https://x.com/.../status/)..."` |
| `--query` | `string` | Search keyword or phrase to look up. | `"banjir aceh"` |
| `--limit` | `integer` | Maximum number of replies/tweets to retrieve. | `30` |
| `--reply-sort` | `string` | Sort order for post replies (`top`, etc. - *best effort*). | `top` |
| `--filter` | `string` | Search filter option (`top` - *reliable*). | `top` |

---

## ⚠️ Security & Best Practices

To prevent bot detection and safeguard your account, please adhere to the following guidelines when using this tool:

1. **Brave Browser Recommendation & Ad-Blocking:**
* It is highly recommended to use **Brave Browser** as your browser executable. Brave's built-in ad-shield natively blocks promoted posts and advertisements, **preventing the script from accidentally scraping ads** as legitimate replies.
* After logging into Twitter/X via the automated browser session, your user profile and active session cookies are **safely stored only on your local machine**. No credentials or data are ever transmitted to third-party servers.


2. **Use a Dedicated or Dummy Account:**
* **Do not use your primary Twitter/X account** for scraping.
* Always use a dedicated scraping/dummy account. If Twitter's automated systems flag the scraping behavior and suspend the account, your main account remains completely unaffected.


3. **Keep Limit Parameters Low:**
* Avoid using excessively high numbers for the `--limit` flag in a single run, as this mimics unnatural, bot-like activity.
* **Recommended Limit:** Keep it to a maximum of **40 replies/tweets per session**, and introduce generous delay intervals between consecutive runs.



---

## 📝 Notes

* **Placeholders:** Make sure to replace the example URL (`[https://x.com/username/](https://x.com/username/)...`) or query values (`"banjir aceh"`) with the actual data you want to scrape.
* **Best Effort vs Reliable:** The `--reply-sort` flag for specific URLs operates on a *best-effort* basis due to X's dynamic layout, whereas the `--filter top` flag used alongside `--query` is highly reliable.