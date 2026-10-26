import json
from types import SimpleNamespace

import pytest

from app.domain.models import ArticleDocument, ArticleSection, VisualItem, VisualPlan
from app.services.knowledge import KnowledgeResults
from app.skills.visual_planning import VisualPlanningSkill


def gallery():
    return KnowledgeResults.model_validate({'images': [
        {'id': f'{i:032x}', 'name': f'粘贴图片-{i}.png', 'folder_name': folder,
         'mime': 'image/png', 'width': 1280, 'height': 1891, 'size': 100}
        for i, folder in enumerate(['蟹教授', '藻教授', *['鱼教授'] * 5], start=1)
    ]})


class Knowledge:
    async def search(self, *args, **kwargs):
        return gallery()


class ExternalPlanner:
    payload = None

    async def generate_structured(self, *, user, **kwargs):
        self.payload = json.loads(user)
        return SimpleNamespace(data=VisualPlan(items=[
            VisualItem(kind=kind, source='ai_generated', provider='planned',
                       placement='正文', purpose='文章配图', prompt_or_source='generated diagram',
                       caption='AI示意图')
            for kind in ['cover', 'concept', 'concept', 'concept']
        ]))


@pytest.mark.asyncio
async def test_anonymous_product_folder_images_take_priority_in_cover_and_body():
    model = ExternalPlanner()
    article = ArticleDocument(titles=['认识鱼教授'],
                              selected_title='认识鱼教授：从双源成分到田间观察',
                              digest='产品介绍', audience='种植户', ending='行动清单',
                              sections=[ArticleSection(type='figure', caption='产品介绍')])
    plan = await VisualPlanningSkill(model, knowledge=Knowledge()).run(
        article, {'ai_generation_available': True, 'cover_count': 1, 'inline_image_count': 3},
    )
    expected = {v.id for v in gallery().images if v.folder_name == '鱼教授'}
    assert len(plan.items) == 4
    assert all(v.source == 'knowledge_base' for v in plan.items)
    assert all(v.knowledge_image_id in expected for v in plan.items)
    assert len({v.knowledge_image_id for v in plan.items}) == 4
    assert all(v.provider == 'planned' for v in plan.items)
    assert {v['folder_name'] for v in model.payload['context']['knowledge_images']} == {'鱼教授'}
    assert all('AI示意图' not in (v.caption or '') for v in plan.items)


@pytest.mark.asyncio
async def test_unrelated_product_gallery_does_not_replace_external_illustrations():
    article = ArticleDocument(titles=['稻田管理'], selected_title='稻田水肥管理', digest='田间管理',
                              audience='种植户', ending='记录',
                              sections=[ArticleSection(type='figure', caption='稻田')])
    plan = await VisualPlanningSkill(ExternalPlanner(), knowledge=Knowledge()).run(
        article, {'ai_generation_available': True},
    )
    assert all(v.source == 'ai_generated' for v in plan.items)


@pytest.mark.asyncio
async def test_review_draft_uses_matching_gallery_without_model_calls():
    class NoModel:
        async def generate_structured(self, **kwargs):
            pytest.fail('review-draft gallery must not call a model')
    article = ArticleDocument(titles=['鱼教授'], selected_title='认识鱼教授', digest='介绍',
                              audience='种植户', ending='记录',
                              sections=[ArticleSection(type='paragraph', content='产品介绍')])
    skill = VisualPlanningSkill(NoModel(), knowledge=Knowledge())
    plan = await skill.local_plan(article, {'cover_count': 1, 'inline_image_count': 3})
    assert len(plan.items) == 4
    assert all(v.source == 'knowledge_base' for v in plan.items)
    assert len({v.knowledge_image_id for v in plan.items}) == 4
    assert all('鱼教授' in v.caption for v in plan.items)
    unrelated = article.model_copy(update={'selected_title': '水稻管理'})
    assert not (await skill.local_plan(unrelated)).items
