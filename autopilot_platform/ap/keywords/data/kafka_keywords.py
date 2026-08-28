"""Kafka 关键字。关键字 id 见 keyword_defs 定义（参考 manifests/KafkaKeyword.json）。

kafka-python 库懒加载为可选依赖，仅在真正发送/消费时 import。
producer/consumer 工厂可通过 ctx.kafka_producer_factory / ctx.kafka_consumer_factory 注入，便于测试。
"""

from __future__ import annotations

from ..registry import keyword, KeywordError
from ..context import ExecutionContext


# --------------------------------------------------------------------------- #
# 懒加载 + 工厂                                                                #
# --------------------------------------------------------------------------- #
def _hosts_list(hosts: str):
    return [h.strip() for h in str(hosts).split(",") if h.strip()]


def _default_producer(hosts: str):
    try:
        # noinspection PyUnresolvedReferences,PyPackageRequirements
        from kafka import KafkaProducer
    except ImportError as e:  # pragma: no cover
        raise KeywordError("未安装 kafka-python，pip install kafka-python") from e
    return KafkaProducer(bootstrap_servers=_hosts_list(hosts))


def _default_consumer(hosts: str):
    try:
        # noinspection PyUnresolvedReferences,PyPackageRequirements
        from kafka import KafkaConsumer
    except ImportError as e:  # pragma: no cover
        raise KeywordError("未安装 kafka-python，pip install kafka-python") from e
    return KafkaConsumer(bootstrap_servers=_hosts_list(hosts))


def _producer(ctx: ExecutionContext, hosts: str):
    factory = getattr(ctx, "kafka_producer_factory", None)
    return factory(hosts) if factory else _default_producer(hosts)


def _consumer(ctx: ExecutionContext, hosts: str):
    factory = getattr(ctx, "kafka_consumer_factory", None)
    return factory(hosts) if factory else _default_consumer(hosts)


# --------------------------------------------------------------------------- #
# 读取辅助                                                                     #
# --------------------------------------------------------------------------- #
def _decode(value, fmt: str) -> str:
    if isinstance(value, bytes):
        try:
            return value.decode(fmt or "UTF-8", errors="replace")
        except (LookupError, TypeError):
            return value.decode("utf-8", errors="replace")
    return "" if value is None else str(value)


def _consume(ctx: ExecutionContext, hosts, topic, partition, begin_offset,
             num, filter_words, fmt):
    """从指定 partition/offset 起读取 num 条（经 filter 过滤后），返回 list[str]。

    begin_offset: -1=最新(tail), -2=最旧(head), >=0=指定 offset。
    """
    # noinspection PyUnresolvedReferences,PyPackageRequirements
    from kafka import TopicPartition, OffsetAndMetadata  # noqa: F401  懒加载校验

    consumer = _consumer(ctx, hosts)
    part = int(partition)
    tp = TopicPartition(topic, part)
    consumer.assign([tp])

    n = int(num)
    if begin_offset == -1:  # 最新：从末尾往前取 num 条
        consumer.seek_to_end(tp)
        end = consumer.position(tp)
        start = max(0, end - n)
        consumer.seek(tp, start)
    elif begin_offset == -2:  # 最旧
        consumer.seek_to_beginning(tp)
    else:
        consumer.seek(tp, int(begin_offset))

    results = []
    for record in consumer:
        text = _decode(getattr(record, "value", record), fmt)
        if not filter_words or filter_words in text:
            results.append(text)
        if len(results) >= n:
            break
    # noinspection PyBroadException
    try:
        consumer.close()
    except Exception:
        pass
    return results


def _result_value(messages):
    """多条结果：单条直接返回，多条返回 list。"""
    if len(messages) == 1:
        return messages[0]
    return messages


# --------------------------------------------------------------------------- #
# 关键字                                                                       #
# --------------------------------------------------------------------------- #
@keyword("produceKafkaMsg", name="发送Kafka消息(文件)", category="Http",
         out_params=["offset"], legacy_impl="KafkaKeyword:produceMsg")
def produce_kafka_msg(ctx: ExecutionContext, msg="", topic="", partition="-1",
                      hosts="", offset="", **_kw) -> dict:
    producer = _producer(ctx, hosts)
    value = msg.encode("utf-8") if isinstance(msg, str) else msg
    part = int(partition)
    kwargs = {} if part < 0 else {"partition": part}
    future = producer.send(topic, value=value, **kwargs)
    return_offset = ""
    # noinspection PyBroadException
    try:
        meta = future.get(timeout=30) if hasattr(future, "get") else future
        return_offset = str(getattr(meta, "offset", meta))
    except Exception:
        pass
    # noinspection PyBroadException
    try:
        producer.flush()
    except Exception:
        pass
    return {offset: return_offset} if offset else {}


# noinspection PyShadowingBuiltins
@keyword("readHeadTailMsg", name="读取最新/旧的Kafka消息", category="Http",
         out_params=["var"], legacy_impl="KafkaKeyword:readHeadTailMsg")
def read_head_tail_msg(ctx: ExecutionContext, pattern="最新", num="10", topic="",
                       partition="0", hosts="", filter="", format="UTF-8",
                       var="", **_kw) -> dict:
    begin_offset = -1 if "新" in str(pattern) else -2
    messages = _consume(ctx, hosts, topic, partition, begin_offset,
                        num, filter, format)
    return {var: _result_value(messages)} if var else {}


# noinspection PyShadowingBuiltins
@keyword("readKafkaMsg", name="读取指定offset的消息", category="Http",
         out_params=["var"], legacy_impl="KafkaKeyword:readAnyOffsetMsg")
def read_any_offset_msg(ctx: ExecutionContext, offset="", num="10", topic="",
                        partition="0", hosts="", filter="", format="UTF-8",
                        var="", **_kw) -> dict:
    messages = _consume(ctx, hosts, topic, partition, int(offset),
                        num, filter, format)
    return {var: _result_value(messages)} if var else {}
