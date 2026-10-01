"""model_gateway.api：入站层（tech-design §4.1）。

- openai_compat：/v1/models · /v1/chat/completions · /v1/images/generations（M1 任务 3/8）
- anthropic：/v1/messages（M1 任务 7）
- admin：/admin/api/* 管理 CRUD + 统计/日志查询（M1 任务 9；Q18-① 免鉴权）
- auth：访问令牌校验中间件，仅 /v1/* 生效（Q18-①：自用系统去掉管理令牌）
"""
