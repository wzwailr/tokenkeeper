"""tokenkeeper × minimax 验证（key 从环境变量读）。"""
import sys, os, time, requests

# key 从环境变量读（完整 key 由用户在外面设置）
api_key = os.environ.get('MINIMAX_API_KEY', '')
print(f'key 长度: {len(api_key)} chars')
if not api_key:
    print('❌ 请先设置 MINIMAX_API_KEY 环境变量')
    sys.exit(1)

sys.path.insert(0, r'D:\aiCode\Hermes\aiTest\ai-agent-governance\tokenkeeper')

base = 'https://api.minimaxi.com/v1'
demo_db = r'D:\aiCode\Hermes\aiTest\ai-agent-governance\tokenkeeper\examples\minimax_real.db'
# 注意：不再重置 DB，保留历史数据
# if os.path.exists(demo_db):
#     os.remove(demo_db)

from tokenkeeper import guard
from tokenkeeper.ledger import Ledger
from tokenkeeper.pricing import calculate_cost

os.environ['TOKENKEEPER_DB'] = demo_db
guard.install(db_path=demo_db, project='minimax-demo', user='tester')

prompts = [
    '用一句话介绍 Python',
    '9*9 等于几？',
    '列出 3 种水果',
    '把 hello 翻译成中文',
    '讲个笑话',
]

print(f'\n=== 连续 {len(prompts)} 次真实 minimax M3 调用 ===\n')

total_cost = 0
for i, prompt in enumerate(prompts, 1):
    t0 = time.time()
    r = requests.post(
        f'{base}/chat/completions',
        headers={'Authorization': f'Bearer {api_key}', 'Content-Type': 'application/json'},
        json={'model': 'MiniMax-M3', 'messages': [{'role': 'user', 'content': prompt}]},
        timeout=30,
    )
    elapsed = (time.time() - t0) * 1000
    if r.status_code == 200:
        data = r.json()
        usage = data['usage']
        cost = calculate_cost('MiniMax-M3', usage['prompt_tokens'], usage['completion_tokens'])
        guard.record(
            model='MiniMax-M3',
            prompt_tokens=usage['prompt_tokens'],
            completion_tokens=usage['completion_tokens'],
            cost_usd=cost.cost_usd,
            cost_cny=cost.cost_cny,
            latency_ms=elapsed,
            provider='minimax',
        )
        total_cost += cost.cost_usd
        print(f'  ✅ [{i}] HTTP {r.status_code} ({elapsed:.0f}ms)  in={usage["prompt_tokens"]} out={usage["completion_tokens"]}  ${cost.cost_usd:.6f}')
        print(f'      reply: {data["choices"][0]["message"]["content"][:60]!r}')
    else:
        print(f'  ❌ [{i}] HTTP {r.status_code}: {r.text[:80]}')

guard.uninstall()
print(f'\n总成本: ${total_cost:.6f}')
print(f'DB: {demo_db}')

ledger = Ledger(demo_db)
print(f'\n账本共 {ledger.count()} 条记录')
for row in ledger.summary(group_by='model'):
    print(f'  {row["group_key"]}  calls={row["calls"]}  cost=${row["cost_usd"]:.6f}')
ledger.close()