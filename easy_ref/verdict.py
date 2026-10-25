"""Strict verdict decoding; invalid output never means approval."""
import json
import re


def unique(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError('duplicate JSON key')
        result[key] = value
    return result


def parse(message):
    try:
        value = json.loads(message, object_pairs_hook=unique)
    except json.JSONDecodeError:
        blocks = re.findall(r'```json\s*\n(.*?)\n```', message, re.S)
        if not blocks:
            raise ValueError('missing JSON verdict')
        values = [json.loads(b, object_pairs_hook=unique) for b in blocks]
        if any(v != values[-1] for v in values):
            raise ValueError('ambiguous verdict blocks')
        value = values[-1]
    if not isinstance(value, dict):
        raise ValueError('verdict must be an object')
    verdict = value.get('verdict')
    if verdict not in ('APPROVE', 'CHANGES_REQUIRED', 'NEEDS_OWNER'):
        raise ValueError('unknown verdict')
    keys = {'verdict', 'summary', 'required'}
    if verdict == 'NEEDS_OWNER':
        keys.add('owner_question')
    if set(value) != keys:
        raise ValueError('unexpected or missing verdict fields')
    if not isinstance(value['summary'], str) or not value['summary'].strip():
        raise ValueError('empty summary')
    required = value['required']
    if not isinstance(required, list):
        raise ValueError('required must be a list')
    ids = set()
    for item in required:
        if not isinstance(item, dict) or set(item) != {'id', 'what', 'evidence'}:
            raise ValueError('invalid finding fields')
        if any(not isinstance(v, str) or not v.strip() for v in item.values()):
            raise ValueError('invalid finding text')
        if item['id'] in ids:
            raise ValueError('duplicate finding id')
        ids.add(item['id'])
    if verdict == 'APPROVE' and required or verdict == 'CHANGES_REQUIRED' and not required:
        raise ValueError('required findings conflict with verdict')
    if verdict == 'NEEDS_OWNER' and (not isinstance(value['owner_question'], str) or not value['owner_question'].strip()):
        raise ValueError('missing owner question')
    return value
