"""
Database migration script - run once to add new columns to an existing arxiv.db.

Usage:
    cd /path/to/arxiv_classify-2.0.0
    python migrate_db.py
"""
import os
import sqlite3

DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'arxiv.db')

def migrate():
    if not os.path.exists(DB_PATH):
        print(f"[ERROR] Database not found at: {DB_PATH}")
        return

    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    existing_columns = {row[1] for row in cursor.execute("PRAGMA table_info(papers)")}

    new_columns = [
        ("is_downloaded",       "BOOLEAN DEFAULT 0", "Whether the PDF has been downloaded"),
        ("is_content_analyzed", "BOOLEAN DEFAULT 0", "Whether content analysis has been performed"),
        # v2.0.0: structured analysis fields
        ("research_content",    "TEXT",               "Research content: data sources, research objects"),
        ("methods",             "TEXT",               "Research methods"),
        ("discussion",          "TEXT",               "Discussion and analysis"),
        ("conclusion",          "TEXT",               "Conclusion"),
        # v2.0.0: user notes
        ("notes",               "TEXT",               "User notes"),
        # Famous-professor author identification
        ("famous_authors",      "TEXT",               "Comma-separated famous-professor names identified by the LLM"),
        ("is_famous_author",    "BOOLEAN DEFAULT 0",  "Whether the author is a famous professor (LLM identified)"),
    ]

    for col_name, col_def, description in new_columns:
        if col_name in existing_columns:
            print(f"[SKIP]  Column '{col_name}' already exists.")
        else:
            cursor.execute(f"ALTER TABLE papers ADD COLUMN {col_name} {col_def}")
            print(f"[OK]    Added column '{col_name}' ({description})")

    # Migration: for papers that already have famous_authors text, set is_famous_author=1
    current_columns = {row[1] for row in cursor.execute("PRAGMA table_info(papers)")}
    if 'is_famous_author' in current_columns:
        cursor.execute("UPDATE papers SET is_famous_author = 1 WHERE famous_authors IS NOT NULL AND famous_authors != ''")
        updated = cursor.rowcount
        if updated:
            print(f"[OK]    Migrated {updated} existing famous-author rows to is_famous_author=1")

    conn.commit()
    conn.close()
    print("Migration complete.")

if __name__ == '__main__':
    migrate()
