"""ZCode 上游接入（tech-design v2.0 §17 / PRD Q27）。

- crypto：`enc:v1` 加解密
- dataroot：整根隔离（ZCODE_DATA_BASE_DIR + 三件套）+ 设备 ID + 进程控制
- store：账号存储 + 导入（设备 ID 冲突 3 选项）
- oauth / auth / quota / claim：M4-3/M4-4/M5 阶段
"""
