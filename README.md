# astrbot_plugin_rule_injector

把行为约束类规则按场景注入 system prompt，带独立的 Web 配置页面。

## 这个插件做什么

在每次 LLM 请求前把行为约束类规则按场景（群聊 / 私聊）拼进 `system prompt`。每条规则可单独开关、可指定生效范围，保存后立即生效，无需重启。

规则按 AstrBot 的**配置档案**隔离：每个档案有独立的一套规则、思维链和示例场景。在 AstrBot「配置档案」页把群或好友绑定到某个档案，该会话就自动使用为此档案配置的规则；切换绑定后无需重启。未绑定的会话走默认档案，档案之间互不继承——某档案没配规则就不注入。

另外提供自定义思维链：由你指定关键词，角色回复前先写一段内心活动，聊天窗口只显示正文，思考内容保留在会话记录里，下一轮仍看得到。

## 功能

- 每条规则可独立命名、编辑内容
- 生效范围：`仅群聊` / `仅私聊` / `通用`
- 单条启用 / 停用
- 拖拽调整顺序（顺序即注入顺序）
- 自定义思维链：条数、标签名和内容都跟着配置走
- 「示例与预览」页集中填写示例，并可预览实际注入内容
- 独立的 Web 页面，列表 + 侧滑抽屉编辑
- 保存后立即生效，无需重启

## 安装

```bash
cd AstrBot/data/plugins
git clone <this-repo> astrbot_plugin_rule_injector
```

或者下载压缩包解压到 `AstrBot/data/plugins/astrbot_plugin_rule_injector/`，然后重启 AstrBot。

## 使用

插件详情页 → **规则配置** 标签。页面顶部有「配置档案」下拉框：

1. 先在 AstrBot「配置档案」页建好档案，并把会话（群 / 好友）绑定到对应档案
2. 在本页下拉框选中该档案，下面的规则、思维链、示例都是它的独立配置
3. 切换下拉框即切换正在编辑的档案，未保存的草稿会提示丢弃

选中档案后，页面里可以：

1. 点「+ 新增规则」创建
2. 点任意一行打开侧滑抽屉，编辑名称、范围、内容
3. 抽屉里点「保存」落盘这一条
4. 主页勾选框切换启用状态
5. 拖左侧 `⋮⋮` 手柄调整顺序
6. 点主页「保存」落盘启用状态

## 配置存储

配置按档案分组存于 `profiles`，key 是 AstrBot 配置档案的文件名（`cmd_config.json` 为默认档案，`abconf_<uuid>.json` 为命名档案）：

```json
{
  "profiles": {
    "cmd_config.json": {
      "rules": [
        {
          "id": "a1b2c3d4",
          "name": "群聊收敛",
          "enabled": true,
          "scope": "group",
          "content": "群聊规则正文..."
        }
      ],
      "thought_chains": [],
      "thought_example": { "user": "", "reply": "" }
    },
    "abconf_3a0d48d8-....json": {
      "rules": [],
      "thought_chains": [],
      "thought_example": { "user": "", "reply": "" }
    }
  }
}
```

`scope` 取值：`group` / `private` / `all`。

多条规则按数组顺序用空行拼接，追加到 `system_prompt` 末尾。档案之间互不继承：某档案的桶里没有规则，该档案的会话就不注入。

`thought_chains` 存每条思维链的关键词、写法要求和示例念头，在「自定义思维链」页和「示例与预览」页分别编辑；`thought_example` 存一组示例场景的 `user`（用户提问）与 `reply`（最终回复），在「示例与预览」页填写。`user` 或 `reply` 留空时分别回退为「在吗」和「嗯？怎么了」。

顶层原有的 `rules` / `thought_chains` / `thought_example` 是旧版格式，升级时会自动迁入当前在用的档案桶，迁移后不再读取，通常不用手改。

## 已知限制

- **不能插入对话历史中间**：AstrBot 的 `system_prompt` 是整块字符串，只支持追加到末尾。SillyTavern 那种 `injection_depth` 的能力做不到。
- **不做关键词触发**：只按场景（群聊 / 私聊）区分，不是「提到某个词才注入」。需要关键词触发的场景请用世界书类插件。
- **规则上限**：默认 10 条，改 `main.py` 里的 `MAX_RULES` 可调整。

## 环境

- AstrBot `>=4.0.0,<5`
- 平台：不限。插件基于 AstrBot 的 `MessageType` 枚举判断会话类型，不依赖特定适配器。

## License

MIT
