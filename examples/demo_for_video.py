"""tokenkeeper 演示脚本——录视频用。

录制流程：
1. 打开本文件
2. 一段一段执行（每段等镜头跟到）
3. 浏览器同时开 http://localhost:8501 看效果
"""

# ====================================================================
# 第一段：5 行接入
# ====================================================================

# from tokenkeeper import guard
#
# guard.install(project="my-ai-app", user="me")
# guard.set_budget(daily_limit_usd=10.0, action="block")
#
# print("✅ tokenkeeper 已启动")
# print("   看板: http://localhost:8501")


# ====================================================================
# 第二段：模拟日常 LLM 调用
# ====================================================================

# import time
# from tokenkeeper.pricing import calculate_cost
#
# # 模拟一周的使用
# daily_calls = [
#     ("gpt-4o", 1500, 800),         # 早上写代码
#     ("claude-sonnet-4", 3000, 1500),  # 中午 debug
#     ("deepseek-chat", 2000, 800),  # 下午便宜模型
# ]
#
# for model, prompt_t, completion_t in daily_calls:
#     cost = calculate_cost(model, prompt_t, completion_t)
#     guard.record(
#         model=model,
#         prompt_tokens=prompt_t,
#         completion_tokens=completion_t,
#         cost_usd=cost.cost_usd,
#         cost_cny=cost.cost_cny,
#         latency_ms=1200,
#     )
#     print(f"   ✓ {model}  ${cost.cost_usd:.4f}")
#
# time.sleep(2)  # 给看板刷新留时间


# ====================================================================
# 第三段：戏剧时刻——触发预算熔断
# ====================================================================

# # 把 daily_limit_usd 改成 $0.05（极低）
# guard.set_budget(daily_limit_usd=0.05, action="block")
#
# # 现在已有 $0.027 花费，再调一次就超
# try:
#     guard.record(
#         model="claude-opus-4",  # 最贵的
#         prompt_tokens=5000,
#         completion_tokens=2000,
#         cost_usd=0.15,  # 直接设大额
#         cost_cny=1.08,
#     )
#     print("调用成功")
# except Exception as e:
#     print(f"🛑 调用被阻断: {e}")
#     print("✅ AI 自动停了，不会再烧钱")


# ====================================================================
# 第四段：对比国产模型（国内友好）
# ====================================================================

# # 同样任务，用不同模型
# print("=== 同一任务，5 个模型的成本对比 ===\n")
# task = (3000, 1500)  # prompt, completion
# for model in ["claude-opus-4", "claude-sonnet-4", "gpt-4o", "qwen-plus", "deepseek-chat"]:
#     cost = calculate_cost(model, *task)
#     print(f"  {model:20s}  ${cost.cost_usd:.4f}  ¥{cost.cost_cny:.4f}")


# ====================================================================
# 录制说明
# ====================================================================
#
# 录制时按上面的分段，每段执行一次（解开注释，运行）
# 浏览器同时打开 http://localhost:8501 看效果
#
# 关键镜头：
# - 5 行代码录下来（5 秒）
# - 浏览器看 KPI 跳动（3 秒）
# - 触发熔断那一刻（重点！3 秒）
# - 模型对比表格（5 秒）