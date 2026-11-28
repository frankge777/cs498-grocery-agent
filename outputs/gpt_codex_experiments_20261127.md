# GPT / Codex 实际实验记录（2026-11-27，America/Chicago）

已接通并实际调用 `gpt-6-sol`，通过本机已登录的 Codex CLI，reasoning_effort=low。
不是把 DeepSeek 输出重命名，也没有把当前开发聊天提供给模型代答。
复现命令和适用范围见 [GPT 实验说明](../docs/gpt-experiments.md)。

## 代码与离线验证

- 新增 `CodexCLIClient` 与 `create_llm(provider=...)`。
- 实验脚本与实时演示脚本支持 `--provider codex --model gpt-6-sol`。
- 正常使用已保存的 CLI 登录，不读取/复制登录 token，不需要项目 OpenAI API key。
- 每次新建空临时工作目录、独立 ephemeral 会话，忽略用户 CLI 配置和项目说明，
  禁用 shell/搜索等；出现工具/文件操作事件即拒绝结果。
- 子进程环境不传入商家 key、DeepSeek key 或项目 session secret。
- 保留原状态机、商品工具、事实校验、模拟用户与评分器。
- **188/188 离线测试通过**，包括原 180 条与 8 条新的传输/隔离/错误分类测试。
- CLI 版本：`0.171.0-alpha.13`。模型温度、4096 输出 token 上限、API 费用均不作等价承诺；
  相应元数据为 null，不按 DeepSeek 费率计费。

## 四条对话开发用例：1/4 完成，0 基础设施失败

全部仅运行 high 表述一次，耗时约 173 秒，2 个并发实验。

- **RD01 完成**：一条面包、总计 12 个鸡蛋，整篮确认与最终验证通过，价格 $3.28。
- **RD02 暂停**：用户酸奶数量未知的场景，但胡萝卜包装先出现资料不足，未进入最终确认。
- **RD03 暂停**：原计划检查用户偏好触发局部替换，但在胡萝卜包装澄清处暂停，未实际覆盖偏好替换分支。
- **RD04 暂停**：原计划检查已有购物车差量与恢复，但在胡萝卜包装澄清处暂停，不能将该分支算作验证通过。

后三条的共同原话都要求“一袋胡萝卜”。推荐的真实快照商品：

- UPC：`0001111091620`。
- 名称：`Kroger® Cut and Peeled Baby Carrots`。
- `raw_size`：`16 oz`。

专门数量模型返回 `insufficient_product_data`：规格证明重量，却未证明外包装是袋。
问题例如 `Is this 16 oz unit packaged as a bag?`。独立模拟用户只保存数量/偏好，
没有这一包装事实，也没有接受其他包装形式的授权，因此停止为 `quantity_review_unavailable`。
程序没有编造“袋装”，没有默认授权，也没有把暂停计成成功。

这是商品信息与模拟用户覆盖不足导致的未完成，不能直接推断 GPT 比 DeepSeek 更差。
评分器照常记成功 1/4；其中 RD04 暂停时原有购物车 $5.07 超过任务 $5 预算，
所以该运行也有预算/硬约束未满足。不能把安全暂停等同于全部目标已满足。

后续处理应补充有真实来源的包装形式，或者让真实用户明确是否接受所展示的包装。
如果扩展模拟用户，必须另行提供独立的授权/事实档案并标记新协议，不能默认回答“是”。
本轮不改冻结商品/任务答案来提升通过率。

结果：[summary](../results/gpt_codex_dialogue_20261127/codex-gpt-6-sol/kroger/recommended/summary.json)、
[逐条评分](../results/gpt_codex_dialogue_20261127/codex-gpt-6-sol/kroger/recommended/trials.jsonl)、
[会话与问题](../results/gpt_codex_dialogue_20261127/codex-gpt-6-sol/kroger/recommended/trajectories.jsonl)、
[协议及代码哈希](../results/gpt_codex_dialogue_20261127/codex-gpt-6-sol/kroger/recommended/manifest.json)。

## 真实 Kroger + GPT 完整本地演示：通过

请求：`Buy exactly 12 large chicken eggs in total under $5, nothing else.`

真实门店：`02100946`。商品来源 `kroger_live`，UPC `0001111060903`，
12 ct，149 美分，有货。流程返回：

```text
awaiting_basket_confirmation → 脚本显式接受本地草稿 → complete
```

最终车为 `{ "0001111060903": 1 }`，总价 $1.49；最终验证 `ok=true`、violations=[]。
演示确实调用 GPT 进行意图、候选审查、推荐和数量解释，之后通过 HTTP 服务的 start/resume 恢复。
`--accept` 只接受这次本地演示的草稿，不调用 Kroger 真实账户购物车或下单接口。

[完整实时记录](gpt_codex_live_20261127.json)。

## 不应混淆的范围

完整冻结 60 条主集尚未用 GPT 重跑。先前 60/60 属于 DeepSeek 实验。
本轮 GPT 的 1/4 是独立开发集结果，不是 GPT 主集准确率。
CLI 包装消息的方式、系统指令、推理/采样/输出长度与直接 API 调用不同，
使用 `codex-json-inference-v1` 标签，不作受控模型横向排名。
CLI 登录状态和模型额度依赖本机账号；这不是可直接部署到网站的 API 凭证。
当前 CLI 适配器仅支持 JSON 交互/推荐流程，不支持原生函数调用基线。
