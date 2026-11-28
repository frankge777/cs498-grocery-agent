# 自动推荐购物篮：第一阶段实现

后续 v2 的实际实现与新增接口见 [Shopping v2 运行说明](shopping-v2-runtime.md)。
本文保留第一阶段说明；涉及后续能力时，以运行说明和对应实验版本区分，
不能将旧 53/60 成绩当作 v2 新成绩。

这份说明对应 `selection_mode="recommend"`。HTTP 交互入口现在默认使用该模式；
旧的 `user_choice` 模式和 benchmark 的 `ours` / `interactive` 名称保留。
前端仍调用旧的 `/api/agent/run`，尚未切换到新交互接口。

## 1. 谁做什么

- 模型：从用户原话提取需求；必要时改写搜索词；审查候选语义；从合格候选里提出商品推荐。
- 程序：保存状态；验证模型输出；检查真实商品字段；计算包装数量、整篮价格和购物车差量；决定暂停、重试或结束。
- 用户：回答必要问题，接受推荐，或指定哪些需求需要替换。
- 商品工具：提供商品、价格、包装和库存。模型输出不能覆盖这些事实。

搜索与审查是已有模块，本次新增 `ModelBasketRecommender`。
它一次看到当前待选需求的候选、已经确定的其他需求和预算。
输出仅包含 `requirement_id`、候选中存在的 `product_id` 和推荐理由。
如果模型返回未知 UPC、重复需求或遗漏需求，整批拒绝，返回 `recommendation_error`，
不会先采用其中几项。返回 `product_id=null` 则转交用户选择，不能强行推荐。

实测还补上了候选审查的格式恢复：保存失败阶段、错误与原始模型输出，
给模型一次修正机会，修正后仍逐项检查。Kroger 名称中的不换行/零宽空格可以与
普通空格对齐，但保存的引用必须映射回原商品字段中的实际子串；不能添加不同单词或标签。

## 2. 主流程

```text
用户原话 + 家庭上下文 + 当前购物车
  ↓ 模型提取 intent
必要信息检查
  ├─ 阻碍搜索/安全判断 → needs_clarification → 回答后继续
  ↓ 程序搜索 + 模型语义审查 + 程序硬约束检查
  ├─ 工具/审查错误 → search_error / review_error
  ├─ 无合格候选 → no_candidates
  ├─ 只能确定“可能相关” → needs_candidate_review
  ↓ 模型提出整篮商品选择（这里还没有执行购物车操作）
  ├─ 模型不能确定 → waiting_for_user → 用户选候选
  ↓ 如缺数量 → needs_clarification → 用户确认该包装买几件
  ↓ 刷新商品详情、计算目标购物篮和预算
  ├─ 超预算 → budget_conflict → reconsider 局部重选
  ↓ awaiting_basket_confirmation
  ├─ replace → 仅指定需求 waiting_for_user → 重算 → 新版推荐
  └─ accept → 再次刷新详情并比较推荐内容
                ├─ 价格/数量/商品变化 → 新版推荐，重新接受
                └─ 内容一致 → 按目标购物车差量执行
                                ├─ 缺货 → 重开受影响需求
                                └─ 最终刷新、预算与购物车验证 → complete
```

单项需求继续使用 `unresolved → selected / needs_quantity → added` 等原有状态。
`awaiting_basket_confirmation` 是整个会话的状态。处于这个状态时，单项通常是
`selected`，意思是“商品和数量已经确定”，还不代表已加入购物车。

## 3. 一个状态例子

用户说“买一袋胡萝卜和酸奶，8 美元以内”。模型保留胡萝卜数量 1，酸奶数量未知。
候选搜索完成后，模型选中每项的具体包装。

```json
{
  "r_carrot": {"status": "selected", "quantity": 1},
  "r_yogurt": {"status": "needs_quantity", "quantity": null},
  "cart": {}
}
```

程序问“这款酸奶买几个包装”。用户答 2 后，酸奶变成 `selected`，数量 2。
只有这时才能得到可靠的整篮价格，返回 `awaiting_basket_confirmation`。

推荐清单 `recommendation` 保存商品名称、UPC、包装、单价、数量、行总价、总价、
预算、需求分配和准备执行的操作。商品名称、价格和数量均来自工具或程序计算。
模型的推荐理由单独附在需求分配里，属于解释，不是商品事实的证明。
换版后不沿用可能包含旧整篮总价的模型说明；保留项用已重新计价的说明，原文留在历史中。

用户要换酸奶时，程序只清除酸奶的选择。胡萝卜的选择和需求继续保留。
新选酸奶的数量如果曾经按“这个 UPC 的几个包装”确认，就会清除并重新问；
如果原话已经明确“12 个鸡蛋”，更换 6 个装/12 个装仍可按原总量重新计算。

## 4. 接口

开始：

```json
{
  "instruction": "Buy one bag of carrots and two yogurt cups under $8.",
  "source": "snapshot",
  "selection_mode": "recommend"
}
```

向 `POST /api/agent/interactive/start` 发送。收到 `awaiting_basket_confirmation` 后接受：

```json
{
  "session_token": "<最新响应中的 token>",
  "recommendation_answer": {
    "recommendation_id": "<最新响应中的 recommendation_id>",
    "action": "accept"
  }
}
```

或请求替换：

```json
{
  "session_token": "<最新响应中的 token>",
  "recommendation_answer": {
    "recommendation_id": "<最新响应中的 recommendation_id>",
    "action": "replace",
    "requirement_ids": ["<要替换的需求 ID>"]
  }
}
```

两种答复都发往 `POST /api/agent/interactive/resume`。
替换返回现有的 `questions/options` 合同，使用其 `decision_id/option_id` 选择商品，
然后得到新推荐，再接受。一次 resume 只能提交一种答复。

`reconsider_requirement_ids` 仍用于预算冲突。已有待确认推荐时，应使用上述 replace。
如果是数量问题，仍使用 `clarification_answers`；语义不确定仍用 `candidate_review_answers`。

## 5. 为什么要改购物车计算

旧逻辑容易把“最终希望有几个”理解成“再加几个”。新实现先生成 `target_cart`，
再比较当前购物车。例如：

```text
当前：鸡蛋 1 盒，面包 2 条
目标：鸡蛋 1 盒，面包 1 条，胡萝卜 1 袋

操作：鸡蛋不动；面包更新为 1；加入胡萝卜 1
总价：只对目标里的商品计算一次
```

同一个 UPC 被多个独立需求分配时，先把分配数量汇总，再执行一次目标数量变更。
`keep_existing_items` / `remove_unlisted_items` 决定是否保留未被需求列出的初始商品；
列出的需求仍以明确的最终数量为准。恢复 checkpoint 时先还原保存的购物车，
不会把它再叠加到初始化购物车上。

## 6. 保存什么

原有 checkpoint 继续保存 intent、每项候选与选择、提问、答复和本地购物车。
新增：`selection_mode`、`initial_cart`、`pending_recommendation`、
`recommendation_revision`、`recommendation_history`、`approved_fingerprint`。

`fingerprint` 是对商品/数量/价格/预算等目标内容的摘要；它不是模型的信心分数。
接受某版清单后，如果刷新得到了不同内容，旧接受失效，程序重新生成草稿。
当前 checkpoint 内会拒绝不对应当前草稿的 recommendation_id。
HTTP token 仍是 30 分钟有效的签名状态，尚无数据库中的会话版本锁；旧 token 的并发重放
防护、持久化和幂等键属于后续工作，不能把当前实现当成真实账户写入的事务系统。

## 7. Benchmark 怎样变化

旧 20 条任务、60 个实例及其评分标准保持不变。新增代理名 `recommended`：

- 模型负责首次推荐；模拟用户不再代替模型完成首次选商品。
- 缺数量继续使用独立用户意图档案回答，不能读取评分器答案。
- 默认接受所有推荐，测试既有任务兼容性；这不能证明能适应个人偏好。
- 可传 `--basket-profiles`，按独立的名称偏好请求局部替换并选择候选。
- 记录第一版推荐、最终成功、提问批次/问题数、替换次数、模型与工具开销。
- 第一版目标评分由实验脚本事后计算，不在购物代理内调用评分器；它不含执行后的交互谓词。
- 没有生成推荐的实例单独计数，不能从初始推荐统计里悄悄消失。

`recommendation_dialogue_kroger_development.json` 新增 4 条开发用例，
使用同一个真实 Kroger 冻结快照。RD03 的 Greek 偏好放在独立模拟用户档案中，
不能传给购物模型作为初始需求。若模型首次就选中了 Greek，零次替换也是有效结果；
固定控制流的测试另外保证“先推荐非 Greek 再局部替换”的分支被执行。

这些用例在开发过程中编写，不能当未见测试集或泛化证明。
用户后续明确改变硬目标（如白面包改全麦）的动态评分协议尚未实现。
服务端连接、鉴权、限流、余额等 SDK 异常作为基础设施失败传播，不能修复成“语义通过”。
具体实验结果及未完成的真实模型重跑见 `outputs/recommended_workflow_20261127.md`。

## 8. 哪些保留、哪些改变、哪些还要做

保留：真实 API/快照适配器、归一化、意图提取、搜索重试、独立语义审查、
硬约束、数量计算、询问接口、checkpoint、预算与最终验证。

不再作为新模式默认：看到多款候选就全部交给用户选择；用模拟用户的“最便宜”
选择冒充模型推荐；选完就立即加购。旧模式留作比较和显式选择模式。

新增：模型整篮推荐、推荐草稿、接受/替换协议、推荐版本、接受内容校验、
购物车目标差量、推荐模式实验适配器和私有偏好模拟用户。

还没有完成：

1. 从任意自然语言反馈提取局部修订（当前用结构化 requirement_ids/option_id）。
2. 完整的“原话 × 包装形式 × 数量”语义解释、证据和确认流程。
   待实现顺序为“模型推荐 → 专门模型数量解释 → 用户确认整份方案”；
   用户先选候选不是默认必经步骤。详见 [数量设计修正](product-and-quantity-interpretation-design.md)，
   当前推荐模式已有整篮确认，但尚无该专门模型数量解释步骤。
3. 通用 preferred→substitute 阶段，以及库存变化后历史候选回选；原有缺货排除仍较简单。
   整合后的实现依据见 [条件替代、候选审查与整篮推荐设计](conditional-substitution-review-recommendation-design.md)，
   K16 细节见 [缺货替代设计](k16-stock-fallback-design.md)；均已记录，尚未据此实现或验收。
4. 无候选时进一步诊断/澄清/重搜的恢复入口；当前仍会明确暂停。
5. 整篮超预算后的自动重规划；当前返回冲突并允许局部重选。
6. 候选审查已具备基础诊断与一次格式修复；语义误判的质量评估与改进仍需继续。
7. 正式未见场景集、动态目标修改评分、跨轮硬约束与误替代率等更完整评估。
8. 前端接入、数据库会话版本/并发/幂等，以及真实 Kroger 账户购物车写入。

当前真实模式只读取 Kroger；购物车操作始终是本地模拟。
