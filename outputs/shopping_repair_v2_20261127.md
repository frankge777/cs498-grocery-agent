# Shopping v2 修复与验证记录（2026-11-27，America/Chicago）

当前实现说明见 [运行流程与 API](../docs/shopping-v2-runtime.md)。
这是开发修复与复测记录，不是多次独立重复实验或未见场景泛化结论。

## 本轮实现

1. **意图分层和来源。** 保存原始请求、原始数量单位/表达、持续硬条件、首选与条件替代。
   每项有独立 primary/fallback 阶段，不能用首选名称继续限制已授权的替代搜索。
   证据必须是实际来源文本；多个独立问题汇总后只允许一次模型修复。
2. **发现与候选审查。** 原始搜索非空但审查/硬过滤后零候选，同样允许有界扩展搜索。
   模型语义审查与程序事实校验分开。缺标签保持未知，tree_nut_free 不冒充 nut_free。
   修复后仍引用虚构商品事实的单行被隔离，不进入推荐或用户选项；其余独立有效行可继续。
3. **逐项缺货恢复。** 加购失败须由真实详情确认库存为零，才能启用用户已授权的替代规则。
   搜索阶段首次发现首选缺货也使用同一确认边界。网络错误、标签不足和数量不足不是缺货。
   用户指定商品且无规则时暂停询问；拒绝则保留未完成需求。重新考虑生成新问题 ID。
   用户延迟答复后重查首选，恢复库存则继续 primary，不凭旧库存启动替代。
4. **模型默认推荐后解释数量。** 用户无需先选搜索结果。专门模型读取原话与推荐商品包装，
   程序检查实际字段依据、正整数和同量纲算术。未知数量进入询问；解释冲突进入明确确认。
   不通过默认一件、静默修改总量或把瓶罐当等价单位来完成任务。
5. **整篮确认与差量。** 显式修改数量/预算、换商品、历史候选重新核验都重新报价确认。
   删除清单外商品与保留旧购物车分开；已在车中的目标商品不重复相加。
   缺货只重开受影响需求；其他商品、原始要求和硬条件保留。
6. **暂停恢复接口。** 新增替代授权和数量解释回答，checkpoint 保存阶段、证据、修订、
   候选历史、库存观察、数量解释及当前问题/草稿版本。旧 v1 会话显式保留兼容。

## 离线检查

`.venv/bin/python -m unittest discover -s tests -q`：**180/180 通过**。
Python 编译检查和 `git diff --check` 通过。测试不证明模型能理解所有商品。

覆盖包括：有/无替代授权、拒绝后重新考虑、首次搜索即缺货、库存恢复、
服务错误不触发替代、两项独立缺货、保留其他已加入商品、营养阈值来源、
No Salt Added 不推导 low_sodium、真实半加仑规格、未知数量、单位/包装冲突、
旧问题拒绝、整批答复先校验、历史候选刷新、改预算/数量及 HTTP 暂停恢复。

## 真实模型实验协议

- DeepSeek `deepseek-flash`，temperature=0，thinking=false；每次各案例仅运行一次。
- 冻结 Kroger 主集为 20 场景 × high/medium/low 三种表述，共 60 条。
- 使用真实 Kroger 商品快照，而非实时调用；冻结任务、商品数据和评分器未改动。
- 模型默认推荐；模拟用户接受草稿，数量问题由独立用户意图档案回答。
- 仅当数量类型冲突而模型建议精确符合独立 count/volume/weight 总量时，
  模拟用户可以明确确认该件数。包装形式冲突、仅包装数档案或不精确总量不自动批准。
- 缺货替代授权没有默认答案，必须原话已有规则或独立用户授权档案。
- 这与无交互的旧 ours/ReAct 协议不同，不能把百分比直接当成公平模型排名。

冻结输入 SHA-256：

- catalog：`2fb65e82715d6b27c079984404052c5a1e4540ac843c6c0c7c49a1d8c89bcbce`
- scenarios：`590c01667f938ab7e3509da03539b94e548906fa1da99e128af37272cfa3442e`
- quantity profiles：`f1dc17946967f8e46cadf2f14c6aa07d6efd1b54e7db81d17d97e97715372dc0`

## 开发过程中的结果（全部保留，未覆盖）

- 起始推荐版：53/60，见 [旧版记录](recommended_workflow_20261127.md)。
- `repair_v2_targeted_20261127`：9/15。发现推荐输出把已确定商品当新需求，以及嵌套上下文引用丢失路径。
- `repair_v2_interface_20261127`：5/6；修复完整上下文路径后 `repair_v2_context_20261127` 为 1/1。
- `repair_v2_full_20261127`：54/60。暴露未知数量被模型默认一件、包装与内含数量冲突、旧车策略矛盾、虚构过敏字段影响整批审查。
- `repair_v2_final_20261127`：59/60。剩余 K20 high 在一次修复里只看到首个数量错误，第二次仍引用并不存在的“Keep the bread”。
  保留严格来源校验，改为汇总独立错误交给同一次修复，没有接受虚构引文。

## 最终版本复测

最终版本运行约 8.0 分钟，估计模型成本 $0.686（脚本费率估算，不是账单）。

- **最终成功 60/60（100%）**；high、medium、low 各 20/20；基础设施失败 0。
- 60 条全部使用 schema_version=2，完成状态 complete 60 次。
- 起始失败的七个实例 K06 medium、K17 medium、K16 high、K19 medium、K20 high/medium/low 本轮全部通过。
- 首份草稿目标检查 60/60，但该指标不包含执行期交互约束；最终 60/60 使用完整原评分器。
- 全部运行合计 75 次整篮确认、26 批缺数量/必要信息澄清、3 次候选选择。
  这属于有模拟用户参与的闭环流程，不能解读为模型不询问用户独立完成 60 条。
- 本轮没有使用独立总量纠错确认；该分支仍由离线反例测试覆盖。
- 平均每条模型调用 9.45 次、工具调用 34.18 次，覆盖率 1.0，硬约束违反率 0。

原始结果：[summary](../results/repair_v2_verified_20261127/deepseek-flash/kroger/recommended/summary.json)、
[trials](../results/repair_v2_verified_20261127/deepseek-flash/kroger/recommended/trials.jsonl)、
[完整过程与会话状态](../results/repair_v2_verified_20261127/deepseek-flash/kroger/recommended/trajectories.jsonl)、
[协议、输入与代码哈希](../results/repair_v2_verified_20261127/deepseek-flash/kroger/recommended/manifest.json)。

## 对话开发与实时 API

- 四条对话开发用例已启动，但全部在首次模型请求遇到 **DeepSeek HTTP 402 Insufficient Balance**。
  本次为 **4 条基础设施失败、0 条可评分**，不能写成 0/4 的智能体准确率或 4/4 通过。
  保留 [失败运行](../results/repair_v2_dialogue_20261127/deepseek-flash/kroger/recommended/summary.json)。
  余额不足发生在最终 60 条完成后，不改变已完成主集结果。
- 受余额限制，没有继续尝试完整实时模型购物流程；旧版实时演示不能替代本版本复测。
- 另外完成不依赖 DeepSeek 的 **实时 Kroger 后端集成检查**：真实读取门店 `02100946`、
  搜索 large eggs、重新读取 UPC `0001111060903`，返回 12 ct、149 美分、有货。
  断言规格、正价格和预算后，1 个包装正确加入本地模拟车，得到 12 个鸡蛋。
  [原始检查结果](repair_v2_live_api_reads_20261127.json) 明确标记 `model_used=false`。
  这证明当前 API 连接及读取/归一化/本地车可用，不证明实时语义审查和推荐已通过。

余额恢复后待执行（必须使用新目录，不覆盖失败运行）：

```bash
.venv/bin/python scripts/run_llm_experiments.py --dataset kroger \
  --agents recommended --variants high --runs 1 --workers 3 --temperature 0 \
  --scenario-path benchmark/recommendation_dialogue_kroger_development.json \
  --user-profiles benchmark/recommendation_dialogue_user_profiles.json \
  --basket-profiles benchmark/recommendation_dialogue_user_profiles.json \
  --output-root results/repair_v2_dialogue_funded_new_run

.venv/bin/python scripts/smoke_recommended_live.py --accept \
  --output outputs/repair_v2_live_model_funded_new_run.json
```

## 已知边界

前端、任意自然语言的全量需求修订、完整永久排除管理、数据库并发锁、
跨旧 token 的强重放防护和真实账户购物车事务不在本轮完成范围。
当前修改入口为运行说明中的结构化接口；购物车为本地模拟，不会向 Kroger 真实账户加车或下单。
来源引用正确不等于语义必定正确，独立语义审查和数量解释仍可能模型误判。
子毫升/子克精确总量及不支持的营养基准需要澄清，不能据此宣称任意计量都已覆盖。
