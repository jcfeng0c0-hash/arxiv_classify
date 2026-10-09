"""
Database migration script for an existing arxiv.db.

Usage:
    cd /path/to/arxiv_classify
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
        ('classification_version', 'VARCHAR(20)', '分类标准版本，历史标签保持不变'),
        ('classification_rule', 'VARCHAR(20)', '分类规则编号'),
        ('analysis_error', 'TEXT', '详细分析失败原因，用于独立重试'),
        ("is_downloaded",       "BOOLEAN DEFAULT 0", "PDF 是否已下载"),
        ("is_content_analyzed", "BOOLEAN DEFAULT 0", "是否已进行内容分析"),
        # v3.0.0: structured analysis fields
        ("research_content",    "TEXT",               "研究内容：数据来源、研究对象"),
        ("methods",             "TEXT",               "研究方法"),
        ("discussion",          "TEXT",               "讨论与分析"),
        ("conclusion",          "TEXT",               "结论"),
        # v3.0.0: user notes
        ("notes",               "TEXT",               "用户笔记"),
        # 知名教授作者识别
        ("famous_authors",      "TEXT",               "大模型识别出的知名教授姓名"),
        ("is_famous_author",    "BOOLEAN DEFAULT 0",  "是否为知名教授（大模型识别）"),
        # 摘要无效标记
        ("is_abstract_invalid", "BOOLEAN DEFAULT 0",  "摘要提取无效，保留但不分析"),
        ("reviewed_at",         "DATETIME",           "用户最近一次标记已读的时间"),
    ]

    for col_name, col_def, description in new_columns:
        if col_name in existing_columns:
            print(f"[SKIP]  Column '{col_name}' already exists.")
        else:
            cursor.execute(f"ALTER TABLE papers ADD COLUMN {col_name} {col_def}")
            print(f"[OK]    Added column '{col_name}' ({description})")

    # 迁移：已有 famous_authors 文本的论文，同步设置 is_famous_author=1
    current_columns = {row[1] for row in cursor.execute("PRAGMA table_info(papers)")}
    if 'is_famous_author' in current_columns and 'is_famous_author' not in existing_columns:
        cursor.execute("""UPDATE papers SET is_famous_author = 1
                          WHERE famous_authors IS NOT NULL AND famous_authors != ''
                          AND (is_famous_author IS NULL OR is_famous_author = 0)""")
        updated = cursor.rowcount
        if updated:
            print(f"[OK]    Migrated {updated} existing famous-author rows to is_famous_author=1")

    # 迁移：已有摘要为 NULL / 空 / 纯分隔线的论文，标记为 is_abstract_invalid=1
    if 'is_abstract_invalid' in current_columns and 'is_abstract_invalid' not in existing_columns:
        cursor.execute("""SELECT id, abstract FROM papers
                          WHERE (is_abstract_invalid IS NULL OR is_abstract_invalid = 0)
                          AND (abstract IS NULL OR abstract = '' OR abstract GLOB '-*')""")
        invalid_ids = []
        for row_id, abstract in cursor.fetchall():
            if abstract is None or abstract.strip() == '' or set(abstract.strip()) == {'-'}:
                invalid_ids.append((row_id,))
        if invalid_ids:
            cursor.executemany("UPDATE papers SET is_abstract_invalid = 1 WHERE id = ?", invalid_ids)
            print(f"[OK]    Migrated {len(invalid_ids)} existing invalid-abstract rows to is_abstract_invalid=1")

    conn.commit()
    conn.close()
    print("Migration complete.")

if __name__ == '__main__':
    migrate()
