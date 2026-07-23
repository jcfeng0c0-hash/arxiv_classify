from sqlalchemy import create_engine, Column, Integer, String, Text, DateTime, Boolean
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
import datetime

Base = declarative_base()

class Paper(Base):
    __tablename__ = 'papers'

    # Basic information
    id = Column(Integer, primary_key=True, autoincrement=True)
    arxiv_id = Column(String(50), unique=True, nullable=False) # Unique identifier, core for deduplication
    version = Column(Integer, default=1)
    title = Column(String(500))
    authors = Column(Text)
    abstract = Column(Text)
    url = Column(String(200))
    publish_date = Column(String(50)) # Paper publication date

    # Filtering / analysis information
    category = Column(String(100))        # English keywords (comma-separated)
    keywords_cn = Column(String(200))     # 🆕 Chinese keywords (comma-separated)
    my_label = Column(String(100))        # AI label: interested/irrelevant
    relevance_score = Column(Integer, default=0)
    summary_cn = Column(Text)             # Chinese abstract / summary
    is_important_author = Column(Boolean, default=False)  # Important paper flag (user-defined list / manual)
    is_famous_author = Column(Boolean, default=False)     # Famous-professor flag (LLM identified)
    famous_authors = Column(Text)         # Comma-separated list of famous-professor names identified by the LLM

    # Structured analysis (v2.0.0)
    research_content = Column(Text)       # Research content: data sources, research objects
    methods = Column(Text)                # Research methods
    discussion = Column(Text)             # Discussion and analysis
    conclusion = Column(Text)             # Conclusion

    # User notes
    notes = Column(Text)

    # Workflow control
    is_pushed = Column(Boolean, default=False)            # Whether pushed
    is_read = Column(Boolean, default=False)              # Whether read
    is_downloaded = Column(Boolean, default=False)        # Whether PDF downloaded
    is_content_analyzed = Column(Boolean, default=False)  # Whether content analysis performed
    created_at = Column(DateTime, default=datetime.datetime.now)

# Database connection config (creates arxiv.db in the current directory)
engine = create_engine('sqlite:///arxiv.db', echo=False)
SessionLocal = sessionmaker(bind=engine)

def init_db():
    Base.metadata.create_all(engine)
