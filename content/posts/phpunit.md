---
title: "PHPUnit"
date: 2022-08-12
draft: false
summary: "PHPUnit 踩坑实录：记录 PHP 7.2/7.4 环境下 PHPUnit 8.5/9.5 与 Mockery 的版本兼容问题、测试类编写规范与日常开发中的实战经验。"
slug: "phpunit"
tags: ["PHPUnit", "PHP", "测试"]
---

PHPUnit踩坑实录

版本信息
说明：现有项目使用php7.2, 只能支持phpunit8.5, 不支持部分新特性

php 7.4.30
phpunit 9.5.21
mockery 1.5.0
日常开发
测试类继承 PHPUnit\Framework\TestCase
use PHPUnit\Framework\TestCase;

class BackBlackServiceTest extends TestCase{}

测试方法 public function testBackBlackService($data, $expect), 需是public, 以test开头

多用例可使用注解 @dataProvider dataProvider
dataProvider 方法需为public, 参数个数,类型可按需自定义

```
建议$data按表格式组装数据，  mock方法，指向预期值 [’myFunc‘ => 'myFuncExpectData']
```

public function serviceProvider()
{

```
    return [
      '测试用例名1'=>[$data,$expect],

      '测试用例名2'=>[$data,$expect]

    ];
```

}

断言时可增加用例名作为报错message

```
         public function testBackBlackService(){
```

this−>assertEquals(this->assertEquals(this−>assertEquals(expected, $actual, $this->getName());

```
         }
```

常用技巧
对象mock(原则上需要mock的类为操作db，调用第三方服务的类)
可注入对象使用一般方法
\Mockery::mock(MyClass::class)

```
   无需注入(基于代码现状, 不改动现有代码)
           \Mockery::mock("overload:" . MyClass::class);

           \Mockery::mock("alias:" . MyClass::class);         静态方法

   使用overload:  alias:  需配合以下注解使用
```

- @runInSeparateProcess
- @runTestsInSeparateProcesses
- @preserveGlobalState disabled

使用shouldReceive定义mock方法，返回值
\Mockery::mock("alias:" . MyClass::class)->shouldReceive('myFunc')->andReturn($data['myFunc'] ?? []);

replyValidation−>shouldReceive(′valiate′)−>andThrow(newValidException(replyValidation->shouldReceive('valiate')->andThrow(new ValidException(replyValidation−>shouldReceive(′valiate′)−>andThrow(newValidException(data['validate'])); //需要抛异常

多用例时需增加Mockery::close()方法
public function tearDown(): void
{
parent::tearDown();
Mockery::close();
}

特殊技巧
链式操作
person=ResumeService::module(′base′)−>findbyuserid((int)person = ResumeService::module('base')->find\_by\_user\_id((int)person=ResumeService::module(′base′)−>findb​yu​seri​d((int)userId);
$resume\_service->shouldReceive('module->find\_by\_user\_id')
同一个方法调用多次
参数区分
withAnyArgs() 任意传参

```
      按传参返回 with(...$args)     \Mockery::spy('alias:' . Config::class)->shouldReceive('getConfigItem')->with("a")->andReturn($data1);

次数区分
    atLeast()->times(2) 最少调用次数

    atMost()->times(2)  最多调用次数

    times(3)  明确调用次数，多了， 少了都不行。

   \Mockery::spy('alias:' . Config::class)->shouldReceive('getConfigItem')->atLeast()->times(2)->andReturn($data1, $data2);
```

静态常量
使用“alias:” mock的类无法访问该类的常量，静态变量

使用自定义类，方式注入

class ConstMap
{
public const CONTRACT\_RESUME = 'View'; //简
public static $remain\_field = 'SurplusNum';

}

\Mockery::mock('alias:' . ContractService::class, ConstMap::class);

魔术方法
类里面未定义属性，使用魔术方法\_\_get($name) 访问

\Mockery::mock('overload:' . CompanyComponent::class)->shouldReceive('\_\_construct')->andSet('company\_name', '公司名');

代码注解使用
通过phpunit.xml 定义，测试用例常量 如 inPhpUnit 跳过测试用例无法覆盖代码， 如register\_shutdown\_function
!defined('inPhpUnit') && register\_shutdown\_function(function(){});

使用注解跳过相关代码块覆盖
// @codeCoverageIgnoreStart

```
 //@codeCoverageIgnoreEnd
```

phpunit.xml
phpunit.xml (phpunit9)
关注参数 forceCoversAnnotation="false"

```
<coverage></coverage>   覆盖源文件配置
```

xml version="1.0" encoding="UTF-8"?

src

tests

phpunit.xml (phpunit8.5)
关注参数 forceCoversAnnotation="false"

```
<whitelist></whitelist>   覆盖源文件配置
```

xml version="1.0" encoding="UTF-8"?

tests

src

IDE支持
点选phpunit.xml, 或者指定用例, 更多运行/调试，使用覆盖率运行

命令行
全部覆盖率

```
 php -dxdebug.mode=coverage /Users/******/composer/vendor/phpunit/phpunit/phpunit  --configuration phpunit.xml

 指定测试

 php -dxdebug.mode=coverage /Users/******/composer/vendor/phpunit/phpunit/phpunit  --configuration phpunit.xml tests/unit/Service/Resume/KickFavoriteServiceTest.php
```

开发建议
db层不封装业务逻辑

```
对象实体能以对象形式代替数组形式返回， 便于模拟数据。

数据层，第三方服务支持注入，简化mock难度
```

相关文档
https://phpunit.readthedocs.io/en/9.5/

https://phpunit.readthedocs.io/zh\_CN/latest/ (中文文档相对滞后)

http://docs.mockery.io/en/latest/index.html

下一篇

[### 阿里云盘 挂载本地挂载](https://www.plbear.com/posts/a-li-yun-pan-gua-zai-ben-di-gua-zai//)
