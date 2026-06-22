import json

lines = []
with open('C:/Users/ru\'bin/.gemini/antigravity/brain/2506e3dc-2c74-42f5-b46f-6cef4ade5e6d/.system_generated/logs/transcript.jsonl', encoding='utf-8') as f:
    for line in f:
        if '"tool_calls"' in line:
            lines.append(json.loads(line))

writes = []
for step in lines:
    for tc in step.get('tool_calls', []):
        if tc['name'] == 'write_to_file' and 'tasks.py' in tc['args'].get('TargetFile', ''):
            writes.append(tc['args']['CodeContent'])

print(f'Found {len(writes)} writes')
for i, w in enumerate(writes):
    with open(f'C:/Users/ru\'bin/tasks_write_{i}.py', 'w', encoding='utf-8') as f:
        f.write(w)
