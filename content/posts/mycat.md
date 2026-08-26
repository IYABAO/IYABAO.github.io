---
title: "微服务架构基于Mycat分库分表及读写分离的配置实战"
date: 2019-08-01
draft: false
slug: "mycat"
---

> 本文以在线商城系统为主要业务场景，分别定义了用户、商品和订单三个微服务，并实现三个微服务所涉及到的数据库和表的水平拆分、垂直拆分和读写分离的相关配置。

# 概念

先来看一下本文业务场景中涉及到的数据库表。

![微服务架构基于Mycat分库分表及读写分离的配置实战](http://p9.pstatp.com/large/pgc-image/4ef055d806c046bcb286caf945fb019e)

单机环境的数据库结构

**1、水平拆分**

将同一个表的数据进行分块保存到不同的数据库中，这些数据库中的表结构完全相同。

我们把数据库水平拆分成三个数据库，每个数据库中的表结构是完全相同的，不同数据库中表的记录条数不同。

![微服务架构基于Mycat分库分表及读写分离的配置实战](http://p1.pstatp.com/large/pgc-image/6fe8a9205795466886ded8fcdedb0d8e)

水平拆分后的数据库结构

**2、垂直拆分**

按功能模块拆分，比如分为订单库、商品库、用户库...这种方式多个数据库之间的表结构不同。

按用户库、商品库和订单库实现的不同功能进行垂直拆分。

![微服务架构基于Mycat分库分表及读写分离的配置实战](http://p1.pstatp.com/large/pgc-image/e00c8023747d430797d51fdf0f5be00d)

垂直拆分数据库结构

**3、读写分离**

读写分离一般来说都是通过主从复制（Master-Slave）的方式来同步数据，再通过读写分离（MySQL-Proxy）来提升数据库的并发负载能力这样的方案来进行部署与实施的。

![微服务架构基于Mycat分库分表及读写分离的配置实战](http://p3.pstatp.com/large/pgc-image/cbd8c22935544d82a243d225f3dc9394)

数据库读写分离架构

**4、Mycat介绍**

首先，Mycat是数据库分库分表中间件。这是Mycat官网（http://mycat.io/）定义的一句话。个人理解它相当于一个数据库的代理，将拆分后的数据库在逻辑上重新封装，对外暴露和未拆分之前是同样的数据库结构。

按照上面的业务场景，将数据库进行垂直拆分再水平拆分。按三个业务模块进行垂直拆分，在分别水平拆分成3个数据库，最后形成9个数据库。再按一主一从的方式进行读写分离配置，即一共18个数据库。

![微服务架构基于Mycat分库分表及读写分离的配置实战](http://p1.pstatp.com/large/pgc-image/137595b896e949e7bfd8dd56a9671501)

垂直、水平拆分及读写分离架构

1、 不同的微服务连接Mycat中间件。访问对应业务模块的数据库。

2、 Mycat中的三个数据库在物理上并不存在，是逻辑上的三个数据库。

3、 Master将三个业务模块的数据库表进行水平拆分，各库中的表结构相同，数据不同。并作为主数据库完成数据的写操作。

4、 Slave将三个业务模块的数据库表进行水平拆分，各库中的表结构相同，数据不同。并作为从数据库完成数据的读操作。

5、 Master和Slave实现数据同步操作。

# Mycat配置

**概览**

Mycat官网下载1.6.7-release版本解压后的目录结构包括bin、catlet、conf、lib和version.txt。其中conf目录中存放大量的配置文件，其中最主要的是有server.xml、schema.xml和rule.xml三个文件。

**1、server.xml**

server.xml 包含mycat的系统配置信息，它有两个标签，分别是user和system。

user标签

![微服务架构基于Mycat分库分表及读写分离的配置实战](http://p1.pstatp.com/large/pgc-image/f45c49c024e74b3a9478f7edeb9b16c7)

server的user标签

name：user的名称，下面的schema.xml文件中的数据库访问用户名。

password：访问密码。

schemas：下面schema.xml文件中的逻辑数据库名称，这里把三个都配置上了，方便操作。

readOnly：说明此用户只有读权限，没有写权限。上面配置中，如果使用user用户登录，则只能进行读操作。

system标签：

这里只着重介绍sequnceHanlderType属性，这里是Mycat主键的生成策略。因为现在是把数据进行了多节点的分片拆分。所以使用主键的自增就会造成主键冲突的问题。

sequnceHanlderType属性有三个选项。0代表本地文件，1代表数据库方式，2代表时间戳方式。这里可以根据需要自行配置。数据库方式的话需要对dataNode创建一些相关的函数才能使用。本地文件是使用conf/sequence\_conf.properties文件内容进行维护的。具体详见该文件的内容。

![微服务架构基于Mycat分库分表及读写分离的配置实战](http://p3.pstatp.com/large/pgc-image/32b7d5cbf1c342c1bf30f8f4f595eed2)

sequnceHanlderType配置

**2、schema.xml**

这里将数据库从逻辑上分为三个，javapupil\_user(用户库)、javapupil\_goods(商品库)、javapupil\_order(订单库)。

![微服务架构基于Mycat分库分表及读写分离的配置实战](http://p3.pstatp.com/large/pgc-image/7c00ec461b08456784e2ae3721443fed)

schema-table-datanode配置

table配置：

name：表名。

primaryKey：表中的主键列名。

dataNode：数据库表所在的数据节点名称。

rule：数据插入规则，rule.xml小节中详述。

![微服务架构基于Mycat分库分表及读写分离的配置实战](http://p1.pstatp.com/large/pgc-image/05401142d526494880bc0f9b56832921)

dataNode配置

dataNode配置：

name：数据节点名称。

dataHost：数据主机名称。下面详述。

database：数据库名称。

![微服务架构基于Mycat分库分表及读写分离的配置实战](http://p3.pstatp.com/large/pgc-image/5a3f6b863ca14942b764c8559dc1d6ce)

dataHost配置

name：dataHost的名称。

balance：负载均衡类型。

（1）0不开启读写分离机制，所有读操作都发送到当前可用的writeHost 上。

（2）全部的 readHost 与 stand by writeHost 参与 select 语句的负载均衡，简单的说，当双主双从模式(M1->S1，M2->S2，并且 M1 与 M2 互为主备)，正常情况下，M2,S1,S2 都参与 select 语句的负载均衡。

（3）balance="2"，所有读操作都随机的在 writeHost、 readhost 上分发。

（4）balance="3"，所有读请求随机的分发到 wiriterHost 对应的 readhost 执行，writerHost 不负担读压力，注意 balance=3 只在 1.4 及其以后版本有，1.3 没有。

所以，这里使用1和3都是可以的。

writeType：

（1）writeType="0", 所有写操作发送到配置的第一个 writeHost，第一个挂了切到还生存的第二个riteHost，重新启动后已切换后的为准，切换记录在配置文件中:dnindex.properties.

（2）writeType="1"，所有写操作都随机的发送到配置的 writeHost，1.5 以后废弃不推荐。

heartbeat：心跳，判断该数据库是否存活。

writeHost：Master写操作的数据库配置

readHost：Slave读操作的数据库配置。如果有多个Slave，这里可以配置多个。

**3、rule.xml**

规则配置文件。

```
<table name="user" primaryKey="id" dataNode="dn1,dn2,dn3" rule="mod-long" />
```

rule属性的mod-long在此配置文件中进行设置。这里表示的是“取模”规则。

rule.xml文件中会找到如下代码：

![微服务架构基于Mycat分库分表及读写分离的配置实战](http://p1.pstatp.com/large/pgc-image/ec54c97105c443b28c1926bb19416037)

mod-long配置

columns：表示利用哪个列进行操作，这里是用id列进行操作。这里的id列必须是整型。

algorithm：表示具体的算法，这里的算法是mod-long。

那么mod-long是怎么实现的呢：

![微服务架构基于Mycat分库分表及读写分离的配置实战](http://p3.pstatp.com/large/pgc-image/65fc61b83d1b4598975cd44d7cedc0d4)

实现mod-long的java类

class：io.mycat.route.funciton.PartitionByMod。取模的算法是通过这个类实现的。

count：表示一共有几个数据节点，这里配置3个，也就是当生成的id与3取模，得到的余数是几就将该条记录插入到哪个数据库中。比如余数是0，就进入dn1中，余数是1就进入dn2中，余数是2就进入dn3中。

# 应用配置

**1、数据库连接配置**

本例中因为使用了Mycat作为数据库中间件，代理了数据库的分库分表。所以应用程序只需要连接Mycat中的逻辑数据库javapupil\_user、javapupil\_goods、javapupil\_order即可。

jdbc:mysql://192.168.1.145:8066/javapupil\_user

jdbc:mysql://192.168.1.145:8066/javapupil\_ goods

jdbc:mysql://192.168.1.145:8066/javapupil\_order

注意：Mycat默认的端口是8066。

**2、sql配置**

当程序需要插入数记录时，在insert into中需要加入如下的Sql代码：

next value for MYCATSEQ\_GLOBAL，这里的GLOBAL是在conf/sequence\_conf.properties中进行的配置。

![微服务架构基于Mycat分库分表及读写分离的配置实战](http://p1.pstatp.com/large/pgc-image/57be1f8820844309987b7f329f8eb7c2)

SEQ\_GLOBAL配置

# 总结

本文着重介绍了基于Mycat的Mysql分库分表及读写分离的配置。使用了垂直和水平相结合的方式对数据库进行拆分。Mycat是一款强大的分库分表的中间件，配置简单，运行稳定。希望本文能给正在研究微服务架构分库分表读写分离的朋友带来一点启发。
