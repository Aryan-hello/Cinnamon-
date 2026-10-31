import asyncio
import json
from cinnamon_modules.brain_intent import IntentPlan, plan_intent
from cinnamon_modules.brain_intent_ai import parse_intent_suggestion, classify_intent_with_fallback

def test_parse_valid_suggestion():
    item = parse_intent_suggestion(json.dumps({'intent':'private_data','confidence':0.91,'phrase':'my balance'}))
    assert item is not None and item.intent == 'private_data' and item.confidence == 0.91

def test_parse_fenced_json():
    item = parse_intent_suggestion('```json\n{"intent":"help","confidence":0.9,"phrase":"help"}\n```')
    assert item and item.intent == 'help'

def test_reject_invalid_unknown_low_confidence_and_oversized():
    assert parse_intent_suggestion('not json') is None
    assert parse_intent_suggestion('{"intent":"execute_shell","confidence":1,"phrase":"x"}') is None
    assert parse_intent_suggestion('{"intent":"private_data","confidence":0.4,"phrase":"balance"}') is None
    assert parse_intent_suggestion('{"intent":"help","confidence":0.9,"phrase":"' + ('x' * 300) + '"}') is None

def test_fallback_only_called_for_chat_plan():
    async def run():
        calls=[]
        async def model(prompt):
            calls.append(prompt)
            return '{"intent":"private_data","confidence":0.95,"phrase":"my balance"}'
        deterministic=plan_intent('how stacked am I')
        result=await classify_intent_with_fallback('how stacked am I', deterministic_plan=deterministic, model_call=model)
        assert deterministic.intent == 'chat' and result.intent == 'private_data' and len(calls)==1
        known=IntentPlan('help','deterministic',('help','chat'))
        assert await classify_intent_with_fallback('help me',deterministic_plan=known,model_call=model) is known
        assert len(calls)==1
    asyncio.run(run())

def test_model_failure_returns_deterministic_plan():
    async def run():
        original=plan_intent('how stacked am I')
        async def broken(prompt): raise TimeoutError('offline')
        assert await classify_intent_with_fallback('how stacked am I',deterministic_plan=original,model_call=broken) is original
    asyncio.run(run())
