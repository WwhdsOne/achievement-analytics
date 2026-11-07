# 成就、完成率与参与行为：补充文献

检索日期：2026-10-23。范围：补充已有截图五篇之外的成就分类、完成率、参与动机与留存研究。仅依据会议、期刊、作者预印本与作者机构仓库核验；以下“项目用途”是针对本项目的建议，不是原论文已经验证的结论。本次没有查询或修改共享数据库。

## 推荐优先级

最贴近现有聚合成就数据的是 **Kwak (2022)** 与 **Yermolaieva & Brown (2019)**；解释“成就究竟测到什么”适合引 **Hamari & Eranti (2011)**、**Jakobsson (2011)**；解释为何关注持续参与可引 **Park et al. (2017)**。**Hamari (2017)** 是非游戏场景的旁证，应明确交代场景差异。

## 1. 大规模奖杯完成率与文本分析

**Kwak, Haewoon. (2022). You Have Earned a Trophy: Characterize In-Game Achievements and Their Completions.** *Proceedings of the 14th ACM Web Science Conference (WebSci ’22)*, 129–138. DOI: [10.1145/3501247.3531582](https://doi.org/10.1145/3501247.3531582)。书目信息与正式版本见[作者机构仓库](https://ink.library.smu.edu.sg/sis_research/7191/)，方法见[作者预印本全文](https://arxiv.org/html/2205.15163)。

- 方法：构建 PlayStation 奖杯及完成率数据，结合 HowLongToBeat；分析类型、时长、奖杯条件重复性与完成率，并采用语义角色标注、词性标注及 SentenceBERT 聚类分析条件文本。
- 项目用途：为“成就完成率＋游戏类型／时长＋成就语义”的分析框架提供直接先例；尤其适合支持成就文本分类、难度结构和游戏画像。
- 限制：PlayStation 的等级与平台规则不同于 Steam；论文还指出玩家社区统计可能有偏差。不能将跨平台发现无条件搬到本项目，也不能把完成率直接等同于喜爱程度。
- 可写入相关工作：“Kwak 从开发者设计与玩家完成行为两侧分析奖杯系统，展示了将条件文本、游戏属性和完成率联合研究的价值。”

## 2. Steam 成就分类与完成率建模

**Yermolaieva, Sofiia, & Brown, Joseph Alexander. (2019). A Taxonomy for Achievements in Digital Games.** *GAME-ON 2019*, 71 起。正式出版方的[论文集目录](https://www.eurosis.org/cms/files/proceedings/GAMEON/GAMEON2019contents.pdf)及[含论文全文的会议文集](https://www.eurosis.org/cms/files/proceedings_full/GAMEON2019.pdf)可核验；没有核验到独立 DOI，因此不补造 DOI。

- 方法：提出 21 项成就特征分类，将其用于 Steam 畅销游戏样本中的 6,775 项成就；使用决策树、决策表与聚类分析特征和完成率的关系。
- 项目用途：比只使用“成就总数”更接近内容设计；可参考其故事、探索、重复、多人等维度，人工标注少量样本并建立简单对照。
- 限制：畅销样本不代表 Steam 全体游戏；人工标注规则应复核；不能把这篇与截图中的“open world role-playing games…new taxonomic method”当成同一篇。
- 可写入相关工作：“已有研究通过成就条件分类解释完成率差异，本项目可进一步考察这些内容维度与游戏层面属性的关联。”

## 3. 成就的概念与设计框架

**Hamari, Juho, & Eranti, Veikko. (2011). Framework for Designing and Evaluating Game Achievements.** *Proceedings of DiGRA 2011 Conference: Think Design Play*. DOI: [10.26503/dl.v2011i1.545](https://doi.org/10.26503/dl.v2011i1.545)。[DiGRA 官方条目](https://dl.digra.org/index.php/dl/article/view/545)及[原文 PDF](https://dl.digra.org/index.php/dl/article/download/545/545/542)。

- 方法：考察现有成就系统，提出由表征元素、完成逻辑和奖励构成的分析框架；将成就视为可跨游戏会话存在的元游戏挑战。
- 项目用途：为 display_name／description 的语义分析，以及“成就内容与完成率不应混为一谈”的测量定义提供基础。
- 限制：这是概念与设计框架，不是“添加成就可提高 Steam 留存”的因果检验，也不提供可直接移植的流失预测器。
- 可写入理论基础：“成就是具有明确完成条件的设计对象，因此完成率既反映玩家行为，也受条件与奖励结构影响。”

## 4. 成就与留存的阶段差异

**Park, Kunwoo, Cha, Meeyoung, Kwak, Haewoon, & Chen, Kuan-Ta. (2017). Achievement and Friends: Key Factors of Player Retention Vary Across Player Levels in Online Multiplayer Games.** *Proceedings of the 26th International Conference on World Wide Web Companion (WWW ’17 Companion)*, 445–453. DOI: [10.1145/3041021.3054176](https://doi.org/10.1145/3041021.3054176)。[作者预印本](https://arxiv.org/abs/1702.08005)、[作者机构仓库及正式出版信息](https://ink.library.smu.edu.sg/sis_research/5653/)。

- 方法：分析某多人在线游戏 51,104 位玩家的日志，按玩家等级／虚拟生命周期比较寿命的预测因素；成就因素在早期到进阶阶段重要，最高等级时社交因素更突出。
- 项目用途：为分阶段、分群分析提供理由，提醒单一总体指标可能掩盖玩家阶段差异。
- 限制：依赖玩家个体日志、等级、社交和时间信息。当前游戏层面全局完成率不能复现其玩家留存模型；“成就因素”也不能机械等同于 Steam 平台成就解锁率。
- 可写入讨论：“留存因素可能随玩家阶段变化，因此本文的游戏层面聚合结果不应解释为所有玩家共有的机制。”

## 5. 成就行为不等于享受：玩家类型的质性证据

**Jakobsson, Mikael. (2011). The Achievement Machine: Understanding Xbox 360 Achievements in Gaming Practices.** *Game Studies*, 11(1)。[期刊官方全文](https://gamestudies.org/1101/articles/jakobsson)。本次未核验到 DOI，使用期刊稳定链接。

- 方法：两年社区民族志研究，材料包含访谈、参与观察及网络社区内容；讨论 achievement casuals、hunters 和 completists 三类实践。
- 项目用途：为“成就指标只能作为行为代理变量”提供理论支持，也适合解释刷成就、完成主义与游戏偏好之间的差别。
- 限制：Xbox 社区质性研究，不能据此量化 Steam 玩家比例或直接给聚合数据贴玩家类型标签；成就追求可能与实际享受冲突。
- 可写入局限：“成就完成行为还受到完成主义和平台元游戏动机驱动，因此高完成率不必然代表更强的主观喜爱。”

## 6. 徽章是否促进活动：非游戏场景的实证旁证

**Hamari, Juho. (2017). Do badges increase user activity? A field experiment on the effects of gamification.** *Computers in Human Behavior*, 71, 469–478. DOI: [10.1016/j.chb.2015.03.036](https://doi.org/10.1016/j.chb.2015.03.036)。[出版社摘要与正式卷页](https://www.sciencedirect.com/science/article/pii/S0747563215002265)。注意：在线发表在 2015 年，正式卷期为 2017 年，参考文献应统一采用正式卷期年份。

- 方法：在点对点交易服务中比较徽章实施前后各一年的不同用户组，样本分别为 1,410 和 1,579；观察提案、交易、评论与总体使用活动。
- 项目用途：放在背景或理论动机中，说明外显成就奖励与活动行为的研究基础。
- 限制：对象不是电子游戏，也不是 Steam；前后不同群体设计不能被转写为本项目的因果证据，不能声称本项目已证明成就设计提升留存。
- 可写入背景：“其他数字服务中的徽章研究为考察成就与参与行为提供了动机，但效应是否适用于游戏仍须单独检验。”

## 本项目的测量边界

以下是根据本项目数据结构提出的分析建议，而非上述论文的逐字结论：

1. 将指标称为“成就完成结构”“内容触达代理”或“参与行为代理”；需要另有证据才能称为喜好、满意度或留存。
2. 同一时点的全局完成率是各成就的边际比例，不能还原个体解锁路径、时间到事件或停止游玩的日期；按完成率排序也不保证真实剧情顺序。
3. 最低成就完成率不等于“全成就玩家比例”：不同玩家可能分别缺不同成就，必须有联合个体记录才能精确计算。
4. “通关成就”须人工或经审核的规则识别，不能把最稀有成就自动当作主线通关；可在相同类型、发行年代、时长区间内比较。
5. 对成就数量、多人条件、重复要求、DLC 和无法再获得的成就做敏感性分析，并区分采集时间与发行时间；观察结果保持相关性措辞。

## 可直接放入报告的相关工作草稿

游戏成就既是玩家行为记录，也是开发者设计的目标系统。Hamari 与 Eranti（2011）从表征、完成逻辑与奖励三个方面界定其结构；Jakobsson（2011）则揭示完成主义与成就狩猎等不同实践。针对可计算的行为数据，Yermolaieva 与 Brown（2019）将成就条件分类用于 Steam 完成率分析，Kwak（2022）进一步结合奖杯条件文本、类型和游戏时长研究跨游戏差异。Park 等（2017）表明多人游戏中的持续参与因素可能随玩家阶段变化。基于这些工作，本项目将聚合成就数据用于描述游戏的完成结构，并考察其与游戏属性的关联；不将此类关联解释为个体喜好或留存的因果机制。

上述段落中的论文链接见各条正式引用。若报告需要参考文献列表，可直接采用各条的作者、年份、题名、venue 与 DOI，按学校指定格式统一排版。
