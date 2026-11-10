from types import SimpleNamespace

import pytest
from renderer_client import RenderRejected, RenderUnavailable

from miner404.budget import worst_case, call_credits
from miner404.pipeline import Pipeline, CallFailed, GENERATE_MAX_OUTPUT, SELECT_MAX_OUTPUT, ASTRA_MAX_OUTPUT, EFFORT_MAX_OUTPUT
from miner404.versions import ACTIVE_PLAN


def test_plan_spends_rewrites_on_one_deep_lineage():
    assert ACTIVE_PLAN.draft_keep==1 and len(ACTIVE_PLAN.steps)==10
    assert len(ACTIVE_PLAN.drafts)==6
    assert sum(s.rewrites[0][0]=='gpt-6-astra' for s in ACTIVE_PLAN.steps)==3


@pytest.mark.parametrize('model,cap', [('gpt-6-astra',ASTRA_MAX_OUTPUT),
    ('gpt-6.1-sol',GENERATE_MAX_OUTPUT),('gpt-6.1-sol',SELECT_MAX_OUTPUT),
    ('gpt-6.1-sol',EFFORT_MAX_OUTPUT['xhigh'])])
def test_reservation_covers_the_real_requested_output_limit(model,cap):
    assert worst_case(model,3000,2,cap)==call_credits(model,7000,cap)


def test_rejected_postprocessing_preserves_valid_parent():
    seen=[]
    def render(source,options):
        seen.append(source)
        if source=='postprocessed':raise RenderRejected('{"error":"resource rejection"}')
        return b'png'
    pipeline=object.__new__(Pipeline)
    pipeline.renderer=SimpleNamespace(render=render)
    assert pipeline.validated_final('postprocessed','parent','parent')=='parent'
    assert seen==['postprocessed','parent','parent']


def test_final_render_infrastructure_failure_is_not_a_candidate_rejection():
    def render(*args):raise RenderUnavailable('service unavailable')
    pipeline=object.__new__(Pipeline);pipeline.renderer=SimpleNamespace(render=render)
    with pytest.raises(RenderUnavailable):pipeline.validated_final('new','parent')


def test_no_invalid_final_candidate_is_reported_as_success():
    def render(*args):raise RenderRejected('{"error":"resource rejection"}')
    pipeline=object.__new__(Pipeline);pipeline.renderer=SimpleNamespace(render=render)
    with pytest.raises(CallFailed):pipeline.validated_final('new','parent')
