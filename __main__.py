
from datetime import datetime, timedelta
import re
import os
os.chdir(os.path.dirname(os.path.abspath(__file__)))
import sys
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
from src.classification_policy import VERSION
from src.paper_analysis import apply_analysis_result
from sqlalchemy import or_, and_
from src.paper_figures import collect_interested_figures
import markdown

from src.config import (
    API_PROVIDER, EMAIL_USER, EMAIL_PASS, ARXIV_MAIL_FOLDER,
    WECHAT_APPID, WECHAT_SECRET, WECHAT_THUMB_MEDIA_ID,
)

email_user = EMAIL_USER
email_pass = EMAIL_PASS

def get_latest_arxiv_email():
    """
    从指定文件夹获取最新 arXiv 邮件并保存为 XML 文件，返回不带后缀的文件名。
    """
    # 1. 连接并登录
    mail, status = connect_and_login(email_user, email_pass)
    if status != 'OK' or not mail:
        print("登录失败，无法获取邮件。")
        return None

    # 2. 获取最新邮件
    folder_name = ARXIV_MAIL_FOLDER
    msg, subject, from_, date_str = fetch_latest_email(mail, folder_name)
    if not msg:
        # 出错或者没有邮件，直接关闭连接退出
        close_connection(mail)
        return None

    print("最新邮件：")
    print(f"Subject: {subject}")
    print(f"From: {from_}")
    print(f"Date: {date_str}")

    # 3. 获取邮件正文
    body = get_email_text_body(msg)

    # 4. 保存为 XML
    filename = save_email_as_xml(subject, from_, date_str, body, output_dir='./downloads')
    print(f"邮件已保存为: {filename}")

    # 5. 关闭连接
    close_connection(mail)
    # 返回不带后缀的路径，如 './downloads/<subject>_<date_str>'
    return filename.replace('.xml', '')

def parse_and_extract(filename_base):
    """
    给定不带后缀的文件路径（filename_base），读取 .xml 文件并提取论文信息，然后保存为 .json。
    返回 JSON 文件路径。
    """
    if not filename_base:
        print("未提供有效的 XML 文件，无法解析。")
        return None

    xml_path = filename_base + '.xml'
    if not os.path.exists(xml_path):
        print(f"找不到文件: {xml_path}")
        return None

    msg = parse_eml(xml_path)
    papers = extract_papers(msg)

    json_path = filename_base + '.json'
    save_papers_to_json(papers, json_path)
    print(f"已将论文信息保存到 {json_path}")
    return json_path

def clean_arxiv_id(raw_id):
    """
    清理 ArXiv ID，移除 (*cross-listing*) 等标记
    输入: "2512.20820 (*cross-listing*)" 或 "2312.12345v2"
    输出: "2512.20820" 或 "2312.12345v2"
    """
    if not raw_id:
        return raw_id
    # 移除 (*cross-listing*) 等标记
    cleaned = re.sub(r'\s*\([^)]*cross-listing[^)]*\)', '', raw_id, flags=re.IGNORECASE)
    # 移除其他可能的括号标记
    cleaned = re.sub(r'\s*\([^)]*\)\s*$', '', cleaned)
    return cleaned.strip()

def parse_arxiv_id(raw_id):
    """
    输入: "2312.12345v2" 或 "astro-ph/0101001v1" 或 "2512.20820 (*cross-listing*)"
    输出: ("2312.12345", 2) 或 ("astro-ph/0101001", 1)
    """
    # 先清理 ID
    cleaned_id = clean_arxiv_id(raw_id)
    # 匹配 v 后面跟着数字的模式
    match = re.match(r"(.+)v(\d+)$", cleaned_id)
    if match:
        base_id = match.group(1)
        version = int(match.group(2))
        return base_id, version
    return cleaned_id, 1  # 如果没匹配到，默认版本为 1


def save_to_database(papers_data):
    """
    将提取到的论文列表存入数据库，自动处理去重
    """
    db = SessionLocal()
    new_count = 0

    for p in papers_data:
        base_id, version = parse_arxiv_id(p['id'])

        # 查询数据库中是否已存在该基础 ID
        existing_paper = db.query(Paper).filter(Paper.arxiv_id == base_id).first()

        # 生成正确的 URL（使用清理后的 base_id，如果有版本号则加上）
        url_id = f"{base_id}v{version}" if version > 1 else base_id
        paper_url = f"https://arxiv.org/abs/{url_id}"

        if not existing_paper:
            # 情况 1: 全新论文
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
            print(f"新增论文: {base_id} (v{version})")

        elif version > existing_paper.version:
            # 情况 3: 发现新版本，更新内容
            existing_paper.version = version
            existing_paper.title = p['Title']
            existing_paper.abstract = p.get('Abstract', '')
            existing_paper.url = paper_url  # 更新 URL
            # 重置分析状态，让 AI 重新分析（因为新版内容可能有变）
            existing_paper.my_label = None
            existing_paper.is_content_analyzed = False
            existing_paper.classification_version = None
            existing_paper.classification_rule = None
            existing_paper.analysis_error = None
            existing_paper.is_pushed = False
            new_count += 1
            print(f"更新论文版本: {base_id} v{existing_paper.version} -> v{version}")

    db.commit()
    db.close()
    print(f"数据库更新完成：新增 {new_count} 篇论文。")
    return new_count




def analyze_papers_from_db(api_provider=None):
    """
    从数据库中读取未分析的论文（my_label 为 NULL），进行相关性分析并更新数据库。
    api_provider: 'local' | 'deepseek' | 'kimi'，默认读取 config.API_PROVIDER
    """
    from src.model_inference import check_important_author

    db = SessionLocal()

    # 查询所有未分析且摘要有效的论文（my_label 为 NULL，is_abstract_invalid 为 False）
    papers_to_analyze = db.query(Paper).filter(
        or_(Paper.my_label == None, and_(
            Paper.classification_version == VERSION,
            Paper.my_label == 'interested', Paper.is_content_analyzed == False)),
        Paper.is_abstract_invalid == False
    ).all()

    if not papers_to_analyze:
        print("没有需要分析的新论文。")
        collect_interested_figures(db.query(Paper).filter(
            Paper.my_label == 'interested',
            Paper.created_at >= datetime.now() - timedelta(hours=48)
        ).all())
        db.close()
        return 0

    print(f"找到 {len(papers_to_analyze)} 篇论文需要分析...")
    analyzed_count = 0
    important_count = 0
    famous_count = 0

    for paper_obj in papers_to_analyze:
        print(f'\n正在分析: {paper_obj.arxiv_id}')
        if not paper_obj.abstract or not paper_obj.abstract.strip() or re.match(r'^-+$', paper_obj.abstract.strip()):
            paper_obj.is_abstract_invalid = True
            db.commit()
            continue

        # 第一步：检查是否为 Important 论文（用户自定义作者名单）
        is_important, matched_authors = check_important_author(paper_obj.authors)

        # 第二步：使用大模型识别知名教授
        famous_result = identify_famous_authors(paper_obj.authors, api_provider=api_provider)
        has_famous = famous_result.get("has_famous_author", False)
        famous_names = famous_result.get("famous_authors", [])

        # Important 论文 与 知名教授 是两个独立的标签
        if is_important:
            print(f"  ⭐ Important 匹配: {', '.join(matched_authors)}")
            paper_obj.is_important_author = True
            important_count += 1
        else:
            paper_obj.is_important_author = False

        if has_famous:
            print(f"  🏆 识别到知名教授: {', '.join(famous_names)}")
            paper_obj.is_famous_author = True
            paper_obj.famous_authors = ', '.join(famous_names)
            famous_count += 1
        else:
            paper_obj.is_famous_author = False
            paper_obj.famous_authors = None

        # 构建论文字典供 AI 分析
        paper_dict = {
            'id': paper_obj.arxiv_id,
            'Title': paper_obj.title,
            'Abstract': paper_obj.abstract,
            'Authors': paper_obj.authors
        }

        # 调用 AI 分析
        try:
            print(f"  🔬 开始 AI 分析...")
            relevance_result = analyze_paper_relevance(paper_dict, api_provider=api_provider)

            # 检查是否有错误
            if 'error' in relevance_result:
                print(f"  ❌ 分析失败: {relevance_result['error']}")
                continue

            apply_analysis_result(paper_obj, relevance_result)
            if relevance_result.get('detail_error'):
                print(f"  详细分析待重试: {relevance_result['detail_error']}")

            db.commit()
            analyzed_count += 1

            # 显示结果
            marks = []
            if paper_obj.is_important_author:
                marks.append("⭐")
            if paper_obj.is_famous_author:
                marks.append("🏆")
            importance_mark = " ".join(marks)
            print(f"  ✓ 分析完成: {paper_obj.arxiv_id} -> {paper_obj.my_label} {importance_mark}")

        except Exception as e:
            print(f"  ❌ 分析出错: {e}")
            db.rollback()
            continue

    # The extra step also retries recent previews that failed on a previous run.
    collect_interested_figures(db.query(Paper).filter(
        Paper.my_label == 'interested',
        or_(Paper.created_at >= datetime.now() - timedelta(hours=48),
            Paper.id.in_([paper.id for paper in papers_to_analyze]))
    ).all())
    db.close()
    print(f"\n{'='*60}")
    print(f"分析完成！")
    print(f"  - 总共分析: {analyzed_count} 篇")
    print(f"  - Important（自定义名单）: {important_count} 篇")
    print(f"  - 知名教授（LLM 识别）: {famous_count} 篇")
    print(f"  - 普通论文: {analyzed_count - important_count - famous_count} 篇")
    print(f"{'='*60}")
    return analyzed_count

def generate_markdown_from_db():
    """
    从数据库中读取最近 48 小时内已分析的论文，生成 Markdown 和 HTML 文件。
    Important 论文优先显示。
    """
    db = SessionLocal()
    date_str = datetime.now().strftime("%Y-%m-%d")

    # 查询最近 48 小时内创建的且已分析的论文（my_label 不为 NULL）
    since = datetime.now() - timedelta(hours=48)
    papers = db.query(Paper).filter(
        Paper.created_at >= since,
        Paper.my_label != None
    ).order_by(Paper.is_important_author.desc(), Paper.is_famous_author.desc()).all()  # 🆕 Important & 知名教授优先

    if not papers:
        print("没有找到今天已分析的论文。")
        db.close()
        return None, None

    print(f"找到 {len(papers)} 篇已分析论文，开始生成报告...")

    # 统计
    important_interested = sum(1 for p in papers if p.is_important_author and p.my_label == 'interested')
    important_irrelevant = sum(1 for p in papers if p.is_important_author and p.my_label == 'irrelevant')
    famous_interested = sum(1 for p in papers if p.is_famous_author and p.my_label == 'interested')
    famous_irrelevant = sum(1 for p in papers if p.is_famous_author and p.my_label == 'irrelevant')
    regular_interested = sum(1 for p in papers if not p.is_important_author and not p.is_famous_author and p.my_label == 'interested')
    regular_irrelevant = sum(1 for p in papers if not p.is_important_author and not p.is_famous_author and p.my_label == 'irrelevant')

    print(f"  ⭐ Important - Interested: {important_interested}")
    print(f"  ⭐ Important - Irrelevant: {important_irrelevant}")
    print(f"  🏆 知名教授 - Interested: {famous_interested}")
    print(f"  🏆 知名教授 - Irrelevant: {famous_irrelevant}")
    print(f"  📄 普通 - Interested: {regular_interested}")
    print(f"  📄 普通 - Irrelevant: {regular_irrelevant}")

    # 转换为字典格式
    papers_dict_list = []
    for p in papers:
        # 添加重要标记到 Type
        type_label = p.my_label
        if p.is_important_author:
            type_label = f"⭐ {p.my_label}"  # 添加星标
        if p.is_famous_author:
            type_label = f"🏆 {type_label}"  # 添加知名教授标记

        paper_dict = {
            'id': p.arxiv_id,
            'date': p.publish_date or date_str,
            'Title': p.title,
            'Authors': p.authors,
            'Abstract': p.abstract,
            'Type': p.my_label,  # 保持原始分类用于分组
            'Display_Type': type_label,  # 用于显示的标签
            'Abstract_CN': p.summary_cn,
            'keywords': p.category.split(', ') if p.category else [],
            'keywords_CN': p.keywords_cn.split(', ') if p.keywords_cn else [],
            'is_important': p.is_important_author,  # 🆕 重要标记
            'is_famous': p.is_famous_author,        # 🆕 知名教授标记
            'famous_authors': p.famous_authors      # 🆕 知名教授姓名
        }
        papers_dict_list.append(paper_dict)

    db.close()

    # 生成 Markdown 文件
    md_path = f'./md/arxiv_{date_str}.md'

    from src.file_writer import write_papers_to_markdown
    write_papers_to_markdown(papers_dict_list, md_path)

    print(f"Markdown 文件已生成: {md_path}")

    # 转换为 HTML
    with open(md_path, "r", encoding="utf-8") as f:
        text = f.read()
    html = markdown.markdown(text, extensions=['extra'])
    html_path = f"./downloads/arxiv_{date_str}.html"
    with open(html_path, "w", encoding="utf-8") as f:
        f.write(html)

    print(f"HTML 文件已生成: {html_path}")

    return md_path, html_path


def send_email(attachment_paths):
    recipients_env = os.environ.get('EMAIL_RECIPIENTS', '')
    receiver_email = [item.strip() for item in recipients_env.split(',') if item.strip()]
    if not receiver_email and os.path.exists('email_list.txt'):
        with open('email_list.txt', 'r', encoding='utf-8') as file:
            receiver_email = [line.strip() for line in file if line.strip() and not line.startswith('#')]
    if not email_user or not email_pass or not receiver_email:
        print('跳过邮件发送：请在 .env 中配置 EMAIL_USER、EMAIL_PASS 和 EMAIL_RECIPIENTS。')
        return

    # 过滤掉 None 或空路径
    attachment_paths = [p for p in (attachment_paths if isinstance(attachment_paths, list) else [attachment_paths]) if p]
    if not attachment_paths:
        print("没有可发送的附件。")
        return

    # 调用发送邮件函数
    send_email_with_attachment(
        sender_email=email_user,
        password=email_pass,
        receiver_email=receiver_email,  # 使用从文件读取的邮箱地址列表
        attachment_path=attachment_paths,
    )
    print(f"附件已发送: {attachment_paths}")


def main():
    """
    主函数，通过命令行参数实现：
    - --fetch-email  : 是否获取最新 arXiv 邮件并保存为 XML
    - --extract-data : 是否解析（XML -> JSON）
    - --analyze-data : 是否对 JSON 里的论文进行相关性分析
    - --generate-md  : 是否生成 Markdown 文件
    - --send-email  : 是否发送邮件
    - --file FILE    : 手动指定 .xml 或 .json 文件，以替代获取的新邮件
    - --md-path MD_PATH : 单独使用send-email的功能需要输入md地址
    - --api-provider {local,deepseek,kimi} : 选择推理后端（默认 deepseek）
    - --use-api     : 已弃用，保留兼容；等价于 --api-provider deepseek
    - --all         : 执行完整流程（相当于同时使用以上所有选项）
    """


    init_db()
    from migrate_db import migrate
    migrate()

    parser = argparse.ArgumentParser(description="ArXiv论文处理流程")
    parser.add_argument("--fetch-email", action="store_true", help="获取最新邮件并保存为 XML")
    parser.add_argument("--extract-data", action="store_true", help="解析 XML -> JSON")
    parser.add_argument("--analyze-data", action="store_true", help="对 JSON 中的论文进行相关性分析")
    parser.add_argument("--extract-figures", action="store_true", help="补充所有 interested 论文的前 5 幅图及图注（已有缓存会跳过）")
    parser.add_argument("--generate-md", action="store_true", help="从 JSON 生成 Markdown 文件")
    parser.add_argument("--send-email", action="store_true", help="发送邮件")
    parser.add_argument("--file", type=str, default=None, help="手动提供 XML 或 JSON 文件路径（不带后缀也可）")
    parser.add_argument("--md-path", type=str, default=None, help="单独使用send-email的功能需要输入md地址")
    parser.add_argument("--api-provider", type=str, default=API_PROVIDER, choices=["local", "deepseek", "kimi"],
                        help=f"选择推理后端：local / deepseek / kimi（默认 {API_PROVIDER}）")
    parser.add_argument("--use-api", action="store_true", help="已弃用，保留兼容；等价于 --api-provider deepseek")
    parser.add_argument("--send-gzh", action="store_true", help="发送公众号")
    parser.add_argument("--all", action="store_true", help="执行完整流程（获取邮件->解析->分析->生成MD->发送邮件）")

    args = parser.parse_args()

    # Resolve API provider: --api-provider takes priority, --use-api is legacy
    if args.use_api and args.api_provider == "deepseek" and not any(a.startswith('--api-provider') for a in sys.argv):
        api_provider = "deepseek"
    else:
        api_provider = args.api_provider

    date_str = datetime.now().strftime("%Y-%m-%d")
    # 如果使用 --all，则设置所有步骤为 True
    if args.all:
        args.fetch_email = True
        args.extract_data = True
        args.analyze_data = True
        args.generate_md = True
        args.send_email = bool(EMAIL_USER and EMAIL_PASS)
        args.send_gzh = bool(WECHAT_APPID and WECHAT_SECRET and WECHAT_THUMB_MEDIA_ID)

    # 用来记录不带后缀的文件路径，比如 ./downloads/xxx
    filename_base = None
    json_path = None
    md_path = None
    html_path = None

    # 如果传入了 --file，我们需要判断它是 .xml / .json / 或不带后缀
    if args.file:
        # 去掉后缀，以便后续统一处理
        if args.file.endswith('.xml'):
            filename_base = args.file.replace('.xml', '')
        elif args.file.endswith('.json'):
            # 如果是 .json 文件，后面就直接用它做分析或生成 Markdown
            json_path = args.file
            # 可以从中推断 filename_base，但不一定需要
            filename_base = args.file.replace('.json', '')
        else:
            # 可能用户只给了个不带后缀的路径
            filename_base = args.file

    # 1. 获取最新邮件并保存为 XML
    if args.fetch_email:
        temp_filename_base = get_latest_arxiv_email()
        # 如果成功获取邮件，就覆盖 filename_base
        if temp_filename_base:
            filename_base = temp_filename_base


    # 2. 解析并存入数据库
    if args.extract_data:
        if filename_base:
            # 原有的解析逻辑得到 papers 列表
            msg = parse_eml(filename_base + '.xml')
            papers = extract_papers(msg)

            # 存入数据库代替单纯的 JSON 保存
            save_to_database(papers)
        else:
            print("缺少文件。")

    # 3. 如果需要分析论文（从数据库读取新论文）
    if args.analyze_data:
        analyzed_count = analyze_papers_from_db(api_provider=api_provider)
        if analyzed_count > 0:
            print(f"✓ 成功分析 {analyzed_count} 篇新论文")
        else:
            print("没有需要分析的新论文")



    if args.extract_figures:
        db = SessionLocal()
        try:
            collect_interested_figures(db.query(Paper).filter(
                Paper.my_label == 'interested').order_by(Paper.created_at.desc()).all())
        finally:
            db.close()

    # 4. 如果需要生成 Markdown（从数据库读取）
    if args.generate_md:
        result = generate_markdown_from_db()
        if result:
            md_path, html_path = result
            print(f"✓ 报告生成完成")
        else:
            print("无法生成 Markdown：没有找到已分析的论文")

    # 5. 如果需要发送邮件
    if args.send_email:
        attachments = []
        if html_path:
            attachments.append(html_path)
        if args.md_path:
            attachments.append(args.md_path)
        elif md_path:
            attachments.append(md_path)

        if attachments:
            send_email(attachments)
        else:
            print("无法发送邮件：未找到可用的 Markdown 文件。")

    # 6, 发送公众号
    if args.send_gzh:
        Tittle = f'Arxiv Daily: {date_str}'
        if args.md_path:
            upload_main(args.md_path,TITLE=Tittle)
        elif md_path:
            upload_main(md_path,TITLE=Tittle)
        else:
            print("无法发送gzh：未找到可用的 Markdown 文件。")

    # 如果用户什么参数都没传，就提示用法
    if not any([args.fetch_email, args.extract_data, args.analyze_data, args.extract_figures, args.generate_md, args.send_email, args.all]):
        parser.print_help()
if __name__ == '__main__':
    main()
