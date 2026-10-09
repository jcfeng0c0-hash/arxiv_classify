"""Persist classification independently from optional detailed analysis."""
from src.classification_policy import VERSION


def apply_analysis_result(paper, result):
    paper.my_label = result['Type']
    paper.classification_version = result.get('classification_version', VERSION)
    paper.classification_rule = result.get('rule', '')
    completed = result.get('details_complete', result['Type'] == 'interested')
    paper.is_content_analyzed = bool(completed)
    paper.analysis_error = result.get('detail_error')
    if completed:
        for field, key in [('summary_cn', 'Abstract_CN'),
                           ('research_content', 'research_content'), ('methods', 'methods'),
                           ('discussion', 'discussion'), ('conclusion', 'conclusion')]:
            setattr(paper, field, result.get(key, ''))
        paper.category = ', '.join(result.get('keywords', []))
        paper.keywords_cn = ', '.join(result.get('keywords_CN', []))
    else:
        # A revised paper must not show detailed conclusions from its old version.
        for field in ('summary_cn', 'research_content', 'methods', 'discussion', 'conclusion', 'keywords_cn'):
            setattr(paper, field, '')
