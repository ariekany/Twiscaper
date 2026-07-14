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

## ⚠️ Security & Best Practices (Penting!)

Untuk menghindari deteksi bot dan menjaga keamanan akun Anda, harap ikuti panduan berikut saat menggunakan tool ini:

1. **Rekomendasi Browser & Keamanan Profil:**
* Sangat direkomendasikan untuk menggunakan **Brave Browser** guna penyamaran dan pemrosesan yang lebih optimal.
* Setelah Anda melakukan login ke Twitter/X via script/browser otomatis, *User Profile* dan sesi login Anda **hanya akan disimpan secara lokal di komputer Anda** dengan aman. Data kredensial tidak pernah dikirim ke server luar manapun.


2. **Gunakan Akun Khusus (Akun Tumbal):**
* **Jangan pernah gunakan akun utama Anda** untuk proses scraping.
* Gunakan akun khusus *scraping* atau akun sekunder (akun tumbal). Jika sistem proteksi Twitter/X mendeteksi aktivitas mencurigakan dan melakukan *suspend*, akun utama Anda akan tetap aman.


3. **Batasi Penggunaan Parameter Limit:**
* Jangan menggunakan angka `--limit` yang terlalu tinggi dalam satu perintah agar tidak memicu proteksi anti-bot milik Twitter/X.
* **Rekomendasi aman:** Batasi maksimal **40 replies/tweets per sesi**. Berikan jeda waktu (delay) sebelum menjalankan sesi berikutnya.



---

## 📝 Notes

* **Placeholders:** Pastikan untuk mengganti contoh URL (`[https://x.com/username/](https://x.com/username/)...`) atau kata kunci pencarian (`"banjir aceh"`) dengan data riil yang ingin Anda ambil.
* **Best Effort vs Reliable:** Flag `--reply-sort` pada URL tertentu bekerja secara *best-effort* karena keterbatasan algoritma X, sedangkan flag `--filter top` yang dipadukan dengan `--query` memiliki akurasi yang lebih andal.