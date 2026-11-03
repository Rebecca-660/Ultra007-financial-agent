"""Framework-independent human review input for CLI and a future web client."""
from pathlib import Path

from .models import Dataset, digest
from .research_models import HumanReview


def review_template(dataset: Dataset) -> dict:
    return {'schema_version':'finance-human-review-v1','confirmed_by':'',
            'source_checked':False,'statement':'',
            'review':{'dataset_fingerprint':dataset.fingerprint,'report_set_id':dataset.report_set_id,
                      'decisions':[{'statement_id':s.statement_id,'statement_digest':digest(s),
                                    'decision':'pending','reviewer':'','conflict_resolution':'',
                                    'note':'','corrections':[]} for s in dataset.statements]}}


def import_human_review(path: Path, dataset: Dataset, report_set):
    from .analysis import effective_statements
    from .research_io import read_json
    from .review import assert_sources
    raw=read_json(path)
    if raw.get('source_checked') is not True:
        raise ValueError('必须由用户明确确认已核对原年报。')
    submission=HumanReview.model_validate(raw)
    for decision in submission.review.decisions:
        if decision.reviewer!=submission.confirmed_by:
            raise ValueError('审核决定中的审核人须与提交人一致。')
        if decision.decision!='approved' and decision.corrections:
            raise ValueError('未批准的表不能提交已生效的修正。')
        if any(not c.reason.strip() for c in decision.corrections):
            raise ValueError('修正理由不能为空白。')
    assert_sources(dataset,report_set)
    effective_statements(dataset,submission.review)
    return submission.review
