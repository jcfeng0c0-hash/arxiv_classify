from src.models import SessionLocal, Paper
from src.model_inference import analyze_paper_relevance

db = SessionLocal()

# Get one unanalyzed paper
paper = db.query(Paper).filter(Paper.my_label == None).first()

if not paper:
    print("❌ No unanalyzed papers found!")
    print("Run: python __main__.py --fetch-email --extract-data")
    db.close()
    exit()

print("=" * 60)
print("TESTING AI ANALYSIS ON SINGLE PAPER")
print("=" * 60)
print(f"\n📄 Paper: {paper.arxiv_id}")
print(f"   Title: {paper.title}")
print(f"   Abstract: {paper.abstract[:200]}...\n")

# Test with local model
print("🔬 Starting analysis with LOCAL model...")
print("-" * 60)

paper_dict = {
    'id': paper.arxiv_id,
    'Title': paper.title,
    'Abstract': paper.abstract,
    'Authors': paper.authors
}

result = analyze_paper_relevance(paper_dict, use_api=True)

print("\n" + "=" * 60)
print("ANALYSIS RESULTS:")
print("=" * 60)

if 'error' in result:
    print(f"❌ Error: {result['error']}")
else:
    print(f"✓ Type: {result.get('Type')}")
    print(f"✓ Keywords (EN): {result.get('keywords')}")
    print(f"✓ Keywords (CN): {result.get('keywords_CN')}")
    print(f"✓ Abstract (CN): {result.get('Abstract_CN', '')[:150]}...\n")
    
    # Update database
    print(result)
    paper.my_label = result.get('Type', 'Unknown')
    paper.summary_cn = result.get('Abstract_CN', '')
    print(f"✓ summary_cn: {paper.summary_cn}")
    print(f'my_label: {paper.my_label}')
    
    keywords_en = result.get('keywords', [])
    keywords_cn = result.get('keywords_CN', [])
    if keywords_en:
        paper.category = ', '.join(keywords_en)
    if keywords_cn:
        paper.keywords_cn = ', '.join(keywords_cn)
    
    db.commit()
    print("✓ Database updated successfully!")

db.close()


