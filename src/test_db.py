from models import SessionLocal, Paper
from datetime import datetime

db = SessionLocal()

print("=" * 60)
print("DATABASE STATUS CHECK")
print("=" * 60)

# Count total papers
total = db.query(Paper).count()
print(f"\n📊 Total papers in database: {total}")

# Count unanalyzed papers (my_label is NULL)
unanalyzed = db.query(Paper).filter(Paper.my_label == None).count()
print(f"🔍 Unanalyzed papers (my_label IS NULL): {unanalyzed}")

# Count analyzed papers
analyzed = db.query(Paper).filter(Paper.my_label != None).count()
print(f"✓ Analyzed papers: {analyzed}")

# Show unanalyzed papers
if unanalyzed > 0:
    print("\n" + "=" * 60)
    print("UNANALYZED PAPERS:")
    print("=" * 60)
    papers = db.query(Paper).filter(Paper.my_label == None).limit(5).all()
    for p in papers:
        print(f"\n📄 {p.arxiv_id}")
        print(f"   Title: {p.title[:60]}...")
        print(f"   Created: {p.created_at}")

# Show today's papers
today_start = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
today_papers = db.query(Paper).filter(Paper.created_at >= today_start).count()
print(f"\n📅 Papers added today: {today_papers}")

# Show analyzed papers (limit 5 for brevity)
if analyzed > 0:
    print("\n" + "=" * 60)
    print("ANALYZED PAPERS (showing up to 5):")
    print("=" * 60)
    analyzed_papers = db.query(Paper).filter(Paper.my_label != None).order_by(Paper.created_at.desc()).limit(5).all()
    for p in analyzed_papers:
        print(f"\n📄 {p.arxiv_id}")
        print(f"   Title: {p.title[:60]}...")
        print(f"   Label: {p.my_label}")
        print(f"   Keywords(EN): {p.category}")
        print(f"   Keywords(CN): {p.keywords_cn}")
        print(f"   Created: {p.created_at}")
        print(f"   Summary(CN): {p.summary_cn}")
        print(f"   Abstract: {p.abstract}")
        print(f"   URL: {p.url}")




db.close()