# 游戏分析相关文献补充

检索日期：2026-10-23。依据项目 `README.md`、`docs/plan.md` 的五个方向整理；排除用户截图已经列出的五篇，不为凑数量重复收录预印本和正式版。文献内容以出版社、作者论文及高校机构库为依据；适配建议是结合本项目数据条件作出的判断。

## 推荐顺序

本目录共新增 13 项文献：本页 7 项，成就专题 6 项，其中 Hamari（2017）是非游戏场景的旁证。优先读成就专题中的 **Kwak（2022）**、**Yermolaieva 与 Brown（2019）**，以及下表的 **Sifa（2015）**；再根据各方向补充。

成就设计、动机与留存方向的详细引用见 [achievement-papers.md](achievement-papers.md)。

| 成就专题补充 | 适合引用的位置 |
| --- | --- |
| Kwak，2022，You Have Earned a Trophy: Characterize In-Game Achievements and Their Completions | 成就文本、类型、时长与完成率联合分析，优先推荐 |
| Yermolaieva 与 Brown，2019，A Taxonomy for Achievements in Digital Games | Steam 成就分类与完成率建模，优先推荐 |
| Hamari 与 Eranti，2011，Framework for Designing and Evaluating Game Achievements | 成就定义、条件与奖励的理论基础 |
| Park 等，2017，Achievement and Friends | 分阶段留存研究及聚合数据的局限 |
| Jakobsson，2011，The Achievement Machine | 成就狩猎、完成主义与喜好指标的解释边界 |
| Hamari，2017，Do badges increase user activity? | 激励与参与行为的背景旁证，须说明不是游戏场景 |

其余跨游戏分析、标签、评价与推荐文献如下。

| 文献 | 可放到项目哪个部分 | 主要用途 |
| --- | --- | --- |
| Sifa 等，2015，Large-Scale Cross-Game Player Behavior Analysis on Steam | 总体背景、游戏画像聚类、玩家偏好 | 说明 Steam 跨游戏行为分析已有研究基础；区分游戏聚类与玩家聚类 |
| Windleharth 等，2016，Full Steam Ahead | 标签归类、年度类型演变、知识图谱 | 说明用户标签不只是传统游戏类型，还包含多种描述维度 |
| Grelier 与 Kaufmann，2023，A Data-Driven Classification of Video Game Vocabulary | 标签加权、类型归类、游戏画像 | 参考用数据区分标签重要程度的方法 |
| Starosta 等，2024，The tangled ways to classify games | 研究背景、分类口径与局限 | 支撑游戏类型划分困难、采用机制和社区标签的动机 |
| Lin 等，2019，An empirical study of game reviews on the Steam platform | 口碑分析、评分与时长的关系 | 支撑 Steam 评价作为研究数据的价值，提醒评价有其生成情境 |
| Wang 等，2020，Using Deep Learning and Steam User Data for Better Video Game Recommendations | 可解释推荐的相关工作与后续拓展 | 对照使用玩家数据的深度推荐路线及其评价指标 |
| Ullmann 等，2022，What Makes a Game High-rated? | 口碑预测与关联因素 | 参考对高评分游戏相关因素的分析，同时讨论评分口径与样本限制 |

## 1. Steam 跨游戏行为分析：最值得补的一篇

**Sifa, R., Drachen, A., & Bauckhage, C. (2015). Large-Scale Cross-Game Player Behavior Analysis on Steam. Proceedings of the AAAI Conference on Artificial Intelligence and Interactive Digital Entertainment, 11(1), 198–204.**

- DOI / 正式页面：[10.1609/aiide.v11i1.12804](https://ojs.aaai.org/index.php/AIIDE/article/view/12804)。页面提供全文。
- 研究：覆盖超过 3000 款游戏与 600 万玩家，研究拥有游戏、游玩时长及评分之间的关系；使用频繁项集与聚类等方法，也对游戏进行聚类。
- 项目用途：适合放在整体相关工作，以及“为什么用行为特征刻画游戏”的论证中。你们的成就完成结构可作为不同于游玩时长的画像维度。
- 限制：它使用玩家层面数据；本项目的游戏级聚合数据不能直接复现其玩家分群或共同拥有关系。

## 2. Steam 用户标签的概念分类

**Windleharth, T. W., Jett, J., Schmalz, M., & Lee, J. H. (2016). Full Steam Ahead: A Conceptual Analysis of User-Supplied Tags on Steam. Cataloging & Classification Quarterly, 54(7), 418–441.**

- DOI：[10.1080/01639374.2016.1190951](https://doi.org/10.1080/01639374.2016.1190951)。
- 免费全文：[华盛顿大学托管 PDF](https://cpb-us-e1.wpmucdn.com/sites.uw.edu/dist/2/3760/files/2019/09/Full-Steam-ahead-a-conceptual-analysis-of-user-supplied-tags-on-Steam.pdf)。已核对首页书目信息及摘要。
- 研究：收集 Steam 用户标签，进行概念归类，并与游戏元数据模式比较。
- 项目用途：用于解释为何把标签按玩法、主题、表现形式等维度整理，比把所有标签视为互斥“类型”更合适。具体维度仍需结合全文和本项目标签表确定。
- 限制：标签体现用户描述与平台文化，不能直接视为客观、完整且跨年份稳定的类型真值。

## 3. 用数据衡量 Steam 标签的重要程度

**Grelier, N., & Kaufmann, S. (2023). A Data-Driven Classification of Video Game Vocabulary. In Entertainment Computing – ICEC 2023, LNCS 14455, 17–30.**

- DOI / 正式页面：[10.1007/978-981-99-8248-6_2](https://link.springer.com/chapter/10.1007/978-981-99-8248-6_2)。已核对摘要和出版社引用信息。
- 免费预印本：[Data-Driven Classifications of Video Game Vocabulary](https://arxiv.org/abs/2303.07179)。预印本与正式版标题不同，作为同一研究脉络处理，不能重复计数；细节引用须注明使用的版本。
- 研究：利用每款游戏被玩家赋予标签的数量，引入标签 priority 指标，分析标签在描述游戏时的重要程度。
- 项目用途：支撑标签并非等权、标签具有不同描述功能的讨论；可与项目现有加权标签方案比较。
- 限制：该指标不等同于 TF-IDF；如果本项目仅保存标签存在关系、没有投票数量，不能宣称复现了作者方法。

## 4. 游戏类型划分的系统综述

**Starosta, J., Kiszka, P., Szyszka, P. D., Starzec, S., & Strojny, P. (2024). The tangled ways to classify games: A systematic review of how games are classified in psychological research. PLOS ONE, 19(6), e0299819.**

- DOI / 开放全文：[10.1371/journal.pone.0299819](https://journals.plos.org/plosone/article?id=10.1371/journal.pone.0299819)。
- 研究：按 PRISMA 流程审查 96 篇全文，讨论游戏类型划分的不一致，并提出关注具体机制、使用社区标签等方向。
- 项目用途：适合写在“游戏类型与标签”的研究背景，解释为何需要透明的标签归类和多维画像。
- 限制：综述针对心理学研究中的分类实践；不能把它表述为验证了本项目的某一具体分类或聚类结果。

## 5. Steam 评价与玩家反馈

**Lin, D., Bezemer, C.-P., Zou, Y., & Hassan, A. E. (2019). An empirical study of game reviews on the Steam platform. Empirical Software Engineering, 24, 170–207.**

- DOI / 正式页面：[10.1007/s10664-018-9627-4](https://link.springer.com/article/10.1007/s10664-018-9627-4)。线上首发是 2018 年，卷期年份为 2019 年，正式参考文献可按卷期用 2019 年。
- 免费作者稿：[SAIL 研究组 PDF](https://sailresearch.github.io/sail-website/data/pdfs/EMSE2018_AnEmpiricalStudyOfGameReviewsOnTheSteamPlatform.pdf)。本轮重点核对出版社摘要和书目信息。
- 研究：分析 6224 款 Steam 游戏的评价，涉及评价数量变化、评价表达的关注点与发表评价前的游玩时长。
- 项目用途：作为口碑与玩家反馈研究的领域参考，讨论评价与时长的关系，以及评价数据的解释边界。
- 限制：如果项目只有总评分和评价数量，不能把它写成已开展评论文本分析；评论时的个人时长也不等于 SteamSpy 的游戏整体平均时长。

## 6. Steam 个性化游戏推荐

**Wang, D., Moh, M., & Moh, T.-S. (2020). Using Deep Learning and Steam User Data for Better Video Game Recommendations. Proceedings of the 2020 ACM Southeast Conference, 154–159.**

- DOI：[10.1145/3374135.3385283](https://doi.org/10.1145/3374135.3385283)。
- 核验来源：[圣何塞州立大学机构库](https://scholarworks.sjsu.edu/faculty_rsca/1698/)。ACM 页面本轮访问受限，使用作者所属高校的摘要与引用信息交叉核对。
- 研究：提出 STEAMer，使用 Steam 用户数据与深度自编码器进行推荐，对照深度神经网络方案，以 MAP@10、NDCG@10 及多样性评估。
- 项目用途：放在推荐系统相关工作，对比“依赖用户历史的推荐”与本项目“种子游戏、标签和成就画像”的实现条件。
- 限制：没有用户交互与真实相关性标签时，不能直接照搬离线指标并声称达到同类效果；可保留盲评或明确标注的代理任务。

## 7. 高评分游戏的关联因素

**Ullmann, G. C., Politowski, C., Guéhéneuc, Y.-G., & Petrillo, F. (2022). What Makes a Game High-rated? Towards Factors of Video Game Success. IEEE/ACM 6th International Workshop on Games and Software Engineering (GAS), 16–23.**

- 正式条目与引用信息：[ÉTS 高校机构库](https://espace2.etsmtl.ca/id/eprint/26362/)。
- 免费全文：[作者研究组 PDF](https://assets.ptidej.net/Publications/Documents/GAS22b.doc.pdf)。
- 研究：围绕 200 个游戏项目，分析团队、类型、游戏模式与开发问题等因素与评分的关系。
- 项目用途：为“游戏属性与口碑相关因素”提供直接的领域参照；也可讨论为何仅靠少数属性难以解释评分。
- 限制：它不是 Steam 成就研究，也不等同于本项目的 RAWG 评分预测。其评分以 Metacritic 为主、部分样本使用其他来源，跨来源口径需要注意。
- 元数据注意：作者稿印有 DOI 尾号 `3527623`，机构库的正式链接为 `3527628`；本笔记不替两者做未经核验的取舍，优先提供机构库和作者稿，正式提交前用出版社 RIS/BibTeX 再确认。

## 相关工作可以怎样组织

以下是组织建议，不是原论文共同验证过的结论：

1. **跨游戏行为分析**：用 Sifa 等引出 Steam 大规模行为研究，再说明本项目主要分析游戏级成就完成特征。
2. **标签与游戏分类**：用 Windleharth、Grelier、Starosta 说明标签维度、权重与类型划分问题，对接年度类型演变和画像聚类。
3. **成就设计与完成表现**：沿用截图里的直接相关文献，并补充 [成就专题笔记](achievement-papers.md) 中适合的研究。
4. **评价与推荐应用**：用 Lin、Ullmann 连接口碑分析，用 Wang 连接推荐路线与评价方法。

不必在每个章节堆满全部文献。每篇应对应一个具体论点、方法或研究差异。K-Means、随机森林、SHAP 等方法论文可另外引用，但不能替代游戏领域相关工作。

## 项目表述的边界

- 全球成就比例是聚合快照；没有个人时间序列时，不能直接估计个体流失时间或验证长期留存。
- 按解锁率排序得到的是完成率分布，只有确认剧情节点与顺序后才能称为主线进度曲线。
- 以标签或成就特征聚类的是游戏；不能自动解释为玩家类型。
- 当前标签在不同发售年份游戏中的占比，反映样本中的发行结构，不能自动代表历史年度玩家偏好。
- 未对已有文献做系统比较前，不写“首次”“填补空白”或“显著优于既有方法”。

## 对截图已有文献的去重提醒

截图中的 *Analyzing Video Game Completion Achievements: Implications for Game Project Scope* 与检索出现的 *Improving video game project scope decisions with data: An analysis of achievements and game completion rates* 高度相关。后者有 [Entertainment Computing 正式页面](https://www.sciencedirect.com/science/article/pii/S1875952118300181)。本轮没有逐项核对两篇的全文和扩展关系，因此没有将后者计为独立新增文献；正式写作时再检查作者、数据与版本关系。
