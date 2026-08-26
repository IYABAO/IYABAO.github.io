---
title: "「火爆人才」简历分层算法：基于活跃度与质量评分的人才分层模型"
date: 2021-05-10T16:00:00+08:00
draft: false
tags: ["算法", "数据建模", "推荐系统", "PHP", "Elasticsearch"]
categories: ["算法"]
summary: "招聘平台「火爆人才」功能的简历分层算法设计，基于活跃度与质量评分构建人才分层模型，实现优质人才优先展示，提升企业招聘效率。"
---

招聘平台上简历数量巨大，企业搜索简历时经常面临"简历很多但合适的很少"的问题。为了提升企业招聘效率，我们做了「火爆人才」功能——把活跃且质量高的简历优先展示给企业。核心是简历分层算法，今天把设计思路和实现分享出来。

## 一、需求与目标

「火爆人才」的目标：

1. **优质优先**：活跃、质量高的简历排在前面，企业更容易找到合适的人才
2. **动态更新**：人才活跃度会变化，分层要动态调整，不能一成不变
3. **可解释**：分层规则要可解释，能告诉企业为什么这份简历是"火爆人才"
4. **防作弊**：防止求职者通过刷活跃度等方式提升层级

## 二、分层模型设计

把简历分成 5 个层级：

| 层级 | 名称 | 占比 | 说明 |
|------|------|------|------|
| S | 火爆人才 | 5% | 极度活跃且质量极高，优先推荐 |
| A | 优质人才 | 15% | 活跃且质量高，推荐展示 |
| B | 潜力人才 | 30% | 有一定活跃度或质量，正常展示 |
| C | 普通人才 | 40% | 活跃度低或质量一般，靠后展示 |
| D | 沉睡人才 | 10% | 长期不活跃，最后展示 |

分层基于两个核心维度：**活跃度评分**和**质量评分**，综合计算总分后按比例分层。

## 三、活跃度评分

活跃度反映求职者最近的活跃程度，越活跃越可能在找工作，企业联系后回复率越高。

### 3.1 活跃度指标

| 指标 | 权重 | 说明 |
|------|------|------|
| 最近登录时间 | 30% | 最近登录越近分越高 |
| 简历更新频率 | 20% | 最近更新简历的次数 |
| 职位浏览/投递 | 25% | 最近浏览职位、投递简历的次数 |
| 消息回复率 | 15% | 企业消息的回复率和回复速度 |
| 在线时长 | 10% | 最近30天的累计在线时长 |

### 3.2 时间衰减

活跃度要考虑时间衰减，越久之前的行为权重越低。用指数衰减函数：

```php
function timeDecay($timestamp, $halfLife = 86400 * 7)
{
    $daysAgo = time() - $timestamp;
    return pow(0.5, $daysAgo / $halfLife); // 半衰期7天
}
```

7天前的行为权重衰减一半，30天前的行为权重只有约 5%。

### 3.3 活跃度计算

```php
class ActivityScorer
{
    public function score($userId)
    {
        $score = 0;

        // 1. 最近登录时间（0-30分）
        $lastLogin = UserLoginLog::find()
            ->where(['user_id' => $userId])
            ->orderBy(['created_at' => SORT_DESC])
            ->select('created_at')
            ->scalar();
        if ($lastLogin) {
            $daysSinceLogin = (time() - $lastLogin) / 86400;
            $score += 30 * max(0, 1 - $daysSinceLogin / 30); // 30天以上0分
        }

        // 2. 简历更新频率（0-20分）
        $updateCount = ResumeUpdateLog::find()
            ->where(['user_id' => $userId])
            ->andWhere(['>=', 'created_at', time() - 86400 * 30])
            ->count();
        $score += 20 * min(1, $updateCount / 5); // 5次以上满分

        // 3. 职位浏览/投递（0-25分）
        $viewCount = JobViewLog::find()
            ->where(['user_id' => $userId])
            ->andWhere(['>=', 'created_at', time() - 86400 * 30])
            ->count();
        $applyCount = JobApply::find()
            ->where(['user_id' => $userId])
            ->andWhere(['>=', 'created_at', time() - 86400 * 30])
            ->count();
        $score += 15 * min(1, $viewCount / 20) + 10 * min(1, $applyCount / 5);

        // 4. 消息回复率（0-15分）
        $replyStats = Message::find()
            ->where(['receiver_id' => $userId])
            ->andWhere(['>=', 'created_at', time() - 86400 * 30])
            ->select(['COUNT(*) as total', 'SUM(is_replied) as replied'])
            ->asArray()
            ->one();
        if ($replyStats && $replyStats['total'] > 0) {
            $replyRate = $replyStats['replied'] / $replyStats['total'];
            $score += 15 * $replyRate;
        }

        // 5. 在线时长（0-10分）
        $onlineSeconds = UserOnlineLog::find()
            ->where(['user_id' => $userId])
            ->andWhere(['>=', 'date', date('Y-m-d', time() - 86400 * 30)])
            ->sum('seconds');
        $score += 10 * min(1, $onlineSeconds / 36000); // 10小时以上满分

        return round($score, 2);
    }
}
```

## 四、质量评分

质量评分反映简历的"含金量"，学历、工作经验、技能等因素。

### 4.1 质量指标

| 指标 | 权重 | 说明 |
|------|------|------|
| 学历 | 20% | 博士/硕士/本科/大专/高中及以下 |
| 工作年限 | 15% | 工作年限越长分越高（但有上限） |
| 知名企业经历 | 20% | 是否有知名企业工作经历 |
| 技能匹配度 | 15% | 技能标签的丰富度和热门程度 |
| 简历完整度 | 15% | 简历各字段填写完整程度 |
| 历史投递反馈 | 15% | 历史投递后企业的反馈（面试邀约率） |

### 4.2 质量计算

```php
class QualityScorer
{
    public function score($userId)
    {
        $resume = Resume::findOne(['user_id' => $userId]);
        if (!$resume) return 0;

        $score = 0;

        // 1. 学历（0-20分）
        $eduScore = ['高中及以下' => 2, '大专' => 8, '本科' => 14, '硕士' => 18, '博士' => 20];
        $score += $eduScore[$resume->education] ?? 5;

        // 2. 工作年限（0-15分）
        $years = $resume->work_years ?? 0;
        $score += 15 * min(1, $years / 10); // 10年以上满分

        // 3. 知名企业经历（0-20分）
        $famousCompanies = $this->getFamousCompanyCount($userId);
        $score += 20 * min(1, $famousCompanies / 2); // 2家以上满分

        // 4. 技能匹配度（0-15分）
        $skillCount = count($resume->skills ?? []);
        $hotSkillCount = $this->getHotSkillCount($resume->skills ?? []);
        $score += 8 * min(1, $skillCount / 10) + 7 * min(1, $hotSkillCount / 5);

        // 5. 简历完整度（0-15分）
        $completeness = $this->calcResumeCompleteness($resume);
        $score += 15 * $completeness;

        // 6. 历史投递反馈（0-15分）
        $interviewRate = $this->getInterviewRate($userId);
        $score += 15 * $interviewRate;

        return round($score, 2);
    }

    private function calcResumeCompleteness($resume)
    {
        $fields = ['name', 'phone', 'email', 'education', 'work_years', 'current_position', 'current_company', 'skills', 'self_introduction', 'work_experience', 'education_experience'];
        $filled = 0;
        foreach ($fields as $field) {
            if (!empty($resume->$field)) $filled++;
        }
        return $filled / count($fields);
    }

    private function getInterviewRate($userId)
    {
        $applies = JobApply::find()
            ->where(['user_id' => $userId])
            ->andWhere(['>=', 'created_at', time() - 86400 * 180])
            ->count();
        if ($applies == 0) return 0.5; // 无数据给中性分

        $interviews = Interview::find()
            ->where(['candidate_id' => $userId])
            ->andWhere(['>=', 'created_at', time() - 86400 * 180])
            ->count();
        return min(1, $interviews / $applies / 0.3); // 30%面试率满分
    }
}
```

## 五、综合分层

### 5.1 总分计算

活跃度和质量各占 50%：

```php
class ResumeTierService
{
    public function calcTier($userId)
    {
        $activityScore = (new ActivityScorer())->score($userId);
        $qualityScore = (new QualityScorer())->score($userId);

        // 综合分：活跃度50% + 质量50%
        $totalScore = $activityScore * 0.5 + $qualityScore * 0.5;

        // 按分数分层
        return $this->scoreToTier($totalScore);
    }

    private function scoreToTier($score)
    {
        if ($score >= 80) return 'S';
        if ($score >= 65) return 'A';
        if ($score >= 50) return 'B';
        if ($score >= 30) return 'C';
        return 'D';
    }
}
```

### 5.2 动态比例调整

固定分数阈值可能导致各层级比例失调（比如 S 级占了 20%）。用动态比例调整，确保各层级占比符合预期：

```php
public function recalcAllTiers()
{
    // 计算所有用户的总分
    $scores = [];
    $users = User::find()->select('id')->column();
    foreach ($users as $userId) {
        $scores[$userId] = $this->calcTotalScore($userId);
    }

    // 按分数降序排序
    arsort($scores);

    // 按比例分层
    $total = count($scores);
    $tiers = [];
    $rank = 0;
    foreach ($scores as $userId => $score) {
        $rank++;
        $percentile = $rank / $total;
        if ($percentile <= 0.05) $tier = 'S';
        elseif ($percentile <= 0.20) $tier = 'A';
        elseif ($percentile <= 0.50) $tier = 'B';
        elseif ($percentile <= 0.90) $tier = 'C';
        else $tier = 'D';

        $tiers[$userId] = $tier;
    }

    // 批量更新
    foreach ($tiers as $userId => $tier) {
        Resume::updateAll(['tier' => $tier], ['user_id' => $userId]);
    }
}
```

每天凌晨跑一次，重新计算所有简历的层级。

## 六、搜索排序集成

简历搜索时，按层级排序，S/A 级优先展示：

```json
POST /resume/_search
{
  "query": {
    "bool": {
      "must": [
        {"match": {"skills": "PHP"}}
      ]
    }
  },
  "sort": [
    {"tier_rank": "desc"},
    {"activity_score": "desc"},
    {"_score": "desc"}
  ]
}
```

`tier_rank` 是层级对应的数字（S=5, A=4, B=3, C=2, D=1），索引时冗余存储，避免排序时计算。

## 七、防作弊机制

求职者可能通过刷登录、刷浏览等方式提升活跃度。防作弊措施：

1. **异常行为检测**：短时间内大量浏览/投递（如1分钟浏览100个职位），标记为异常，不计入活跃度
2. **IP/设备限制**：同一IP/设备多个账号频繁操作，降权处理
3. **质量分保底**：活跃度再高，质量分太低也不能到 S/A 级
4. **人工审核**：S 级简历定期人工抽查，发现造假降级

## 八、效果

上线后的数据对比：

| 指标 | 上线前 | 上线后 | 提升 |
|------|--------|--------|------|
| 企业简历查看率 | 45% | 62% | +38% |
| 简历投递回复率 | 28% | 41% | +46% |
| 面试邀约率 | 12% | 18% | +50% |
| 企业招聘满意度 | 6.5/10 | 8.2/10 | +26% |

「火爆人才」标签的简历，企业查看率和回复率都明显高于普通简历，说明分层算法是有效的。

## 九、总结

简历分层算法的核心设计：

1. **双维度评分**：活跃度（找工作意愿）+ 质量（简历含金量），综合评估
2. **时间衰减**：活跃度考虑时间衰减，越近的行为权重越高
3. **动态分层**：按比例动态调整各层级人数，避免比例失调
4. **搜索集成**：层级作为排序因子，优质人才优先展示
5. **防作弊**：异常行为检测 + 质量保底 + 人工审核，防止刷分

这个算法不是完美的，后续还可以优化：引入企业端的反馈数据（收藏、下载、面试）作为质量分的重要依据，用机器学习模型替代人工权重，实现更精准的分层。但作为第一版，已经达到了预期效果，验证了方向的正确性。
