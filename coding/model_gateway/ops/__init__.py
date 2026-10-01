"""运营调度模块（tech-design v2.0 §16 / PRD Q26-② Q27-④）。

🔴 **与核心调度解耦**：运营接口是产品专属业务接口，**不是 OpenAI 兼容 API 的组成部分**
→ 独立模块，**不进 `core/scheduler.py`**、**不进 `Resource` 主流程**（§16.1）。

🔴 **硬边界**（§16.6）：
  - `ops/` **不 import** `core/scheduler`（避免复用其重试/冷却/C 计数语义）
  - `ops/` **不 import** `core/errors.ErrorClassifier`
    （它会把 ZCode 的 `HTTP 400 + code 1003` 判成 `BAD_REQUEST`，与 §16.3 教训 2 直接冲突）

边界一句话：**`upstream/` 负责"怎么调上游"，`ops/` 负责"什么时候调、怎么批量、结果怎么归类"。**
"""
