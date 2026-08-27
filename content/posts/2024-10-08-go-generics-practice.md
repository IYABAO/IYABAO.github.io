---
title: "Go 泛型实战：从 any 到类型参数的优雅抽象设计"
date: 2024-10-08T14:00:00+08:00
draft: false
tags: ["Go", "泛型", "类型参数", "架构设计", "最佳实践"]
categories: ["Go开发"]
summary: "Go 1.18+ 泛型的实战应用，从 any 接口到类型参数的优雅抽象，涵盖通用数据结构、工具函数、泛型约束、性能对比，以及泛型的边界和不适用场景。"
---

Go 1.18 引入泛型后，终于不用到处写 `interface{}` 然后做类型断言了。但泛型不是银弹，用不好反而让代码更难读。2024年我们在项目里逐步引入泛型，踩了不少坑，也总结了一些最佳实践。今天把实战经验分享出来。

## 一、泛型解决了什么问题

没有泛型的时候，写通用逻辑很痛苦：

```go
// 没有泛型：用 interface{}，调用方要做类型断言
func Max(a, b interface{}) interface{} {
    switch av := a.(type) {
    case int:
        bv := b.(int)
        if av > bv { return av }
        return bv
    case float64:
        bv := b.(float64)
        if av > bv { return av }
        return bv
    // ... 每个类型都要写一遍
    }
    return nil
}

// 调用方要类型断言，容易panic
m := Max(3, 5).(int)
```

有了泛型：

```go
func Max[T Ordered](a, b T) T {
    if a > b { return a }
    return b
}

// 调用方不用类型断言，类型安全
m := Max(3, 5)  // m 是 int 类型
```

代码简洁、类型安全、性能好（编译时生成具体类型的代码，没有运行时反射开销）。

## 二、基础语法

### 类型参数

```go
// 单个类型参数
func Print[T any](x T) {
    fmt.Println(x)
}

// 多个类型参数
func Map[K comparable, V any](m map[K]V) []K {
    keys := make([]K, 0, len(m))
    for k := range m {
        keys = append(keys, k)
    }
    return keys
}

// 泛型类型
type Stack[T any] struct {
    items []T
}

func (s *Stack[T]) Push(item T) {
    s.items = append(s.items, item)
}

func (s *Stack[T]) Pop() (T, bool) {
    if len(s.items) == 0 {
        var zero T
        return zero, false
    }
    item := s.items[len(s.items)-1]
    s.items = s.items[:len(s.items)-1]
    return item, true
}
```

### 类型约束

```go
// 内置约束：any（任意类型）、comparable（可比较类型）
func Contains[T comparable](slice []T, target T) bool {
    for _, v := range slice {
        if v == target {
            return true
        }
    }
    return false
}

// 自定义约束：接口定义
type Ordered interface {
    ~int | ~int8 | ~int16 | ~int32 | ~int64 |
        ~uint | ~uint8 | ~uint16 | ~uint32 | ~uint64 |
        ~float32 | ~float64 |
        ~string
}

func Sort[T Ordered](slice []T) {
    sort.Slice(slice, func(i, j int) bool {
        return slice[i] < slice[j]
    })
}

// 带方法的约束
type Stringer interface {
    String() string
}

func ToStringSlice[T Stringer](items []T) []string {
    result := make([]string, len(items))
    for i, item := range items {
        result[i] = item.String()
    }
    return result
}
```

`~int` 表示底层类型是 int 的类型（包括 `type MyInt int`），这是 Go 泛型里很重要的一个设计。

## 三、实战场景

### 场景一：通用工具函数

项目里有大量重复的 slice/map 操作，用泛型封装成通用工具：

```go
// slice 工具
package sliceutil

func Map[T, R any](items []T, fn func(T) R) []R {
    result := make([]R, len(items))
    for i, item := range items {
        result[i] = fn(item)
    }
    return result
}

func Filter[T any](items []T, fn func(T) bool) []T {
    result := make([]T, 0)
    for _, item := range items {
        if fn(item) {
            result = append(result, item)
        }
    }
    return result
}

func Reduce[T, R any](items []T, initial R, fn func(R, T) R) R {
    acc := initial
    for _, item := range items {
        acc = fn(acc, item)
    }
    return acc
}

func GroupBy[T any, K comparable](items []T, keyFn func(T) K) map[K][]T {
    result := make(map[K][]T)
    for _, item := range items {
        key := keyFn(item)
        result[key] = append(result[key], item)
    }
    return result
}

// 使用
type User struct {
    ID   int
    Name string
    Age  int
    City string
}

users := []User{...}

// 提取所有用户名
names := sliceutil.Map(users, func(u User) string { return u.Name })

// 筛选杭州的用户
hangzhouUsers := sliceutil.Filter(users, func(u User) bool { return u.City == "杭州" })

// 按城市分组
usersByCity := sliceutil.GroupBy(users, func(u User) string { return u.City })

// 计算平均年龄
avgAge := sliceutil.Reduce(users, 0, func(acc int, u User) int { return acc + u.Age }) / len(users)
```

之前每个业务都要写一遍 Map/Filter/GroupBy，现在通用工具一套搞定，类型安全不用断言。

### 场景二：通用缓存

```go
package cache

import (
    "encoding/json"
    "time"
    "github.com/redis/go-redis/v9"
)

type Cache[T any] struct {
    redis *redis.Client
    ttl   time.Duration
}

func New[T any](redis *redis.Client, ttl time.Duration) *Cache[T] {
    return &Cache[T]{redis: redis, ttl: ttl}
}

func (c *Cache[T]) Get(key string) (T, bool) {
    var zero T
    data, err := c.redis.Get(context.Background(), key).Bytes()
    if err != nil {
        return zero, false
    }
    var value T
    if err := json.Unmarshal(data, &value); err != nil {
        return zero, false
    }
    return value, true
}

func (c *Cache[T]) Set(key string, value T) error {
    data, err := json.Marshal(value)
    if err != nil {
        return err
    }
    return c.redis.Set(context.Background(), key, data, c.ttl).Err()
}

func (c *Cache[T]) Delete(key string) error {
    return c.redis.Del(context.Background(), key).Err()
}

// 使用：不同类型的缓存，不用每个类型写一套
userCache := cache.New[User](redisClient, time.Hour)
jobCache := cache.New[Job](redisClient, 30*time.Minute)

user, ok := userCache.Get("user:1001")
job, ok := jobCache.Get("job:2001")
```

之前每个缓存类型都要写 Get/Set/Delete，现在泛型一行定义一个类型安全的缓存。

### 场景三：通用 Repository

```go
package repository

import "gorm.io/gorm"

type Repository[T any] struct {
    db *gorm.DB
}

func New[T any](db *gorm.DB) *Repository[T] {
    return &Repository[T]{db: db}
}

func (r *Repository[T]) GetByID(id int64) (*T, error) {
    var entity T
    if err := r.db.First(&entity, id).Error; err != nil {
        return nil, err
    }
    return &entity, nil
}

func (r *Repository[T]) Create(entity *T) error {
    return r.db.Create(entity).Error
}

func (r *Repository[T]) Update(entity *T) error {
    return r.db.Save(entity).Error
}

func (r *Repository[T]) Delete(id int64) error {
    var entity T
    return r.db.Delete(&entity, id).Error
}

func (r *Repository[T]) List(page, pageSize int) ([]T, int64, error) {
    var items []T
    var total int64
    r.db.Model(&items{}).Count(&total)
    err := r.db.Offset((page-1)*pageSize).Limit(pageSize).Find(&items).Error
    return items, total, err
}

// 使用：每个实体的 Repository 一行定义
userRepo := repository.New[User](db)
jobRepo := repository.New[Job](db)
resumeRepo := repository.New[Resume](db)

user, err := userRepo.GetByID(1001)
users, total, err := userRepo.List(1, 20)
```

基础 CRUD 不用每个实体写一遍，泛型 Repository 覆盖 80% 场景，复杂查询再在具体 Repository 里扩展。

## 四、泛型约束的高级用法

### 约束组合

```go
// 组合多个约束
type Entity interface {
    HasID
    Timestamps
}

type HasID interface {
    GetID() int64
}

type Timestamps interface {
    GetCreatedAt() time.Time
    GetUpdatedAt() time.Time
}

// 只有同时实现了 HasID 和 Timestamps 的类型才能用
func LogEntity[T Entity](entity T) {
    fmt.Printf("ID: %d, Created: %s\n", entity.GetID(), entity.GetCreatedAt())
}
```

### 类型集与运算符

```go
// 约束里可以用 | 联合类型，~ 表示底层类型
type Number interface {
    ~int | ~int8 | ~int16 | ~int32 | ~int64 |
        ~uint | ~uint8 | ~uint16 | ~uint32 | ~uint64 |
        ~float32 | ~float64
}

// Number 约束的类型可以用 + - * / 运算符
func Sum[T Number](items []T) T {
    var sum T
    for _, item := range items {
        sum += item
    }
    return sum
}
```

Go 1.21 引入了 `golang.org/x/exp/constraints` 包（后来移到标准库 `cmp`），提供了 Ordered、Integer、Float 等常用约束，不用自己写。

## 五、性能对比

泛型代码是编译时生成具体类型的实现，没有运行时反射开销，性能和手写具体类型的代码几乎一样：

```
BenchmarkMaxGeneric-8     100000000    10.2 ns/op    0 B/op    0 allocs/op
BenchmarkMaxInterface-8    30000000    45.6 ns/op    8 B/op    1 allocs/op
BenchmarkMaxHandwritten-8  100000000    10.1 ns/op    0 B/op    0 allocs/op
```

泛型版本和手写版本性能几乎一致，比 interface{} 版本快 4 倍，且没有内存分配。

## 六、不适用场景

泛型不是万能的，这些场景不建议用：

1. **方法不能有额外类型参数**：Go 的方法不支持定义自己的类型参数，只能用结构体的类型参数。如果需要方法级别的泛型，只能用函数
2. **类型断言不可避免时**：如果逻辑里需要大量类型判断和断言，泛型帮不上忙，用 interface{} + 类型 switch 更直接
3. **API 设计复杂**：泛型参数太多会让 API 很难理解，超过 2-3 个类型参数就要考虑是不是设计有问题
4. **简单场景过度设计**：一个只在一个地方用的函数，没必要抽成泛型。泛型的价值在于复用，只用一次的代码泛型化是增加复杂度
5. **运行时动态类型**：需要根据运行时类型做不同处理的场景（如序列化框架），泛型编译时确定类型，反而不灵活

## 七、踩坑经验

1. **零值处理**：泛型函数里返回零值要用 `var zero T`，不能用 nil（因为 T 可能是值类型）。早期经常写 `return nil, false` 编译报错
2. **方法集限制**：泛型类型的方法只能用结构体定义时的类型参数，不能在方法里新加类型参数。需要方法级泛型时改成普通函数
3. **约束里的 ~**：自定义类型 `type MyInt int` 如果约束里写 `int` 不包含 MyInt，必须写 `~int`。这个细节很容易忘，导致自定义类型用不了泛型函数
4. **编译错误信息难懂**：泛型的编译错误信息有时很绕，特别是约束不满足时。遇到看不懂的错误，先简化代码定位问题
5. **接口和泛型的选择**：如果只需要调用方法，用接口更简单；需要操作具体类型（如比较、算术运算），用泛型。两者不是互斥的，可以组合用
6. **不要为了泛型而泛型**：看到重复代码就想抽泛型是新手常犯的。先问自己：这个逻辑真的会被多个类型复用吗？如果只有一个类型用，写具体类型的代码更清晰

## 八、总结

Go 泛型实战核心：

1. **工具函数优先**：slice/map 的 Map/Filter/Reduce/GroupBy 等通用操作是泛型最典型的应用场景，收益最大
2. **通用基础设施**：缓存、Repository、队列等基础设施用泛型，一套代码支持所有类型
3. **类型约束设计**：合理使用 any、comparable、Ordered 等约束，自定义约束要考虑 ~ 底层类型
4. **性能无损**：编译时生成具体类型代码，性能和手写一致，比 interface{} 快且类型安全
5. **边界清晰**：方法不能有额外类型参数、运行时动态类型不适合泛型，这些场景用接口或具体类型
6. **不过度设计**：泛型的价值在于复用，只用一次的代码没必要泛型化，保持简单

Go 的泛型设计很克制——没有继承、没有通配符、没有方法级类型参数，这些限制让 Go 泛型比 Java/C# 的泛型简单很多，但也足够应对 80% 的场景。用好泛型的关键是"克制"——只在真正需要类型安全的复用场景用，不要为了炫技到处加类型参数。代码的可读性永远是第一位的。
