import json
import re
from collections import defaultdict

def json_to_markdown(json_file_path, md_file_path):
    """
    将 JSON 文件转换为 Markdown，并按 `type` 进行分类存储。
    - 先按 `type` 进行分组，每类论文用一级标题 `# Type: <类型>` 进行区分。
    - 论文内部用二级标题 `## Paper ID: <id>` 标识。
    - 去掉摘要中的换行符，使其变成单行。
    """
    # 1. 读取 JSON 文件
    with open(json_file_path, 'r', encoding='utf-8') as f:
        papers = json.load(f)  # 假设是一个列表结构

    # 2. 先按 `type` 进行分类
    categorized_papers = defaultdict(list)
    for paper in papers:
        paper_type = paper.get('Type', 'Unknown')  # 以 'Unknown' 作为默认分类
        categorized_papers[paper_type].append(paper)

    # 3. 定义类型顺序
    type_order = ['ISM', 'StarFormation', 'Other', 'Unknown']

    # 4. 打开 Markdown 文件，按指定顺序写入
    with open(md_file_path, 'w', encoding='utf-8') as f:
        #f.write(f"- [ ] ISM\n\n")
        #f.write(f"- [ ] StarFormation\n\n")
        #f.write(f"- [ ] Other\n\n")
        for paper_type in type_order:
            if paper_type in categorized_papers:
                # 一级标题（论文类别）
                f.write(f"# Type: {paper_type}\n\n")

                for paper in categorized_papers[paper_type]:
                    # 读取字段，避免 KeyError
                    paper_id = paper.get('id', 'N/A')
                    date = paper.get('date', 'N/A')
                    title = paper.get('Title', 'N/A')
                    authors = paper.get('Authors', 'N/A')
                    summary = paper.get('summary', 'N/A')
                    keywords = paper.get('keywords', 'N/A')
                    keywords_CN = paper.get('keywords_CN', 'N/A')
                    # 摘要换行转换（去掉多余空白字符）
                    abstract = paper.get('Abstract', 'N/A')
                    abstract_CN = paper.get('Abstract_CN', 'N/A')
                    # 检查是否以两个%开始
                    if abstract.startswith('%%'):
                        abstract_singleline = 'N/A'
                    else:
                        abstract_singleline = abstract.replace('\n', ' ')  # 只替换换行符
                        abstract_singleline = abstract_singleline.replace('&', '\\')  # 替换 `&` 为 `\`

                    # 论文内容（使用二级标题 `##` 进行分隔）
                    f.write(f"\n### **{title}** \n\n")
                    f.write("**Keywords**: ")
                    if isinstance(keywords, list):
                        for keyword in keywords:
                            # 将关键词中的空格替换为下划线
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
                    f.write("---\n\n")  # 每篇论文之间插入分割线
                    #f.write("\\newpage \n")

    print(f"已将 {json_file_path} 转换为 Markdown 文件，并按 `type` 分类存入：{md_file_path}")


def write_papers_to_markdown(papers_list, md_file_path):
    """
    将论文列表写入 Markdown，按 Type 分类，Important 论文优先显示
    """
    from collections import defaultdict

    # 按 `type` 和 `is_important` 分类
    categorized_papers = defaultdict(lambda: {'important': [], 'regular': []})

    for paper in papers_list:
        paper_type = paper.get('Type', 'Unknown')
        is_important = paper.get('is_important', False)

        if is_important:
            categorized_papers[paper_type]['important'].append(paper)
        else:
            categorized_papers[paper_type]['regular'].append(paper)

    # 定义类型顺序
    type_order = ['interested', 'irrelevant', 'Unknown']

    # 写入 Markdown 文件
    with open(md_file_path, 'w', encoding='utf-8') as f:
        for paper_type in type_order:
            if paper_type not in categorized_papers:
                continue

            # 写入分类标题
            f.write(f"# Type: {paper_type}\n\n")

            # 先写 Important 论文
            important_papers = categorized_papers[paper_type]['important']
            regular_papers = categorized_papers[paper_type]['regular']

            if important_papers:
                f.write(f"## ⭐ Important Papers ({len(important_papers)} papers)\n\n")
                for paper in important_papers:
                    write_paper_entry(f, paper)

            if regular_papers:
                if important_papers:  # 如果有重要论文，添加分隔
                    f.write(f"## Regular Papers ({len(regular_papers)} papers)\n\n")
                for paper in regular_papers:
                    write_paper_entry(f, paper)

    print(f"已将论文列表转换为 Markdown 文件：{md_file_path}")


def write_paper_entry(f, paper):
    """
    写入单篇论文条目
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

    # 处理摘要
    if abstract.startswith('%%'):
        abstract_singleline = 'N/A'
    else:
        abstract_singleline = abstract.replace('\n', ' ')
        abstract_singleline = abstract_singleline.replace('&', '\\')

    # 写入论文内容
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
