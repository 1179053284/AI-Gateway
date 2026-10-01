"""model_gateway.stats：统计与日志（tech-design §4.8）。

- events：请求事件 JSONL 流水（按天分文件 + 单写队列串行化）
- aggregate：日聚合（按天单文件）+ 看板查询
"""
