# AGENTS.md

## 开发流程

1. **切新分支**：改动前先开分支，不要直接改 `main`。

   ```bash
   git checkout -b feat/<简短描述>
   ```

2. **部署到容器本地测试**

   ```bash
   docker cp main.py astrbot:/AstrBot/data/plugins/astrbot_plugin_rule_injector/main.py
   docker restart astrbot
   ```

   重启后看日志确认加载无报错，然后实际对话验证。

3. **测试完合并分支**

   ```bash
   git checkout main
   git merge feat/<简短描述>
   ```

## 风格指南

- 禁止修改astrbot项目源码，只能使用暴露出来的钩子
