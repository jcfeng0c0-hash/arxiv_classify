import re
import json
from email import policy
from email.parser import BytesParser

def parse_eml(file_path):
    with open(file_path, 'rb') as f:
        return BytesParser(policy=policy.default).parse(f)

def split_entries(body):
    """
    Split the body by the specific delimiter and return a list where each element
    is a "paper entry" string.
    """
    return body.split('\n\\\\\na')

def parse_entry(entry):
    """
    Parse a single paper entry and return a dict containing the paper fields.
    """
    paper = {}
    lines = entry.split('\n')
    paper_content = []
    is_collecting = False
    collecting_title = False
    title_lines = []

    for line in lines:
        line = line.strip()
        if line.startswith('rXiv:'):
            raw_id = line.split(':', 1)[1].strip()
            # Clean the ID: remove (*cross-listing*) and similar markers
            raw_id = re.sub(r'\s*\([^)]*cross-listing[^)]*\)', '', raw_id, flags=re.IGNORECASE)
            raw_id = re.sub(r'\s*\([^)]*\)\s*$', '', raw_id)  # Remove trailing parenthetical content
            paper['id'] = raw_id.strip()
        elif line.startswith('Date:'):
            # Remove extra characters such as (v1)
            date_str = re.sub(r'Date:| \(.*\)', '', line).strip()
            paper['date'] = date_str
            collecting_title = False
        elif line.startswith('Title:'):
            title_lines.append(line.split(':', 1)[1].strip())
            collecting_title = True
        elif collecting_title and not line.startswith('Authors:'):
            title_lines.append(line)
        elif line.startswith('Authors:'):
            paper['Title'] = ' '.join(title_lines).strip()
            paper['Authors'] = line.split(':', 1)[1].strip()
            collecting_title = False
        elif line.startswith('%%--'):
            break
        elif line.startswith('\\\\'):
            # Toggle abstract collection state
            if is_collecting:
                break
            else:
                is_collecting = True
        elif is_collecting:
            paper_content.append(line)

    paper['Abstract'] = '\n'.join(paper_content).strip()
    return paper

def extract_papers(msg):
    papers = []
    body = msg.get_body(preferencelist=('plain')).get_content()
    entries = split_entries(body)

    for entry in entries:
        if entry.startswith('rXiv:'):
            paper = parse_entry(entry)
            papers.append(paper)
    return papers

def save_papers_to_json(papers, file_path):
    with open(file_path, 'w', encoding='utf-8') as f:
        json.dump(papers, f, ensure_ascii=False, indent=4)

def read_papers_from_json(file_path):
    with open(file_path, 'r', encoding='utf-8') as f:
        return json.load(f)

def load_papers_as_dict(papers):
    return {paper.get('id', f"Unknown_{idx}"): paper for idx, paper in enumerate(papers)}

def print_paper(papers):
    for paper in papers:
        print(f"arXiv ID: {paper.get('id', 'N/A')}")
        print(f"Date: {paper.get('date', 'N/A')}")
        print(f"Title: {paper.get('Title', 'N/A')}")
        print(f"Authors: {paper.get('Authors', 'N/A')}")
        print(f"Abstract: {paper.get('Abstract', '')}")
        print('-' * 80)
