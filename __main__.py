from datetime import datetime
import re
import os
import argparse
from src.model_inference import analyze_paper_relevance, translate_paper_abstract, identify_famous_authors
from src.get_file_from_email import (
    connect_and_login,
    fetch_latest_email,
    get_email_text_body,
    save_email_as_xml,
    close_connection
)
from src.extract_email  import (
    parse_eml,
    extract_papers,
    save_papers_to_json,
    print_paper,
    read_papers_from_json
)
from src.file_writer import json_to_markdown
from src.send_email import send_email_with_attachment
from src.wechat_public import upload_main
from src.models import SessionLocal, Paper, init_db
import markdown

from src.config import EMAIL_USER, EMAIL_PASS

# Edit your QQ Mail account and authorization code in src/config.py
email_user = EMAIL_USER
email_pass = EMAIL_PASS

def get_latest_arxiv_email():
    """
    Fetch the latest arXiv email from the specified folder, save it as an XML file,
    and return the filename without extension.
    """
    # 1. Connect and log in
    mail, status = connect_and_login(email_user, email_pass)
    if status != 'OK' or not mail:
        print("Login failed; cannot fetch email.")
        return None

    # 2. Fetch the latest email
    # Adjust the folder name according to your mailbox. In QQ Mail, if you created a folder named 'arxiv',
    # the IMAP path is usually 'arxiv'; for a subfolder under INBOX, a different encoded form may be needed.
    folder_name = 'arxiv'  # or 'INBOX'
    msg, subject, from_, date_str = fetch_latest_email(mail, folder_name)
    if not msg:
        # Error or no emails; close the connection and exit
        close_connection(mail)
        return None

    print("Latest email:")
    print(f"Subject: {subject}")
    print(f"From: {from_}")
    print(f"Date: {date_str}")

    # 3. Get the email body
    body = get_email_text_body(msg)

    # 4. Save as XML
    filename = save_email_as_xml(subject, from_, date_str, body, output_dir='./downloads')
    print(f"Email saved as: {filename}")

    # 5. Close the connection
    close_connection(mail)
    # Return the path without extension, e.g. './downloads/<subject>_<date_str>'
    return filename.replace('.xml', '')

def parse_and_extract(filename_base):
    """
    Given a filename without extension (filename_base), read the .xml file, extract paper information,
    and save it as .json. Returns the JSON file path.
    """
    if not filename_base:
        print("No valid XML file provided; cannot parse.")
        return None

    xml_path = filename_base + '.xml'
    if not os.path.exists(xml_path):
        print(f"File not found: {xml_path}")
        return None

    msg = parse_eml(xml_path)
    papers = extract_papers(msg)

    json_path = filename_base + '.json'
    save_papers_to_json(papers, json_path)
    print(f"Paper information saved to {json_path}")
    return json_path

def clean_arxiv_id(raw_id):
    """
    Clean the ArXiv ID, removing markers such as (*cross-listing*).
    Input: "2512.20820 (*cross-listing*)" or "2312.12345v2"
    Output: "2512.20820" or "2312.12345v2"
    """
    if not raw_id:
        return raw_id
    # Remove (*cross-listing*) and similar markers
    cleaned = re.sub(r'\s*\([^)]*cross-listing[^)]*\)', '', raw_id, flags=re.IGNORECASE)
    # Remove other possible parenthetical markers at the end
    cleaned = re.sub(r'\s*\([^)]*\)\s*$', '', cleaned)
    return cleaned.strip()

def parse_arxiv_id(raw_id):
    """
    Input: "2312.12345v2" or "astro-ph/0101001v1" or "2512.20820 (*cross-listing*)"
    Output: ("2312.12345", 2) or ("astro-ph/0101001", 1)
    """
    # Clean the ID first
    cleaned_id = clean_arxiv_id(raw_id)
    # Match the pattern of 'v' followed by digits at the end
    match = re.match(r"(.+)v(\d+)$", cleaned_id)
    if match:
        base_id = match.group(1)
        version = int(match.group(2))
        return base_id, version
    return cleaned_id, 1  # Default version is 1 if no match


def save_to_database(papers_data):
    """
    Save the extracted paper list to the database, handling deduplication automatically.
    """
    db = SessionLocal()
    new_count = 0

    for p in papers_data:
        base_id, version = parse_arxiv_id(p['id'])

        # Check whether this base ID already exists in the database
        existing_paper = db.query(Paper).filter(Paper.arxiv_id == base_id).first()

        # Build the correct URL using the cleaned base_id, appending version if present
        url_id = f"{base_id}v{version}" if version > 1 else base_id
        paper_url = f"https://arxiv.org/abs/{url_id}"

        if not existing_paper:
            # Case 1: brand-new paper
            new_p = Paper(
                arxiv_id=base_id,
                version=version,
                title=p['Title'],
                authors=p.get('Authors', ''),
                abstract=p.get('Abstract', ''),
                category=p.get('Category', ''),
                url=paper_url
            )
            db.add(new_p)
            new_count += 1
            print(f"Added new paper: {base_id} (v{version})")

        elif version > existing_paper.version:
            # Case 3: new version found; update content
            existing_paper.version = version
            existing_paper.title = p['Title']
            existing_paper.abstract = p.get('Abstract', '')
            existing_paper.url = paper_url  # Update URL
            # Reset analysis status so the AI reanalyzes (new version may differ)
            existing_paper.my_label = None
            existing_paper.is_pushed = False
            new_count += 1
            print(f"Updated paper version: {base_id} v{existing_paper.version} -> v{version}")

    db.commit()
    db.close()
    print(f"Database update complete: {new_count} new papers added/updated.")
    return new_count




def analyze_papers_from_db(use_api=False):
    """
    Read unanalyzed papers from the database (my_label is NULL), perform relevance analysis,
    and update the database.
    """
    from src.model_inference import check_important_author

    db = SessionLocal()

    # Query all unanalyzed papers (my_label is NULL)
    papers_to_analyze = db.query(Paper).filter(Paper.my_label == None).all()

    if not papers_to_analyze:
        print("No new papers to analyze.")
        db.close()
        return 0

    print(f"Found {len(papers_to_analyze)} papers to analyze...")
    analyzed_count = 0
    important_count = 0
    famous_count = 0

    for paper_obj in papers_to_analyze:
        print(f'\nAnalyzing: {paper_obj.arxiv_id}')

        # Step 1: check whether this is an Important paper (user-defined author list)
        is_important, matched_authors = check_important_author(paper_obj.authors)

        # Step 2: use an LLM to identify famous professors
        famous_result = identify_famous_authors(paper_obj.authors, use_api=use_api)
        has_famous = famous_result.get("has_famous_author", False)
        famous_names = famous_result.get("famous_authors", [])

        # Important-paper and famous-professor tags are independent
        if is_important:
            print(f"  ⭐ Important match: {', '.join(matched_authors)}")
            paper_obj.is_important_author = True
            important_count += 1
        else:
            paper_obj.is_important_author = False

        if has_famous:
            print(f"  🏆 Famous professor identified: {', '.join(famous_names)}")
            paper_obj.is_famous_author = True
            paper_obj.famous_authors = ', '.join(famous_names)
            famous_count += 1
        else:
            paper_obj.is_famous_author = False
            paper_obj.famous_authors = None

        # Step 3: run AI analysis on all papers (including Important ones)
        # Check whether the abstract is valid
        if not paper_obj.abstract or re.match(r'^-+$', paper_obj.abstract):
            print(f"  Skipped: invalid abstract")
            continue

        # Build the paper dict for AI analysis
        paper_dict = {
            'id': paper_obj.arxiv_id,
            'Title': paper_obj.title,
            'Abstract': paper_obj.abstract,
            'Authors': paper_obj.authors
        }

        # Call the AI analysis
        try:
            print(f"  🔬 Starting AI analysis...")
            relevance_result = analyze_paper_relevance(paper_dict, use_api=use_api)

            # Check for errors
            if 'error' in relevance_result:
                print(f"  ❌ Analysis failed: {relevance_result['error']}")
                continue

            # Update the database record
            paper_obj.my_label = relevance_result.get('Type', 'Unknown')
            paper_obj.summary_cn = relevance_result.get('Abstract_CN', '')
            paper_obj.research_content = relevance_result.get('research_content', '')
            paper_obj.methods = relevance_result.get('methods', '')
            paper_obj.discussion = relevance_result.get('discussion', '')
            paper_obj.conclusion = relevance_result.get('conclusion', '')
            paper_obj.is_content_analyzed = True

            # Convert keyword lists to strings for storage
            keywords_en = relevance_result.get('keywords', [])
            keywords_cn = relevance_result.get('keywords_CN', [])
            if keywords_en:
                paper_obj.category = ', '.join(keywords_en)
            if keywords_cn:
                paper_obj.keywords_cn = ', '.join(keywords_cn)

            db.commit()
            analyzed_count += 1

            # Display results
            marks = []
            if paper_obj.is_important_author:
                marks.append("⭐")
            if paper_obj.is_famous_author:
                marks.append("🏆")
            importance_mark = " ".join(marks)
            print(f"  ✓ Analysis complete: {paper_obj.arxiv_id} -> {paper_obj.my_label} {importance_mark}")

        except Exception as e:
            print(f"  ❌ Analysis error: {e}")
            db.rollback()
            continue

    db.close()
    print(f"\n{'='*60}")
    print(f"Analysis complete!")
    print(f"  - Total analyzed: {analyzed_count}")
    print(f"  - Important (custom list): {important_count}")
    print(f"  - Famous professors (LLM identified): {famous_count}")
    print(f"  - Regular papers: {analyzed_count - important_count - famous_count}")
    print(f"{'='*60}")
    return analyzed_count

def generate_markdown_from_db():
    """
    Read today's analyzed papers from the database and generate Markdown and HTML files.
    Important papers are shown first.
    """
    db = SessionLocal()
    date_str = datetime.now().strftime("%Y-%m-%d")

    # Query papers created today that have been analyzed (my_label is not NULL)
    today_start = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
    papers = db.query(Paper).filter(
        Paper.created_at >= today_start,
        Paper.my_label != None
    ).order_by(Paper.is_important_author.desc(), Paper.is_famous_author.desc()).all()  # 🆕 Important & famous first

    if not papers:
        print("No analyzed papers found for today.")
        db.close()
        return None, None

    print(f"Found {len(papers)} analyzed papers; generating report...")

    # Statistics
    important_interested = sum(1 for p in papers if p.is_important_author and p.my_label == 'interested')
    important_irrelevant = sum(1 for p in papers if p.is_important_author and p.my_label == 'irrelevant')
    famous_interested = sum(1 for p in papers if p.is_famous_author and p.my_label == 'interested')
    famous_irrelevant = sum(1 for p in papers if p.is_famous_author and p.my_label == 'irrelevant')
    regular_interested = sum(1 for p in papers if not p.is_important_author and not p.is_famous_author and p.my_label == 'interested')
    regular_irrelevant = sum(1 for p in papers if not p.is_important_author and not p.is_famous_author and p.my_label == 'irrelevant')

    print(f"  ⭐ Important - Interested: {important_interested}")
    print(f"  ⭐ Important - Irrelevant: {important_irrelevant}")
    print(f"  🏆 Famous professor - Interested: {famous_interested}")
    print(f"  🏆 Famous professor - Irrelevant: {famous_irrelevant}")
    print(f"  📄 Regular - Interested: {regular_interested}")
    print(f"  📄 Regular - Irrelevant: {regular_irrelevant}")

    # Convert to dict format
    papers_dict_list = []
    for p in papers:
        # Add importance markers to Type
        type_label = p.my_label
        if p.is_important_author:
            type_label = f"⭐ {p.my_label}"  # Add star
        if p.is_famous_author:
            type_label = f"🏆 {type_label}"  # Add famous-professor marker

        paper_dict = {
            'id': p.arxiv_id,
            'date': p.publish_date or date_str,
            'Title': p.title,
            'Authors': p.authors,
            'Abstract': p.abstract,
            'Type': p.my_label,  # Keep original classification for grouping
            'Display_Type': type_label,  # Label used for display
            'Abstract_CN': p.summary_cn,
            'keywords': p.category.split(', ') if p.category else [],
            'keywords_CN': p.keywords_cn.split(', ') if p.keywords_cn else [],
            'is_important': p.is_important_author,  # 🆕 important marker
            'is_famous': p.is_famous_author,        # 🆕 famous-professor marker
            'famous_authors': p.famous_authors      # 🆕 famous-professor names
        }
        papers_dict_list.append(paper_dict)

    db.close()

    # Generate Markdown file
    md_path = f'./md/arxiv_{date_str}.md'

    from src.file_writer import write_papers_to_markdown
    write_papers_to_markdown(papers_dict_list, md_path)

    print(f"Markdown file generated: {md_path}")

    # Convert to HTML
    with open(md_path, "r", encoding="utf-8") as f:
        text = f.read()
    html = markdown.markdown(text, extensions=['extra'])
    html_path = f"./downloads/arxiv_{date_str}.html"
    with open(html_path, "w", encoding="utf-8") as f:
        f.write(html)

    print(f"HTML file generated: {html_path}")

    return md_path, html_path


def send_email(html_path):
    # Read receiver email addresses from email_list.txt
    with open("email_list.txt", "r") as file:
        receiver_email = [line.strip() for line in file.readlines() if line.strip() and not line.startswith('#')]

    date_str = datetime.now().strftime("%Y-%m-%d")
    md_path = f'./md/arxiv_{date_str}.md'

    # Call the email-sending function
    send_email_with_attachment(
        sender_email=email_user,
        password=email_pass,
        receiver_email=receiver_email,  # Use the list of addresses read from the file
        attachment_path=[html_path, md_path],
    )
    print(f"Attachments sent: {html_path}")


def main():
    """
    Main function, controlled via command-line arguments:
    - --fetch-email  : Fetch the latest arXiv email and save it as XML
    - --extract-data : Parse (XML -> JSON)
    - --analyze-data : Perform relevance analysis on papers in JSON
    - --generate-md  : Generate Markdown file
    - --send-email   : Send email
    - --file FILE    : Manually specify an .xml or .json file to use instead of the latest email
    - --md-path MD_PATH : Markdown path required when using send-email alone
    - --use-api      : Use the online API instead of the local model for analysis
    - --all          : Run the full pipeline (equivalent to enabling all options above)
    """


    init_db()

    parser = argparse.ArgumentParser(description="ArXiv paper processing pipeline")
    parser.add_argument("--fetch-email", action="store_true", help="Fetch the latest email and save as XML")
    parser.add_argument("--extract-data", action="store_true", help="Parse XML -> JSON")
    parser.add_argument("--analyze-data", action="store_true", help="Perform relevance analysis on papers in JSON")
    parser.add_argument("--generate-md", action="store_true", help="Generate Markdown file from JSON")
    parser.add_argument("--send-email", action="store_true", help="Send email")
    parser.add_argument("--file", type=str, default=None, help="Manually provide an XML or JSON file path (without extension is also acceptable)")
    parser.add_argument("--md-path", type=str, default=None, help="Markdown path required when using send-email alone")
    parser.add_argument("--use-api", action="store_true", help="Use online API instead of local model for analysis")
    parser.add_argument("--send-gzh", action="store_true", help="Push to WeChat Official Account")
    parser.add_argument("--all", action="store_true", help="Run full pipeline (fetch -> parse -> analyze -> generate MD -> send email)")

    args = parser.parse_args()
    date_str = datetime.now().strftime("%Y-%m-%d")
    # If --all is used, enable every step
    if args.all:
        args.fetch_email = True
        args.extract_data = True
        args.analyze_data = True
        args.generate_md = True
        args.send_email = True
        args.send_gzh = True

    # Used to record the filename without extension, e.g. ./downloads/xxx
    filename_base = None
    json_path = None
    md_path = None

    # If --file is provided, determine whether it is .xml / .json / or without extension
    if args.file:
        # Strip the extension for uniform handling later
        if args.file.endswith('.xml'):
            filename_base = args.file.replace('.xml', '')
        elif args.file.endswith('.json'):
            # If a .json file is provided, use it directly for analysis or Markdown generation
            json_path = args.file
            # We can infer filename_base, but it is not strictly necessary
            filename_base = args.file.replace('.json', '')
        else:
            # User may have supplied a path without extension
            filename_base = args.file

    # 1. Fetch the latest email and save as XML
    if args.fetch_email:
        temp_filename_base = get_latest_arxiv_email()
        # If fetching succeeds, override filename_base
        if temp_filename_base:
            filename_base = temp_filename_base


    # 2. Parse and save to database
    if args.extract_data:
        if filename_base:
            # Original parsing logic returns the papers list
            msg = parse_eml(filename_base + '.xml')
            papers = extract_papers(msg)

            # Save to database instead of only saving JSON
            save_to_database(papers)
        else:
            print("Missing file.")

    # 3. Analyze papers if requested (read new papers from database)
    if args.analyze_data:
        analyzed_count = analyze_papers_from_db(use_api=args.use_api)
        if analyzed_count > 0:
            print(f"✓ Successfully analyzed {analyzed_count} new papers")
        else:
            print("No new papers to analyze")



    # 4. Generate Markdown if requested (read from database)
    if args.generate_md:
        result = generate_markdown_from_db()
        if result:
            md_path, html_path = result
            print(f"✓ Report generation complete")
        else:
            print("Cannot generate Markdown: no analyzed papers found")

    # 5. Send email if requested
    if args.send_email:
        if args.md_path:
            send_email(args.md_path)
        elif md_path:
            send_email(html_path)
        else:
            print("Cannot send email: no available Markdown file found.")

    # 6. Push to WeChat Official Account
    if args.send_gzh:
        Tittle = f'Arxiv Daily: {date_str}'
        if args.md_path:
            upload_main(args.md_path, TITLE=Tittle)
        elif md_path:
            upload_main(md_path, TITLE=Tittle)
        else:
            print("Cannot send to WeChat Official Account: no available Markdown file found.")

    # If no arguments were provided, show usage help
    if not any([args.fetch_email, args.extract_data, args.analyze_data, args.generate_md, args.send_email, args.all]):
        parser.print_help()
if __name__ == '__main__':
    main()
