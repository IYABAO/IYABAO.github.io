---
title: "接口自动化测试体系搭建：从接口测试到压测的全链路方案"
date: 2026-06-15T14:00:00+08:00
draft: false
tags: ["自动化测试", "接口测试", "压测", "Go", "CI/CD", "质量保障"]
categories: ["测试"]
summary: "接口自动化测试体系的完整搭建方案，涵盖接口功能测试、数据驱动、契约测试、性能压测、CI/CD 集成，实现每次代码提交自动运行测试，保障服务质量。"
---

微服务架构下，接口数量多、变更频繁，手工测试跟不上。2026年6月搭建了完整的接口自动化测试体系，从功能测试到性能压测全覆盖，集成到 CI/CD 流水线，每次提交自动运行。今天把方案分享出来。

## 一、技术选型

| 层级 | 工具 | 说明 |
|------|------|------|
| 接口测试 | Go + httpexpect | 用 Go 写测试，和服务同语言，维护成本低 |
| 数据驱动 | YAML/JSON | 测试数据配置化，不用改代码 |
| 契约测试 | Pact | 消费者驱动契约测试，保证服务间接口兼容 |
| 性能压测 | k6 / wrk | 轻量级压测工具，支持脚本化 |
| CI/CD | GitHub Actions / Jenkins | 自动运行测试，失败阻断发布 |
| 测试报告 | Allure | 可视化测试报告，支持历史趋势 |

## 二、接口功能测试

用 Go + httpexpect 写接口测试：

```go
// resume_test.go
func TestGetResume(t *testing.T) {
    e := httpexpect.Default(t, "http://localhost:8080")

    // 1. 先创建测试简历
    created := e.POST("/api/resumes").
        WithJSON(map[string]interface{}{
            "user_id": 1001,
            "name": "测试用户",
            "phone": "13800138000",
        }).
        Expect().
        Status(http.StatusOK).
        JSON().
        Object()

    resumeID := created.Value("data").Object().Value("id").Number().Raw()

    // 2. 查询简历
    e.GET("/api/resumes/{id}", resumeID).
        Expect().
        Status(http.StatusOK).
        JSON().
        Object().
        Value("data").Object().
        Value("name").String().IsEqual("测试用户")

    // 3. 清理测试数据
    e.DELETE("/api/resumes/{id}", resumeID).
        Expect().
        Status(http.StatusOK)
}
```

### 数据驱动

测试数据放 YAML，不用改代码：

```yaml
# testdata/resume_cases.yaml
- name: "正常创建简历"
  request:
    user_id: 1001
    name: "张三"
    phone: "13800138000"
  expected:
    status: 200
    code: 0

- name: "手机号格式错误"
  request:
    user_id: 1001
    name: "张三"
    phone: "12345"
  expected:
    status: 200
    code: 1
    message: "手机号格式错误"

- name: "缺少必填字段"
  request:
    user_id: 1001
    phone: "13800138000"
  expected:
    status: 200
    code: 1
    message: "姓名不能为空"
```

```go
func TestCreateResume_DataDriven(t *testing.T) {
    var cases []TestCase
    data, _ := os.ReadFile("testdata/resume_cases.yaml")
    yaml.Unmarshal(data, &cases)

    e := httpexpect.Default(t, "http://localhost:8080")

    for _, tc := range cases {
        t.Run(tc.Name, func(t *testing.T) {
            resp := e.POST("/api/resumes").
                WithJSON(tc.Request).
                Expect().
                Status(tc.Expected.Status).
                JSON().
                Object()

            resp.Value("code").Number().IsEqual(float64(tc.Expected.Code))
        })
    }
}
```

## 三、契约测试

用 Pact 做消费者驱动契约测试，保证服务间接口兼容：

```go
// 消费者端：定义契约
func TestResumeServiceContract(t *testing.T) {
    pact := &pact.Pact{Consumer: "job-service", Provider: "resume-service"}

    pact.AddInteraction().
        Given("简历存在").
        UponReceiving("获取简历请求").
        WithRequest(dsl.Request{
            Method: "GET",
            Path: dsl.String("/api/resumes/1"),
        }).
        WillRespondWith(dsl.Response{
            Status: 200,
            Body: map[string]interface{}{
                "code": 0,
                "data": map[string]interface{}{
                    "id": dsl.Like(1),
                    "name": dsl.Like("张三"),
                    "phone": dsl.Like("13800138000"),
                },
            },
        })

    pact.Verify(t)
}
```

提供者端验证契约：

```go
func TestProvider_VerifyPacts(t *testing.T) {
    pact.VerifyProvider(t, types.VerifyRequest{
        ProviderBaseURL: "http://localhost:8080",
        PactURLs: []string{
            "pacts/job-service-resume-service.json",
        },
    })
}
```

## 四、性能压测

用 k6 做压测，脚本化：

```javascript
// loadtest/resume.js
import http from 'k6/http';
import { check, sleep } from 'k6';

export const options = {
  stages: [
    { duration: '1m', target: 100 },  // 1分钟内升到100并发
    { duration: '3m', target: 100 },  // 保持100并发3分钟
    { duration: '1m', target: 0 },     // 1分钟内降到0
  ],
  thresholds: {
    http_req_duration: ['p(99)<200'], // P99 < 200ms
    http_req_failed: ['rate<0.01'],    // 错误率 < 1%
  },
};

export default function () {
  const res = http.get('http://localhost:8080/api/resumes/1');
  check(res, {
    'status is 200': (r) => r.status === 200,
    'code is 0': (r) => r.json().code === 0,
  });
  sleep(1);
}
```

运行：`k6 run loadtest/resume.js`

## 五、CI/CD 集成

每次代码提交自动运行测试：

```yaml
# .github/workflows/test.yml
name: API Test
on: [push, pull_request]
jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-go@v5
        with: { go-version: '1.22' }

      - name: 启动服务
        run: |
          go build -o app .
          ./app &
          sleep 5 # 等待服务启动

      - name: 运行接口测试
        run: go test -v ./tests/... -cover

      - name: 运行契约测试
        run: go test -v ./tests/contract/...

      - name: 性能压测（仅主分支）
        if: github.ref == 'refs/heads/main'
        run: k6 run loadtest/resume.js

      - name: 生成测试报告
        if: always()
        uses: actions/upload-artifact@v4
        with:
          name: test-report
          path: reports/
```

测试失败阻断合并，保证主干代码质量。

## 六、踩坑经验

1. **测试数据污染**：测试创建的数据没清理，影响其他测试。用独立测试数据库，测试结束自动清理，或用事务回滚
2. **服务启动时序**：CI 里服务还没启动完就开始测试，连接失败。加健康检查轮询，等服务就绪再跑测试
3. **压测环境差异**：本地压测和生产环境性能差异大，压测结果参考价值有限。在预发布环境压测，配置和生产一致
4. **契约测试维护成本高**：服务多了契约文件管理复杂。用 Pact Broker 统一管理契约，自动验证
5. **测试用例冗余**：接口测试和单元测试有重叠，维护成本高。明确边界：单元测试测逻辑，接口测试测协议和集成，不重复

## 七、总结

接口自动化测试体系核心：

1. **功能测试**：Go + httpexpect，数据驱动，覆盖正常和异常场景
2. **契约测试**：Pact 消费者驱动契约，保证服务间接口兼容
3. **性能压测**：k6 脚本化压测，P99 延迟和错误率阈值监控
4. **CI/CD 集成**：每次提交自动运行，失败阻断发布
5. **测试报告**：Allure 可视化报告，历史趋势对比
6. **数据管理**：独立测试库，自动清理，避免数据污染

自动化测试的价值不是"写了多少测试用例"，而是"每次代码变更都能快速验证质量"。把测试集成到 CI/CD，让测试成为开发流程的一部分，而不是发布前的手工环节。测试左移，问题越早发现，修复成本越低。
