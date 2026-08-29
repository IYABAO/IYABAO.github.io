---
title: "YAML基础语法手册以及和JSON的对照"
date: 2019-08-05
draft: false
summary: "YAML 基础语法手册及与 JSON 的对照：从 YAML 1.2 规范讲起，覆盖常用语法与 JSON 对照关系，快速掌握这种对人对机器都友好的配置格式。"
slug: "yaml"
tags: ["YAML", "JSON", "配置"]
---

[YAML](http://yaml.org/)
全名 YAML Ain’t Markup Language，主要设计目标是对人类可读性高。 [YAML 1.2](http://yaml.org/spec/1.2/spec.html)
是 JSON 的超集，也就是说合法的 JSON 扔给 YAML 1.2 解析器是可以被完美解析的。YAML 集 JSON 和 XML 等各种标记语言之长，进行了扩展强化，功能全面也很易读，很多的系统采用它作为配置文件的格式。

## 示例

```
fruits:
  - apple1:
      color: red
  - apple2:
      color: green
  - pear
```
