from src.models import SessionLocal, Paper

db = SessionLocal()

print("=" * 80)
print("DATABASE INSPECTION - IMPORTANT & FAMOUS PAPERS")
print("=" * 80)

# Statistics
total = db.query(Paper).count()
analyzed = db.query(Paper).filter(Paper.my_label != None).count()
important_total = db.query(Paper).filter(Paper.is_important_author == True).count()
famous_total = db.query(Paper).filter(Paper.is_famous_author == True).count()

print(f"\n📊 Statistics:")
print(f"   Total papers: {total}")
print(f"   Analyzed: {analyzed}")
print(f"   Important papers: {important_total}")
print(f"   Famous authors: {famous_total}")

# Breakdown by type and importance
print(f"\n📈 Classification:")
for is_imp in [True, False]:
    label = "⭐ Important" if is_imp else "📄 Not Important"
    interested = db.query(Paper).filter(
        Paper.is_important_author == is_imp,
        Paper.my_label == 'interested'
    ).count()
    irrelevant = db.query(Paper).filter(
        Paper.is_important_author == is_imp,
        Paper.my_label == 'irrelevant'
    ).count()
    print(f"   {label}:")
    print(f"      - Interested: {interested}")
    print(f"      - Irrelevant: {irrelevant}")

print(f"\n🏆 Famous Author Classification:")
for is_fam in [True, False]:
    label = "🏆 Famous" if is_fam else "📄 Not Famous"
    interested = db.query(Paper).filter(
        Paper.is_famous_author == is_fam,
        Paper.my_label == 'interested'
    ).count()
    irrelevant = db.query(Paper).filter(
        Paper.is_famous_author == is_fam,
        Paper.my_label == 'irrelevant'
    ).count()
    print(f"   {label}:")
    print(f"      - Interested: {interested}")
    print(f"      - Irrelevant: {irrelevant}")

# Show important papers
print("\n" + "=" * 80)
print("⭐ IMPORTANT PAPERS:")
print("=" * 80)

important_papers = db.query(Paper).filter(Paper.is_important_author == True).all()

if important_papers:
    for i, p in enumerate(important_papers, 1):
        print(f"\n[{i}] {p.arxiv_id}")
        print(f"    Title: {p.title[:70]}...")
        print(f"    AI Classification: {p.my_label}")
        print(f"    Keywords: {p.category}")
        print(f"    Authors: {p.authors[:100]}...")
else:
    print("No important papers found.")

# Show famous author papers
print("\n" + "=" * 80)
print("🏆 FAMOUS AUTHOR PAPERS:")
print("=" * 80)

famous_papers = db.query(Paper).filter(Paper.is_famous_author == True).all()

if famous_papers:
    for i, p in enumerate(famous_papers, 1):
        print(f"\n[{i}] {p.arxiv_id}")
        print(f"    Title: {p.title[:70]}...")
        print(f"    AI Classification: {p.my_label}")
        print(f"    Famous authors: {p.famous_authors}")
        print(f"    Authors: {p.authors[:100]}...")
else:
    print("No famous author papers found.")

db.close()