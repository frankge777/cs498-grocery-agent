# K16 缺货替代：待实现设计约定

状态：支线聊天确认的后续实现依据。本文仅记录设计，不表示已实现或已通过验收。
本次不修改运行代码、API 合同或冻结 benchmark 数据。

后续更新：本段描述方案记录时状态，v2 已实现部分流程；
具体完成项、实际 API 与限制见 [v2 运行说明](shopping-v2-runtime.md)。

后续整合版本见 [条件替代、候选审查与整篮推荐设计](conditional-substitution-review-recommendation-design.md)，
其中补充 K19/K20、整篮推荐与重新确认、诊断及验收要求；两份文档均为待实现设计。

## 1. 已观察到的根因

K16 high 要求首选 Planet Oat Dairy Free Original Oat Milk；若确认缺货，
允许换其他奶，但必须明确具有 `dairy_free` 和 `nut_free`。

最终推荐实验首次选中 UPC `0004410015618`，加入购物车时触发测试缺货事件。
当前程序清除选择、恢复 `status=unresolved` 并排除该 UPC，
但 `search_query` 仍为 `Planet Oat Dairy Free Original Oat Milk`。
首选与条件替代混在 intent 的 description/preferences 中，没有独立的生效阶段。

第二轮搜索和语义审查继续将 Original 当作必须匹配的名称条件。
Extra Creamy、Unsweetened、Barista 等符合替代范围且有必需标签的商品被判 unrelated。
部分 Original 候选又没有明确的必需标签，最终返回 `no_candidates`。

查询回退目前只在原始 `search_products` 返回零条时启动。
返回 20 条但语义审查/硬约束过滤后剩零条，也没有按允许范围扩大搜索。

## 2. 每项需求的结构

下列是建议字段，不是当前代码已经存在的完整 schema。

- `immutable_original_request`：不可变用户原话，以及来源明确的上下文。
- 用户修订记录：追踪后续明确答复、规则变化及其证据，不能覆盖原话。
- `invariant_constraints`：原有数量目标、明确硬标签和所关联整篮预算等。
  这些条件不随缺货阶段自动放宽；包装变动后的数量解释仍需遵循数量设计约定。
- `primary`：首选名称、用户指定 UPC（若有）、搜索目标及来源证据。
- `fallback`：可为 null。非空时保存触发条件、允许替代范围、必需条件及原话/上下文证据。
- `phase`：`primary | fallback`，表示当前使用哪套商品目标。
- `status`：`unresolved | selected | added` 等执行进度，与 phase 分开保存。
- `observed_availability`：按商品保存可用性观察、来源、时间和确认缺货依据。
- 当前选中 UPC、历轮候选及展示资料、候选读取时间、明确排除与修订记录。

K16 的条件关系示意：

```json
{
  "phase": "primary",
  "invariant_constraints": {
    "quantity": {"measure": "units", "min": 1, "max": 1},
    "required_tags": ["dairy_free", "nut_free"]
  },
  "primary": {
    "name": "Planet Oat Dairy Free Original Oat Milk",
    "search_target": "Planet Oat Dairy Free Original Oat Milk"
  },
  "fallback": {
    "trigger": "confirmed_out_of_stock",
    "product_scope": "其他奶",
    "required_tags": ["dairy_free", "nut_free"],
    "evidence": {
      "source": "original_request",
      "quote": "If it becomes unavailable, substitute one other milk explicitly labeled dairy-free and nut-free."
    }
  }
}
```

此处 UPC 仅用于记录已观察轨迹，不能作为修复代码的场景特判。
实际 primary 的 UPC 只能来自用户明确输入或商品工具结果。
fallback 范围由第一次 intent 提取模型从用户原话/上下文结构化保存，
不得读取 benchmark 隐藏允许 UPC 列表，也不得在缺货后临时编造授权。
用户没有给出改变明确商品条件的替代规则时，`fallback=null`，需要改变这些条件先询问。
若具体 UPC 只是模型在用户原要求范围内的选择，可保持原范围重新推荐并确认新整篮；
不能把模型选定 A 当成用户已明确要求只能买 A。细节见统一实现约定 5.1 节。

## 3. 转换条件与分工

1. 初始 `phase=primary`。模型提取规则，程序验证结构与原话证据、保存状态。
   程序调用搜索工具，模型审查真实候选并提出购物篮，用户确认。
2. 加购失败时先分类：确认缺货、API/网络错误、标签未知、价格变化不能混为一种原因。
   只有 `confirmed_out_of_stock` 且已有有效 fallback，程序才执行 `primary → fallback`。
   商家工具缺少稳定错误码时，需在实现中定义结构化失败原因与确认办法，
   不能把任意失败或暂时取不到详情一律解释为缺货。
3. 切换阶段时清除旧选择和旧推荐批准，保留所有不变硬约束，
   只重开受影响 requirement；其他已确定或已加入的商品继续保存。
   整篮报价与最终批准需按新商品重新计算，不能沿用旧篮子批准。
4. 需要改变用户明确条件但没有 fallback 时，返回可恢复的等待用户替换决定状态。
   用户答复必须绑定需求与问题，明确答复后保存为修订，不能把沉默当作授权。

## 4. 构造当前生效需求

程序按 phase 构造 `active_requirement`，不让模型自行决定哪些硬要求可以忽略。

K16 fallback 阶段的生效目标为：

```text
当前目标：其他奶
数量：保留原目标
硬条件：明确 dairy_free + nut_free
已知事实：首选 UPC 在某次工具观察中确认缺货
原首选名称：历史偏好，不再是替代商品必须满足的名称条件
```

完整原话、有效修订、来源证据和当前阶段仍提供给语义模型。
程序可由已保存替代范围形成查询，或让模型提出有界查询词；
真正的 `search_products/get_product` 由程序调用。
模型不能扩大用户授权范围，不能因首选缺货而自动删除预算、数量或过敏限制。

## 5. 候选审查和搜索恢复

1. 模型读取 active requirement、真实候选、原话/上下文，返回
   `related | unrelated | uncertain`、理由与商品字段证据。
2. 程序验证 UPC 确实来自工具，核验库存、有效价格、数量与显式硬标签。
   模型认为语义相关，不等于商品已经满足硬约束。
3. `tree_nut_free` 不能冒充 `nut_free`，缺失标签保持未知，不能猜测。
4. 原始结果非空、但审查或硬过滤后为零时，也应在已授权范围内有界扩大搜索，
   然后才返回 `no_candidates`。重试次数和调用上限须在实现中显式定义，不能无限循环。
5. API 失败走 API 恢复；真实商品条件不合格走候选恢复，不能通过删掉硬条件解决。
6. 从合格候选形成新推荐/选项。用户确认后重新读取价格、库存、标签和包装数量，
   再执行本地加购与最终验证。

## 6. 历史候选和恢复

与 [历史候选与重新选择设计](candidate-history-and-reselection-design.md) 一致：

- 上一轮未选择不等于永久拒绝，暂时缺货不等于永久不可购买。
- 保存历史候选和展示时事实；当前库存、价格必须重新读取。
- 库存恢复后可重新审查旧商品；重新选择不得复用过期 option_id 或旧价格。
- 用户明确排除与缺货观察分别保存，明确排除可在用户主动修订后解除。
- checkpoint 保存 phase、规则证据、可用性观察和当前状态，恢复后不能沿用旧推荐批准。

与 [商品和数量解释设计](product-and-quantity-interpretation-design.md) 一致：
保留原数量目标和单位含义，不能把某 UPC 的已确认包装数无条件转移给另一包装。

## 7. 建议涉及代码

- `interactive_intent.py` / 提示词：提取和校验 primary/fallback、触发条件及来源证据。
- `choices.py`：每项 phase、active spec、候选历史与缺货观察。
- `interactive.py`：失败原因分类、阶段转换、局部重开、旧批准失效、checkpoint 恢复。
- `discovery.py`：按 active spec 搜索和审查；过滤后零候选时有界扩大检索。
- `recommendation.py`：只基于当前阶段合格候选与有效约束推荐；
  不继续把首选名称当作 fallback 必须满足的条件。
- API / 测试：无规则时暴露可恢复的替换询问状态；状态名称与合同在实现时确定。

## 8. 待执行的验收用例

以下是验收要求，尚未据此实现或宣称通过：

- 首选有货时不启用替代规则。
- 首选确认缺货且用户已给规则时，能选择符合 dairy_free+nut_free 的其他奶。
- 仅有 tree_nut_free 或缺失 nut_free 的商品仍拒绝。
- 需要改变明确条件但用户未给替代规则时暂停询问，不自动替换；
  在原范围重新推荐不额外重复询问授权，仍需新版方案确认。
- API/网络错误不触发缺货替代。
- 多商品篮子只重开缺货需求，保留其他已确定状态。
- 恢复后重新核验商品，旧推荐、旧批准和过期价格不能继续执行。
- 上一轮未选候选可重新读取、核验并进入选择。
- 原始搜索非空但合格候选为零时，能在允许范围内有界重搜并正常停止。
- 规则与证据经过 checkpoint 保存/恢复后仍然一致。
- 冻结 benchmark 数据不因修复被修改，代理不得访问隐藏评分答案。
