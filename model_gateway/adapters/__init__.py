"""model_gateway.adapters：出站适配层（tech-design §4.4）。

- base：适配器接口（M1 任务 3）
- openai_out：OpenAI 兼容出站，商汤首发（M1 任务 3；含 kimi-k3 URL→b64 转换 §8-15）
- anthropic_out / gemini_out：P1 / P2
"""
