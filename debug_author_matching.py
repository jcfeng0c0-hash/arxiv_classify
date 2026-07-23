from src.models import SessionLocal, Paper
from src.model_inference import check_important_author, IMPORTANT_AUTHORS

db = SessionLocal()

print("=" * 80)
print("DEBUG: IMPORTANT AUTHOR MATCHING")
print("=" * 80)
print(f"\nImportant Authors List: {IMPORTANT_AUTHORS}\n")

# Get papers marked as important
important_papers = db.query(Paper).filter(Paper.is_important_author == True).all()

if not important_papers:
    print("No papers marked as important yet.")
else:
    print(f"Found {len(important_papers)} papers marked as important:\n")
    
    for i, paper in enumerate(important_papers, 1):
        print(f"[{i}] {paper.arxiv_id}")
        print(f"    Title: {paper.title[:60]}...")
        print(f"    Authors: {paper.authors}")
        
        # Re-check the matching
        is_imp, matched = check_important_author(paper.authors)
        print(f"    Matched: {matched}")
        print(f"    Match result: {is_imp}")
        print()

# Also check all papers to see if any should be marked
print("=" * 80)
print("CHECKING ALL PAPERS:")
print("=" * 80)

all_papers = db.query(Paper).all()

false_positives = []
false_negatives = []

for paper in all_papers:
    is_imp, matched = check_important_author(paper.authors)
    
    if is_imp and not paper.is_important_author:
        false_negatives.append((paper, matched))
    elif not is_imp and paper.is_important_author:
        false_positives.append(paper)

if false_positives:
    print(f"\n❌ FALSE POSITIVES (marked important but shouldn't be): {len(false_positives)}")
    for paper in false_positives[:5]:
        print(f"    {paper.arxiv_id}: {paper.authors[:80]}...")

if false_negatives:
    print(f"\n❌ FALSE NEGATIVES (should be important but not marked): {len(false_negatives)}")
    for paper, matched in false_negatives[:5]:
        print(f"    {paper.arxiv_id}: {paper.authors[:80]}... (matched: {matched})")

db.close()