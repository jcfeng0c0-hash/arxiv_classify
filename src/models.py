from sqlalchemy import create_engine, Column, Integer, String, Text, DateTime, Boolean
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
import datetime
from pathlib import Path

Base = declarative_base()

class Paper(Base):
    __tablename__ = 'papers'

    # 基本信息
    id = Column(Integer, primary_key=True, autoincrement=True)
    arxiv_id = Column(String(50), unique=True, nullable=False) # 唯一标识，去重核心
    version = Column(Integer, default=1)
    title = Column(String(500))
    authors = Column(Text)
    abstract = Column(Text)
    url = Column(String(200))
    publish_date = Column(String(50)) # 论文发布日期

    # 筛选分析信息
    category = Column(String(100))        # 英文关键词 (逗号分隔)
    keywords_cn = Column(String(200))     # 🆕 中文关键词 (逗号分隔)
    my_label = Column(String(100))        # AI 标注: interested/irrelevant
    classification_version = Column(String(20))
    classification_rule = Column(String(20))
    analysis_error = Column(Text)
    relevance_score = Column(Integer, default=0)
    summary_cn = Column(Text)             # 中文摘要/总结
    is_important_author = Column(Boolean, default=False)  # Important 论文标记（用户自定义名单 / 手动标记）
    is_famous_author = Column(Boolean, default=False)     # 知名教授标记（大模型识别）
    famous_authors = Column(Text)         # 大模型识别出的知名教授姓名列表（逗号分隔）

    # 结构化分析 (v3.0.0)
    research_content = Column(Text)       # 研究内容：数据来源、研究对象
    methods = Column(Text)                # 研究方法
    discussion = Column(Text)             # 讨论与分析
    conclusion = Column(Text)             # 结论

    # 用户笔记
    notes = Column(Text)

    # 流程控制
    is_pushed = Column(Boolean, default=False)            # 是否已推送
    is_read = Column(Boolean, default=False)              # 是否已读
    is_downloaded = Column(Boolean, default=False)        # 是否已下载 PDF
    is_content_analyzed = Column(Boolean, default=False)  # 是否已进行内容分析
    is_abstract_invalid = Column(Boolean, default=False)  # 摘要提取无效（如修订版条目），保留但不分析
    reviewed_at = Column(DateTime)                        # 用户最近一次标记已读的时间
    created_at = Column(DateTime, default=datetime.datetime.now)

# 数据库连接配置 (在当前目录下生成 arxiv.db 文件)
DB_PATH = Path(__file__).resolve().parents[1] / 'arxiv.db'
engine = create_engine(f'sqlite:///{DB_PATH}', echo=False)
SessionLocal = sessionmaker(bind=engine)

def init_db():
    Base.metadata.create_all(engine)
