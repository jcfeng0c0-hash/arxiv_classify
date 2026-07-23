import json
import re
from collections import defaultdict

def json_to_markdown(json_file_path, md_file_path):
    """
    Convert a JSON file to Markdown, grouped by `type`.
    - First group papers by `type`, with each group under a level-1 heading `# Type: <type>`.
    - Inside each group, identify each paper with a level-2 heading `## Paper ID: <id>`.
    - Remove newlines from abstracts so they become single-line.
    """
    # 1. Read the JSON file
    with open(json_file_path, 'r', encoding='utf-8') as f:
        papers = json.load(f)  # Expected to be a list

    # 2. Group by `type`
    categorized_papers = defaultdict(list)
    for paper in papers:
        paper_type = paper.get('Type', 'Unknown')  # Default group is 'Unknown'
        categorized_papers[paper_type].append(paper)

    # 3. Define type order
    type_order = ['ISM', 'StarFormation', 'Other', 'Unknown']

    # 4. Open the Markdown file and write in the specified order
    with open(md_file_path, 'w', encoding='utf-8') as f:
        #f.write(f"- [ ] ISM\n\n")
        #f.write(f"- [ ] StarFormation\n\n")
        #f.write(f"- [ ] Other\n\n")
        for paper_type in type_order:
            if paper_type in categorized_papers:
                # Level-1 heading (paper category)
                f.write(f"# Type: {paper_type}\n\n")

                for paper in categorized_papers[paper_type]:
                    # Read fields, avoiding KeyError
                    paper_id = paper.get('id', 'N/A')
                    date = paper.get('date', 'N/A')
                    title = paper.get('Title', 'N/A')
                    authors = paper.get('Authors', 'N/A')
                    summary = paper.get('summary', 'N/A')
                    keywords = paper.get('keywords', 'N/A')
                    keywords_CN = paper.get('keywords_CN', 'N/A')
                    # Convert abstract newlines (remove extra whitespace)
                    abstract = paper.get('Abstract', 'N/A')
                    abstract_CN = paper.get('Abstract_CN', 'N/A')
                    # Check whether it starts with two percent signs
                    if abstract.startswith('%%'):
                        abstract_singleline = 'N/A'
                    else:
                        abstract_singleline = abstract.replace('\n', ' ')  # Replace newlines only
                        abstract_singleline = abstract_singleline.replace('&', '\\')  # Replace `&` with `\`

                    # Paper content (separated by level-2 heading `##`)
                    f.write(f"\n### **{title}** \n\n")
                    f.write("**Keywords**: ")
                    if isinstance(keywords, list):
                        for keyword in keywords:
                            # Replace spaces in keywords with underscores
                            keyword = keyword.replace(' ', '_')
                            f.write(f"#{keyword} ")
                    f.write("\n\n")
                    if isinstance(keywords_CN, list):
                        for keyword_CN in keywords_CN:
                            f.write(f" **{keyword_CN}**  ")
                    f.write("\n\n")
                    f.write(f"**Authors**: {authors}\n\n")
                    f.write(f"**Abstract**: {abstract_singleline}\n\n")
                    f.write(f"**Abstract_CN**: \n {abstract_CN}\n\n")
                    f.write(f"Paper Link: ```https://arxiv.org/abs/{paper_id}``` \n\n")
                    f.write(f"Date: {date}\n\n")
                    #f.write(f" \n ``` \n https://arxiv.org/abs/{paper_id} \n ```\n\n")
                    #f.write(f" \n ``` \n {title} \n ```\n\n")
                    #f.write(f"\n ``` \n **Summary**:  {summary}\n ```\n\n")
                    f.write("---\n\n")  # Divider between papers
                    #f.write("\\newpage \n")

    print(f"Converted {json_file_path} to Markdown, grouped by `type`, saved to: {md_file_path}")


def write_papers_to_markdown(papers_list, md_file_path):
    """
    Write the paper list to Markdown, grouped by Type, with Important papers shown first.
    """
    from collections import defaultdict

    # Group by `type` and `is_important`
    categorized_papers = defaultdict(lambda: {'important': [], 'regular': []})

    for paper in papers_list:
        paper_type = paper.get('Type', 'Unknown')
        is_important = paper.get('is_important', False)

        if is_important:
            categorized_papers[paper_type]['important'].append(paper)
        else:
            categorized_papers[paper_type]['regular'].append(paper)

    # Define type order
    type_order = ['interested', 'irrelevant', 'Unknown']

    # Write the Markdown file
    with open(md_file_path, 'w', encoding='utf-8') as f:
        for paper_type in type_order:
            if paper_type not in categorized_papers:
                continue

            # Write category heading
            f.write(f"# Type: {paper_type}\n\n")

            # Write Important papers first
            important_papers = categorized_papers[paper_type]['important']
            regular_papers = categorized_papers[paper_type]['regular']

            if important_papers:
                f.write(f"## ⭐ Important Papers ({len(important_papers)} papers)\n\n")
                for paper in important_papers:
                    write_paper_entry(f, paper)

            if regular_papers:
                if important_papers:  # Add a separator if there are Important papers
                    f.write(f"## Regular Papers ({len(regular_papers)} papers)\n\n")
                for paper in regular_papers:
                    write_paper_entry(f, paper)

    print(f"Converted paper list to Markdown: {md_file_path}")


def write_paper_entry(f, paper):
    """
    Write a single paper entry.
    """
    paper_id = paper.get('id', 'N/A')
    date = paper.get('date', 'N/A')
    title = paper.get('Title', 'N/A')
    authors = paper.get('Authors', 'N/A')
    keywords = paper.get('keywords', [])
    keywords_CN = paper.get('keywords_CN', [])
    abstract = paper.get('Abstract', 'N/A')
    abstract_CN = paper.get('Abstract_CN', 'N/A')
    is_important = paper.get('is_important', False)
    is_famous = paper.get('is_famous', False)
    famous_authors = paper.get('famous_authors', '')

    # Process abstract
    if abstract.startswith('%%'):
        abstract_singleline = 'N/A'
    else:
        abstract_singleline = abstract.replace('\n', ' ')
        abstract_singleline = abstract_singleline.replace('&', '\\')

    # Write paper content
    marks = []
    if is_important:
        marks.append("⭐")
    if is_famous:
        marks.append("🏆")
    importance_mark = " ".join(marks)
    if importance_mark:
        importance_mark += " "
    f.write(f"\n### {importance_mark}**{title}** \n\n")
    f.write("**Keywords**: ")
    if isinstance(keywords, list):
        for keyword in keywords:
            keyword = keyword.replace(' ', '_')
            f.write(f"#{keyword} ")
    f.write("\n\n")
    if isinstance(keywords_CN, list):
        for keyword_CN in keywords_CN:
            f.write(f" **{keyword_CN}**  ")
    f.write("\n\n")
    if is_famous and famous_authors:
        f.write(f"**🏆 Famous Professor**: {famous_authors}\n\n")
    f.write(f"**Authors**: {authors}\n\n")
    f.write(f"**Abstract**: {abstract_singleline}\n\n")
    f.write(f"**Abstract_CN**: \n {abstract_CN}\n\n")
    f.write(f"Paper Link: ```https://arxiv.org/abs/{paper_id}``` \n\n")
    f.write(f"Date: {date}\n\n")
    f.write("---\n\n")

