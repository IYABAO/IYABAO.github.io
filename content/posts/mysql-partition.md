---
title: "MySQL表分区（partition）创建、查询、删除以及重建分区等等操作"
date: 2019-08-01
draft: false
summary: "MySQL 表分区实战手册：Range、Hash、Key、List 各分区类型详解，涵盖分区表创建、查询、删除与重建等操作演示，助力大表数据管理与查询性能优化。"
slug: "mysql-partition"
---

下面演示MySQL Range类型分区的操作，其他类型的分区还有Hash、Key、List等等。

分区优点：

1. 分区可以分在多个磁盘，存储更大一点。

2. 根据查找条件，也就是where后面的条件，查找只查找相应的分区不用全部查找了。

3. 进行大数据搜索时可以进行并行处理。

4. 跨多个磁盘来分散数据查询，来获得更大的查询吞吐量.

# **1. 创建演示表 tr，设置range 类型分区**

> CREATE TABLE tr (id INT, name VARCHAR(50), purchased DATE)
>
> PARTITION BY RANGE( YEAR(purchased) ) (
>
> PARTITION p0 VALUES LESS THAN (1990),
>
> PARTITION p1 VALUES LESS THAN (1995),
>
> PARTITION p2 VALUES LESS THAN (2000),
>
> PARTITION p3 VALUES LESS THAN (2005),
>
> PARTITION p4 VALUES LESS THAN (2010),
>
> PARTITION p5 VALUES LESS THAN (2015)
>
> );

# **2. 插入演示数据**

> INSERT INTO tr VALUES
>
> (1, 'desk organiser', '2003-10-15'),
>
> (2, 'alarm clock', '1997-11-05'),
>
> (3, 'chair', '2009-03-10'),
>
> (4, 'bookcase', '1989-01-10'),
>
> (5, 'exercise bike', '2014-05-09'),
>
> (6, 'sofa', '1987-06-05'),
>
> (7, 'espresso maker', '2011-11-22'),
>
> (8, 'aquarium', '1992-08-04'),
>
> (9, 'study desk', '2006-09-16'),
>
> (10, 'lava lamp', '1998-12-25');

**3. 查询分区 p2中的数据**

> SELECT \* FROM tr
>
> WHERE purchased BETWEEN '1995-01-01' AND '1999-12-31';

也可以使用分区参数partition 获取相同的信息。

# SELECT \* FROM tr PARTITION (p2);

![MySQL表分区（partition）创建、查询、删除以及重建分区等等操作](http://p1.pstatp.com/large/pgc-image/f4140e2646e9492e9ffa88179cc77f81)

# **4. 删除分区**

下面指定删除分区p2，执行如下命令。

> ALTER TABLE tr DROP PARTITION p2;

需要注意的是：**当删除一个分区时，分区中的数据也会被删除。**

再次执行前面的SELECT 脚本，没有任何数据返回。

> SELECT \* FROM tr
>
> WHERE purchased BETWEEN '1995-01-01' AND '1999-12-31';

返回结果：0 row(s) returned

> SELECT \* FROM tr PARTITION (p2);

出现异常：Error Code: 1735. Unknown partition 'p2' in table 'tr'

# **5. 查看表tr的分区定义**

> SHOW CREATE TABLE tr;

![MySQL表分区（partition）创建、查询、删除以及重建分区等等操作](http://p1.pstatp.com/large/pgc-image/f8cd0de264854e089b8d2d345ed7a06e)

partition p2 已经不存在了。

现在插入 purchased 列数据在1995-01-01 到 2004-12-31 之间的数据，新的行数据将存储在 partition p3中。

> INSERT INTO tr VALUES (11, 'pencil holder', '1995-07-12');
>
> SELECT \* FROM tr WHERE purchased BETWEEN '1995-01-01' AND '2004-12-31';
>
> select \* from tr partition(p3);

![MySQL表分区（partition）创建、查询、删除以及重建分区等等操作](http://p9.pstatp.com/large/pgc-image/748a57d73a7747f0af24463daac5f7c0)

# **6. RANGE 重建分区**

将原来的 p0,p1 分区合并起来，放到新的 p0 分区中。

在分区合并之前，先检查一下 p0和p1 分区中的数据。

select \* from tr partition(p0,p1);

输出结果：3条记录

![MySQL表分区（partition）创建、查询、删除以及重建分区等等操作](http://p3.pstatp.com/large/pgc-image/01ba2e3ed4054d9a9d4f4f190d1617dd)

下面进行分区合并操作。

ALTER TABLE tr REORGANIZE PARTITION p0, p1 INTO (PARTITION p0 VALUES LESS THAN (1995));

合并操作完成之后，分区 p1 已经不存在了，新的 p0 分区数据记录如下，3条记录。

select \* from tr partition(p0);

![MySQL表分区（partition）创建、查询、删除以及重建分区等等操作](http://p1.pstatp.com/large/pgc-image/2ee35a9b924841ee8aab57323ce53e76)

查看更新后的分区定义，分区p0的范围进行了重新定义。

SHOW CREATE TABLE tr;

![MySQL表分区（partition）创建、查询、删除以及重建分区等等操作](http://p9.pstatp.com/large/pgc-image/52c3a3b52b0b48d59b1511ca65a5e027)

打开MySQL的数据目录，查看分区的表空间文件如下。

![MySQL表分区（partition）创建、查询、删除以及重建分区等等操作](http://p1.pstatp.com/large/pgc-image/8757eccc655e4845aec2b263e6abc1e6)

# **7. 子分区**

子分区是分区表中每个分区的再次分割，子分区既可以使用HASH分区，也可以使用KEY分区。这也被称为复合分区（composite partitioning）。

子分区的几点注意事项：

- 如果一个分区中创建了子分区，其他分区也要有子分区。
- 如果创建了子分区，每个分区中的子分区数必有相同。
- 同一分区内的子分区，名字不相同，不同分区内的子分区名字可以相同。
- 由于分区是RANGE和LIST分区，所以删除分区也是同RANGE和LIST分区一样，这里只能对每个分区进行删除，不能针对每个子分区进行删除操作，删除分区后子分区连同数据一并被删除。

**子分区由两种创建方法：**

一种是不定义每个子分区的名字和路径由分区决定；

二是定义每个子分区的分区名和各自的路径；

（1）不定义每个子分区

表名称：tb\_sub

> CREATE TABLE tb\_sub (id INT, purchased DATE)
>
> PARTITION BY RANGE( YEAR(purchased) )
>
> SUBPARTITION BY HASH( TO\_DAYS(purchased) )
>
> SUBPARTITIONS 2 (
>
> PARTITION p0 VALUES LESS THAN (1990),
>
> PARTITION p1 VALUES LESS THAN (2000),
>
> PARTITION p2 VALUES LESS THAN MAXVALUE
>
> );

分区表空间文件如下。

![MySQL表分区（partition）创建、查询、删除以及重建分区等等操作](http://p3.pstatp.com/large/pgc-image/736fdd7f0a9f4f588d85d7bfbccbcf26)

查看系统中表tb\_sub 信息：

> SELECT PARTITION\_NAME,PARTITION\_METHOD,PARTITION\_EXPRESSION,PARTITION\_DESCRIPTION,TABLE\_ROWS,SUBPARTITION\_NAME,SUBPARTITION\_METHOD,SUBPARTITION\_EXPRESSION
>
> FROM information\_schema.PARTITIONS
>
> WHERE TABLE\_SCHEMA=SCHEMA() AND TABLE\_NAME='tb\_sub';

![MySQL表分区（partition）创建、查询、删除以及重建分区等等操作](http://p3.pstatp.com/large/pgc-image/5b927bdc92f641d9837cec790f803278)

（2）定义每个子分区

定义子分区可以为每个子分区定义具体的分区名和分区路径。

> CREATE TABLE tb\_sub\_ev (id INT, purchased DATE)
>
> PARTITION BY RANGE( YEAR(purchased) )
>
> SUBPARTITION BY HASH( TO\_DAYS(purchased) ) (
>
> PARTITION p0 VALUES LESS THAN (1990) (
>
> SUBPARTITION s0,
>
> SUBPARTITION s1
>
> ),
>
> PARTITION p1 VALUES LESS THAN (2000) (
>
> SUBPARTITION s2,
>
> SUBPARTITION s3
>
> ),
>
> PARTITION p2 VALUES LESS THAN MAXVALUE (
>
> SUBPARTITION s4,
>
> SUBPARTITION s5
>
> )
>
> );

插入测试记录：

> INSERT INTO tb\_sub\_ev() VALUES(1,'1989-01-01'),(2,'1989-03-19'),(3,'1989-04-19');

从查询结果中，可以看到3条记录分表存储在2个不同的子分区中。

![MySQL表分区（partition）创建、查询、删除以及重建分区等等操作](http://p3.pstatp.com/large/pgc-image/9bec9e47cfe9407f9ac5a1350610b12d)

查看如下查询语言的执行计划：

> explain select \* from tb\_sub where purchased='1989-01-01';
>
> explain select \* from tb\_sub where purchased='1989-03-19';
>
> explain select \* from tb\_sub where purchased='1989-04-19';

![MySQL表分区（partition）创建、查询、删除以及重建分区等等操作](http://p1.pstatp.com/large/pgc-image/362381940f1c4c6991fba01dc062149a)

# **8. 移除表的分区**

注意：使用remove移除分区是仅仅移除分区的定义，并不会删除数据和drop PARTITION不一样，后者会连同数据一起删除。

ALTER TABLE tb\_sub REMOVE PARTITIONING;

移除分区之后，再次查询表中的数据，确认表的数据依然存在。

![MySQL表分区（partition）创建、查询、删除以及重建分区等等操作](http://p3.pstatp.com/large/pgc-image/ecf5574015af49259b8e3a153455f093)

查看表结构，确认表分区已经成功移除了。

show create table tb\_sub;

![MySQL表分区（partition）创建、查询、删除以及重建分区等等操作](http://p1.pstatp.com/large/pgc-image/2336de35079440b8bded63559396d1b0)
