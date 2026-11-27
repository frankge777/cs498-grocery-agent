# 推荐购物篮第一阶段：实现与验证结果

日期：2026-11-27。Benchmark 使用真实 Kroger Mt Zion 冻结快照；
单独的实时演示读取 Kroger Public API。购物车操作始终为本地模拟，真实账户与下单未接入。

## 最终版本、充值后验证

- 完整兼容性实验：**53/60 = 88.3%**，无基础设施错误。high 18/20、medium 16/20、low 19/20。
  结果：`results/recommended_kroger_post_topup_20261127/`，耗时约 360 秒。
  20 个场景各 3 种表述、每个实例仅 1 次运行，temperature=0、workers=3。
  首版推荐生成 58/60，这 58 条均满足首版目标检查；2 条未生成推荐，不能把该条件通过率当 60 条总体准确率。
  首版检查不含执行交互谓词，最终 53/60 使用完整原评分器。
  共 101 次问题/确认批次、127 个问题/确认；默认接受推荐，不测试私有偏好。
- 交互开发实验：**4/4**，无基础设施错误。
  `results/recommended_dialogue_post_topup_20261127/`，共 7 次交互批次、7 个问题/确认、1 次局部替换。
  RD02 实际补问数量；RD03 实际执行一次 Greek 酸奶替换；RD04 调整已有购物车。
- 两次最终实验的源码哈希均与最终代码一致，冻结任务与商品数据哈希未变。
- 实时演示：**awaiting_basket_confirmation → complete**。
  `outputs/recommended_live_post_topup_20261127.json`：Mt Zion，locationId 02100946，
  请求 12 个大号鸡蛋，实际推荐 UPC 0001111060903、12 ct、1 个包装、$1.49。
  接受后重新调用商品详情，最终 verification.ok=true。草稿阶段本地车为空。

冻结兼容性实验不是新偏好场景评测，4 条开发用例也不是未见泛化测试集。
没有重新运行 ReAct/Direct FC，不能据此宣布相对架构效果。

## 最终 7 条失败的具体原因

所有失败均返回 `no_candidates`；本次无 review_error、数量无人回答、重复计价超预算或基础设施错误。

1. **K06 medium**：模型把半加仑换成精确 1892 mL，真实快照的半加仑商品规范化为 1893 mL。
   语义审查已经找到正确 UPC，但严格数量范围将其拒绝。应统一单位换算/精度语义，
   或保留用户明确的“一盒半加仑”包装要求；不能按场景加 1 mL 特判。
2. **K17 medium**：用户说 no-salt tomato sauce，模型额外加入 `required_tags=[low_sodium]`。
   正确商品有无添加盐名称和每份 10 mg 钠，但没有该标签，因此程序拒绝。
   应区分商品描述、显式标签、数值营养条件及其原话证据，不能自行增加硬标签，也不能猜未知标签。
3. **K16 high、K19 medium、K20 high/medium/low**：首版推荐通过，随后首选缺货。
   当前流程仍用首选名称搜索/审查，没有可靠地切换到用户允许的替代阶段。
   应显式保存首选条件、始终有效的硬条件、条件替代和当前阶段，并针对替代重新发现候选。
   不能为找得到商品而放宽过敏条件，或把 tree_nut_free 猜成 nut_free。

这些问题已有修改方向，但本阶段没有借助评分答案或按商品品类特判修补。
下一步应优先修复上述单位/条件表达与缺货恢复，再接通自然语言局部反馈。

## 已完成

- 新增模型整篮选品，模型只能引用每项审查通过的候选，不能输出价格或购物车操作。
- 默认 HTTP 交互模式变为 `recommend`，原 `user_choice` 显式保留。
- 缺数量时先选包装再询问，确认数量后才生成完整报价。
- 新增 `awaiting_basket_confirmation`，支持 accept 或按需求 ID 局部 replace。
- 局部替换保留其他需求，重新报价并重新接受。旧候选不会因本次未选而被加入黑名单。
- 接受后重新检查价格、库存、数量、硬约束；目标内容变化则重新确认。
- 按最终购物车差量执行新增、更新、删除；修复已有商品重复计价与恢复时重复叠加。
- 推荐草稿、版本、接受摘要、原有购物车与历史一起进入 checkpoint。
- 新模式的数量问题 ID 包含所选商品和推荐版本，避免把旧包装的回答用于新包装。
- 候选审查记录错误与原始输出，格式不合法时最多修正一次。
- 对商品字段的空白差异恢复原文引用；虚构单词、未知商品、缺失硬标签仍拒绝。
- 余额、限流、连接等 OpenAI SDK 服务异常直接传播给 benchmark 的基础设施分类，
  不再伪装成商品审查失败，也不会为此再进行语义修复。
- 新增 `recommended` 实验标签、独立模拟用户偏好、第一版目标评分和交互成本记录。

最终代码离线回归：**136 项测试通过**；`git diff --check` 通过。
FastAPI 请求模型及路由 schema 检查通过。

## 历史诊断运行：各次分开解释

1. `results/recommended_smoke_20261127/`：3 条全部为网络连接失败，没有有效成功率。
2. `results/recommended_smoke_network_20261127/`：网络恢复后 2/3，通过 K02、K07；K20 停在缺货替代后的硬约束筛选。
3. `results/recommended_kroger_20261127/`：**50/60 = 83.3%**，无基础设施失败。
   high 17/20、medium 16/20、low 17/20。10 条停止为 5 条 no_candidates、5 条 review_error。
   54 条生成过首版推荐，其首版目标检查均通过；6 条没有生成推荐，不能忽略。
   这是增加空白引用修复之前的版本，且默认模拟用户接受推荐；不代表最终代码的新完整成绩，
   也不能与旧 ours/interactive 的不同用户协议直接做架构优劣比较。
4. `results/recommended_dialogue_development_20261127/`：新增 4 条开发用例的初跑通过 2/4。
   RD02、RD03 停在审查输出校验。一次额外诊断确认模型引用的 ASCII 空格与源字段的
   NBSP/零宽字符存在差异；该诊断不是原失败响应，见 `recommendation_review_diagnostic_20261127.json`。
5. `results/recommended_dialogue_v2_20261127/`：增加引用恢复和一次格式修复后，
   **4/4 开发用例通过**，没有基础设施失败。共 7 次用户交互批次、7 个问题/确认、1 次替换。
   RD01 接受，RD02 回答数量，RD03 仅替换酸奶，RD04 调整已有购物车。
6. `results/recommended_kroger_v2_20261127/`：**不可报告为完整成功率**。
   原始 runner 标记 40 条基础设施异常；另有 4 条 review_error 的诊断明确包含 429/402，
   1 条 recommendation_error、1 条 no_candidates，14 条完成。
   原生 summary 的局部分母统计不能用于报告新版总体效果。
   这次运行期间服务返回并发额度限制和余额不足，因此停止继续付费调用。

各次原始数据和 manifest 均保留，没有覆盖前次结果。
4 条开发用例不是未见测试集；单次运行也不是稳定效果估计。
随后补充供应商异常分类、日志和旧推荐说明失效处理，全部离线回归通过；
充值后重新完成了本报告开头的最终版本完整测试、交互测试和实时演示。
`recommended_dialogue_final_20261127` 是新回合网络授权恢复前的 4 条连接失败记录，
不参与任何有效成功率；恢复授权后另存为 post_topup 运行。

## RD03 实际输入和状态

公开请求：“Buy exactly two yogurt cups and one bag of Kroger Cut and Peeled Baby Carrots,
under $8, nothing else.” 上下文提供可接受酸奶名单。
独立模拟用户另有 Greek 偏好，首次不传给购物模型。

```text
模型提取：r1 酸奶 2 个包装；r2 胡萝卜 1 袋；预算 800 cents
搜索 + 独立审查 + 硬约束筛选
模型初选：r1 Yoplait 草莓杯；r2 Kroger baby carrots
程序报价：2 × 69 + 1 × 139 = 277 cents

会话：awaiting_basket_confirmation，basket_1
单项：r1 selected，r2 selected；本地 cart 仍为空
用户：replace，requirement_ids=[r1]

会话：waiting_for_user
单项：r1 needs_user；r2 selected，保持原 UPC 和数量
用户从候选选择：Oikos Greek Vanilla，UPC 0003663200834

程序重新报价：2 × 139 + 1 × 139 = 417 cents
会话：awaiting_basket_confirmation，basket_2
用户：accept basket_2

刷新详情、比较接受内容、按差量执行
add carrots 1；add Oikos 2；最终刷新和校验通过
单项：r1 added，r2 added
会话：complete，总价 $4.17
```

真实轨迹中保留的胡萝卜原推荐理由还包含旧总价 $2.77。
最终代码已修正：换版后不再展示上一版篮子的模型说明，改用“保留选择、已重算总价”说明；
原模型文本仅留在历史记录中，价格和总价仍始终由程序计算。

## 下一步

优先补单位/约束证据表达与 preferred→substitute，再补通用自然语言反馈的局部修订、
历史候选回选、原话与包装数量的语义确认以及无候选/超预算恢复。前端暂不开发。
正式评估还需独立未见场景，以及用户改变硬目标时的评分协议。

充值前的 402 阻碍已解除，最终完整 60 条重跑和实时演示均已完成。
实时演示入口为 `scripts/smoke_recommended_live.py`。
未来重跑建议 `--workers 3`，使用新输出目录，避免同时启动多个模型实验。
