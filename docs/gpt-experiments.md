# 使用已登录的 Codex / GPT 运行购物实验

实验与实时演示脚本增加 `--provider codex`。实际模型默认 `gpt-6-sol`，
可以用 `--model` 指定账户可用模型；`--reasoning-effort` 默认 low。
原 DeepSeek 后端保留，HTTP 服务的默认模型配置没有在本轮改动。

## 如何调用

先确认本机已安装 Codex CLI，并正常登录：

```bash
codex login status
# 未登录时在本机执行 codex login，按官方登录流程完成。
```

不需要从登录文件复制 access token，也不需要把聊天登录凭证当成 API key。
本项目只通过官方 `codex exec` 使用现有登录；账号仍受其模型权限和用量限制。
另一台机器、CI 或托管网站不能因为本机已登录就自动获得授权。

四条对话开发用例：

```bash
.venv/bin/python scripts/run_llm_experiments.py \
  --provider codex --model gpt-6-sol --reasoning-effort low \
  --dataset kroger --agents recommended --variants high --runs 1 --workers 2 \
  --scenario-path benchmark/recommendation_dialogue_kroger_development.json \
  --user-profiles benchmark/recommendation_dialogue_user_profiles.json \
  --basket-profiles benchmark/recommendation_dialogue_user_profiles.json \
  --output-root results/gpt_codex_dialogue_new_run
```

实时 Kroger 商品与本地车：

```bash
.venv/bin/python scripts/smoke_recommended_live.py \
  --provider codex --model gpt-6-sol --accept \
  --output outputs/gpt_codex_live_new_run.json
```

完整冻结主集（这个命令是运行方式，不表示本轮已跑完 GPT 60 条）：

```bash
.venv/bin/python scripts/run_llm_experiments.py \
  --provider codex --model gpt-6-sol --dataset kroger \
  --agents recommended --runs 1 --workers 2 \
  --output-root results/gpt_codex_main_new_run
```

原 DeepSeek 命令仍默认可用，也可显式传 `--provider deepseek`。
不同实验请使用新目录，不覆盖旧成绩。

## 程序如何运行

1. `create_llm` 创建 `CodexCLIClient`，现有状态机仍调用 `llm.chat(...)`。
2. 适配器把当前步骤的 system/user/assistant 消息序列编码为 JSON，交给独立 CLI 会话。
   这里不会把当前开发聊天、隐藏评分目标或参考购物车附加给模型。
3. 每次使用新的空临时目录、`--ephemeral`、只读模型沙箱、`--ignore-user-config`，
   禁用 shell、搜索、图片、项目说明读取等，不恢复其他会话。
   子进程不继承 Kroger、DeepSeek key 或项目 session secret。
4. GPT 返回 JSON；程序继续原有 UPC、证据、标签、数量、预算等校验，再决定状态流转。
   商家工具和购物车操作仍由既有程序执行。CLI 结果中若出现工具/文件操作事件，拒绝结果。
5. 记录 CLI `turn.completed` 的实际 token 用量，一次调用记作一次模型调用。
   登录/超时/CLI 失败与模型 JSON 错误分开统计；不会静默退回 DeepSeek。

本适配器支持 `recommended` 和 `interactive` 的 JSON 工作流。
旧 ReAct / Direct FC / ours 原生函数调用协议尚未适配到 CLI，参数不兼容时直接拒绝。
若要在托管服务使用 GPT API，需另接正式 API 客户端和相应服务端凭证。

## 如何解释结果

这调用的是所指定的 GPT 模型，而不是让拥有开发历史的当前聊天代答。
CLI 自带系统指令和额外 token 开销，项目消息是在 CLI 提示中封装的；
温度和 DeepSeek 的 4096 输出 token 上限没有在 CLI 中等价设置。
因此使用单独的 `codex-json-inference-v1` 标记，不宣称是受控的 API 模型横向比较。

`temperature`、`max_tokens`、`api_cost_usd` 在 CLI 模型元数据中为 null；
脚本不使用 DeepSeek 单价估算 GPT 费用，也不把订阅用量解释为免费或无限。
先前的 DeepSeek 60/60 不会改名成 GPT 成绩。开发用例也不能当作完整主集准确率。

官方依据：
[非交互运行与 JSONL](https://developers.openai.com/codex/noninteractive/)、
[认证方式](https://developers.openai.com/codex/auth/)、
[配置参考](https://developers.openai.com/codex/config-reference/)。
