# astrbot_plugin_rule_injector

把行为约束类规则按场景注入 system prompt，带独立的 Web 配置页面。

## 为什么需要这个插件

AstrBot 的 skill 机制是「渐进披露」：注入给模型的只有技能的 `name` 和 `description`，正文需要模型主动读取 `SKILL.md` 才能看到。

这对「任务型」技能没问题——问「怎么传话」时模型会去读。

但对「每条消息都要遵守」的行为约束不适用。模型不会因为「现在在群聊里说话」就主动去读一个技能文件，所以这类规则写在 skill 里往往不生效。

反过来，全塞进人格又会让每轮 prompt 变得臃肿，且无法按场景区分。

这个插件补上中间那层：**在 `on_llm_request` 阶段把规则无条件拼进 `system_prompt`，每条规则可单独开关、可指定生效范围。**

## 功能

- 每条规则可独立命名、编辑内容
- 生效范围：`仅群聊` / `仅私聊` / `通用`
- 单条启用 / 停用
- 拖拽调整顺序（顺序即注入顺序）
- 独立的 Web 页面，列表 + 侧滑抽屉编辑
- 保存后立即生效，无需重启

## 安装

```bash
cd AstrBot/data/plugins
git clone <this-repo> astrbot_plugin_rule_injector
```

或者下载压缩包解压到 `AstrBot/data/plugins/astrbot_plugin_rule_injector/`，然后重启 AstrBot。

## 使用

插件详情页 → **规则（rules）** 标签。

页面里可以：

1. 点「+ 新增规则」创建
2. 点任意一行打开侧滑抽屉，编辑名称、范围、内容
3. 抽屉里点「保存」落盘这一条
4. 主页勾选框切换启用状态
5. 拖左侧 `⋮⋮` 手柄调整顺序
6. 点主页「保存」落盘启用状态

## 配置存储

```json
{
  "rules": [
    {
      "id": "a1b2c3d4",
      "name": "群聊收敛",
      "enabled": true,
      "scope": "group",
      "content": "群聊规则正文..."
    }
  ]
}
```

`scope` 取值：`group` / `private` / `all`。

多条规则按数组顺序用空行拼接，追加到 `system_prompt` 末尾。

## 注入时机

```python
@filter.on_llm_request(priority=-1000)
```

`priority=-1000` 在多数插件之后执行（越小的数字越先执行），所以规则位于 `system_prompt` 的**最末尾**——模型生成回复时最后读到，权重较高。

如果和其他插件的注入位置冲突，可以调整这个优先级。

## 已知限制

- **不能插入对话历史中间**：AstrBot 的 `system_prompt` 是整块字符串，只支持追加到末尾。SillyTavern 那种 `injection_depth` 的能力做不到。
- **不做关键词触发**：只按场景（群聊 / 私聊）区分，不是「提到某个词才注入」。需要关键词触发的场景请用世界书类插件。
- **规则上限**：默认 10 条，改 `main.py` 里的 `MAX_RULES` 可调整。

## 环境

- AstrBot `>=4.0.0,<5`
- 平台：不限。插件基于 AstrBot 的 `MessageType` 枚举判断会话类型，不依赖特定适配器。

## License

MIT
