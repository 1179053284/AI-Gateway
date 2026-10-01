"""model_gateway.core：核心层（tech-design §4.2/§4.3/§4.6）。

- ir：内部标准请求/响应/流事件模型（协议中间表示）
- scheduler：§5 调度状态机（选路/重试 m/切换续跑/兜底）
- resources：资源池/生效集/冷却/连续失败计数（懒恢复）
- errors：错误分类器（FR-3.13）
- cancel：取消注册表与透传
"""
