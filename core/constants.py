# -*- coding: utf-8 -*-
"""插件常量集中定义，供入口、core 与 api 各模块共用。"""

PLUGIN_NAME = "astrbot_plugin_rule_injector"
MAX_RULES = 10
MAX_THOUGHT_CHAINS = 5
MAX_NAME_CHARS = 60
MAX_KEYWORD_CHARS = 12
MAX_CONTENT_CHARS = 20000
MAX_EXAMPLE_THOUGHT_CHARS = 500
MAX_EXAMPLE_USER_CHARS = 500
MAX_EXAMPLE_REPLY_CHARS = 500
SCOPES = ("group", "private", "all")

# 老配置迁移完成的标记，避免每次启动都重迁
MIGRATED_KEY = "_profiles_v1"
DEFAULT_PROFILE_KEY = "cmd_config.json"

# 用户没配置 thought_example 时的回退示例，与改前行为一致
DEFAULT_EXAMPLE_USER = "在吗"
DEFAULT_EXAMPLE_REPLY = "嗯？怎么了"

# 新增思维链时预填的内容。与 _conf_schema.json 里的默认值保持一致。
DEFAULT_THOUGHT_RULE = (
    "这里是你的内心想法：写得比说话长、可以写自己的反应、"
    "可以在心里复述他说的话、可以没头没尾，使用第一人称，"
    "别跳出来评价自己演得像不像。"
)
