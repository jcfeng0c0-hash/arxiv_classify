# arxiv_classify v2.0.0

Automated arXiv paper classification, translation, and structured analysis system with a Flask-based WebUI.

---

## Table of Contents

1. [Project Overview](#project-overview)
2. [Architecture](#architecture)
3. [Quick Start](#quick-start)
4. [Configuration: config.py](#configuration-configpy)
5. [Research Interest & Important Authors](#research-interest--important-authors)
6. [WebUI Features](#webui-features)
7. [Mobile Access](#mobile-access)
8. [Module Reference](#module-reference)

---

## Project Overview

This tool automatically:

- Fetches the daily arXiv mailing list from QQ Mail via IMAP
- Parses paper metadata (title, authors, abstract, arXiv ID)
- Classifies papers as **interested / irrelevant** based on your research interests using DeepSeek or local Ollama
- Translates abstracts to Chinese
- Extracts structured analysis: research content, methods, discussion, and conclusion
- Stores everything in a local SQLite database
- Provides a web-based paper browser (Flask)
- Optionally pushes daily summaries to WeChat Public Account

---

## Architecture

```
arrow_classify-2.0.0-public/
├── __main__.py            # CLI entry: fetch email → parse → classify → store → send
├── webui.py               # Flask web app (port 5000)
├── migrate_db.py          # Database migration script
├── run_webui.sh           # Simple WebUI launcher
├── start_webui.sh         # WebUI launcher with LAN IP hints
├── requirements.txt       # Python dependencies
├── email_list.txt         # Email receivers (one per line)
├── src/
│   ├── config.py          # All API keys and credentials (edit this first)
│   ├── models.py          # SQLAlchemy Paper model + DB session
│   ├── model_inference.py # DeepSeek/Ollama: classify, translate, structured analysis
│   ├── extract_email.py   # Parse arXiv email/XML to paper dicts
│   ├── get_file_from_email.py  # IMAP connection and mail fetching
│   ├── file_writer.py     # JSON → Markdown export
│   ├── send_email.py      # SMTP email sending
│   └── wechat_public.py   # WeChat Public Account upload
├── templates/             # Flask HTML templates
├── downloads/             # Cached emails, XML, JSON, HTML and PDFs
└── md/                    # Daily markdown summaries
```

---

## Quick Start

### 1. Install Dependencies

```bash
pip install -r requirements.txt
# For local inference (optional):
# Install Ollama and pull deepseek-r1:14b
```

### 2. Configure Keys

Edit `src/config.py` — see [Configuration](#configuration-configpy) below.

### 3. Customize Research Interests

Edit the top of `src/model_inference.py`:

```python
RESEARCH_REQUIREMENTS = """
Your research interests here
"""

IMPORTANT_AUTHORS = [
    # "Author Name",
]
```

### 4. Set Email Receivers

Edit `email_list.txt`:

```text
friend@example.com
yourself@example.com
```

### 5. Initialize Database

```bash
python migrate_db.py
```

### 6. Run the Pipeline

```bash
# Fetch latest arXiv email, classify and store papers
python __main__.py --all --use-api

# Run WebUI
bash start_webui.sh
# or: python webui.py
# Access: http://localhost:5000
```

---

## Configuration: config.py

All sensitive credentials are centralized in `src/config.py`. **Do not commit this file to public repositories.**

```python
# DeepSeek API key (https://platform.deepseek.com)
DEEPSEEK_API_KEY = "sk-your-deepseek-api-key-here"

# QQ Mail account and authorization code
EMAIL_USER = "your_qq@qq.com"
EMAIL_PASS = "your_qq_auth_code"

# WeChat Public Account credentials (optional)
WECHAT_APPID = "your-wechat-appid"
WECHAT_SECRET = "your-wechat-secret"
WECHAT_THUMB_MEDIA_ID = "your-thumb-media-id"
```

For QQ Mail, generate an authorization code at:
https://mail.qq.com → Settings → Accounts → POP3/IMAP/SMTP

Also update the IMAP folder name in `__main__.py` if your arXiv folder is not named `arxiv`:

```python
folder_name = 'arxiv'  # or 'INBOX' if you forward arXiv mails there
```

---

## Research Interest & Important Authors

Open `src/model_inference.py` and customize the two variables at the top:

- `RESEARCH_REQUIREMENTS`: describe what papers you care about. The LLM uses this to label papers as `interested` or `irrelevant`.
- `IMPORTANT_AUTHORS`: list of author names. Papers by these authors are always highlighted with a ⭐ marker.

---

## WebUI Features

Start the server with `bash start_webui.sh` then open `http://<your-ip>:5000`.

### Paper List (`/`)
- Full-text search across title, authors, abstract, and arXiv ID
- Filter by label (interested / irrelevant / unanalyzed), read status, download status, content analyzed
- Filter by important-author and famous-author tags
- Sort by any field
- Pagination

### Paper Detail (`/paper/<arxiv_id>`)
- Full metadata display
- Collapsible English abstract
- Chinese abstract translation
- **Structured Analysis Panel** (v2.0.0 new):
  - Research Content
  - Methods
  - Discussion & Analysis
  - Conclusion
- Action buttons: mark read, mark important, mark downloaded, mark content-analyzed

### API Endpoints
| Endpoint | Method | Description |
|---|---|---|
| `/api/stats` | GET | Database statistics |
| `/api/settings` | GET/POST | Read/update inference mode |
| `/api/paper/<id>/toggle_read` | POST | Toggle read status |
| `/api/paper/<id>/toggle_important` | POST | Toggle important status |
| `/api/paper/<id>/mark_important` | POST | Mark as important |
| `/api/paper/<id>/toggle_famous` | POST | Toggle famous status |
| `/api/paper/<id>/toggle_downloaded` | POST | Toggle downloaded status |
| `/api/paper/<id>/toggle_content_analyzed` | POST | Toggle content-analyzed status |
| `/api/paper/<id>/notes` | POST | Save user notes |
| `/api/paper/<id>/analyze` | POST | Run AI analysis on demand |
| `/api/batch/download` | POST | Batch download PDFs |
| `/api/download/status` | GET | Download progress |
| `/api/download/zip` | GET | Download zip of PDFs |
| `/api/batch/analyze` | POST | Batch analyze papers |
| `/api/analyze/status` | GET | Analysis progress |

---

## Mobile Access

1. Start the server: `bash start_webui.sh` (prints your LAN IP automatically)
2. Connect your phone to the same Wi-Fi network
3. Open `http://<LAN-IP>:5000` in your mobile browser

The WebUI is responsive with mobile-optimized layouts, touch-friendly buttons, and collapsible abstract sections.

---

## Module Reference

### `src/config.py`
Central credentials store. Edit before first run.

### `src/model_inference.py`
- `analyze_paper_relevance(paper, use_api, api_key, requirements)` — Classifies the paper and returns `Type`, `keywords`, `keywords_CN`, `Abstract_CN`, `research_content`, `methods`, `discussion`, `conclusion`.
- `translate_paper_abstract(paper)` — Standalone translation via local Ollama.
- `identify_famous_authors(authors, use_api, api_key)` — Uses LLM to detect well-known professors in the author list.

### `src/models.py`
SQLAlchemy model `Paper` with fields for metadata, analysis results, read/download status, and user notes.

### `src/get_file_from_email.py`
IMAP-based email fetcher for QQ Mail.

### `src/extract_email.py`
Parses arXiv mailing list emails/XML into structured paper dictionaries.

### `src/send_email.py`
Sends daily summary reports via SMTP with markdown/HTML attachments.

### `src/wechat_public.py`
Uploads markdown-converted daily summaries as WeChat Public Account draft articles.

### `src/file_writer.py`
Exports paper data to Markdown files organized by date and relevance.
