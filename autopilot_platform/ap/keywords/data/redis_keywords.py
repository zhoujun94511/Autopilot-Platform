"""Redis 关键字。关键字 id 见 keyword_defs 定义（参考 align-data-keywords.md）。redis 库懒加载。"""

from __future__ import annotations

from typing import Any

from ..registry import keyword, KeywordError
from ..context import ExecutionContext


def _manager(ctx: ExecutionContext) -> dict:
    mgr = getattr(ctx, "redis", None)
    if mgr is None:
        mgr = {}
        ctx.redis = mgr  # type: ignore[attr-defined]
    return mgr


def default_redis_factory(ip: str, port: int, password: str, db: int):
    try:
        # noinspection PyUnresolvedReferences,PyPackageRequirements
        import redis
    except ImportError as e:  # pragma: no cover
        raise KeywordError("未安装 redis 库。pip install redis") from e
    return redis.Redis(host=ip, port=port, password=password or None, db=db,
                       decode_responses=True)


# 测试可替换：ctx.redis_factory
def _factory(ctx: ExecutionContext):
    return getattr(ctx, "redis_factory", None) or default_redis_factory


# noinspection PyPep8Naming
@keyword("redis_connect_redis", name="连接Redis", category="Public",
         legacy_impl="RedisKeyword:connectRedis")
def connect_redis(ctx: ExecutionContext, alias="", redisIP="127.0.0.1",
                  redisPort="6379", redisPasswd="", **_kw) -> None:
    client = _factory(ctx)(redisIP, int(redisPort), redisPasswd, 0)
    _manager(ctx)[alias or ""] = client


def _client(ctx: ExecutionContext, alias: str):
    c = _manager(ctx).get(alias or "")
    if c is None:
        raise KeywordError(f"Redis 未连接（alias={alias!r}），请先 redis_connect_redis")
    return c


# noinspection PyPep8Naming
@keyword("redis_get_RedisVal", name="获取Redis值", category="Public",
         out_params=["redisValue"], legacy_impl="RedisKeyword:getRedisVal")
def get_redis_val(ctx: ExecutionContext, alias="", dbIndex="0", redisKey="",
                  redisValue="", **_kw) -> dict:
    c = _client(ctx, alias)
    if hasattr(c, "select"):
        # noinspection PyBroadException
        try:
            c.select(int(dbIndex))
        except Exception:
            pass
    return {redisValue: c.get(redisKey)}


# noinspection PyPep8Naming
@keyword("redis_set_RedisString", name="设置Redis字符串", category="Public",
         legacy_impl="RedisKeyword:setRedisString")
def set_redis_string(ctx: ExecutionContext, alias="", redisKey="",
                     redisValue="", dbIndex="0", **_kw) -> None:
    _c(ctx, alias, dbIndex).set(redisKey, redisValue)   # 按 dbIndex 切分片，避免误写 db0


# noinspection PyPep8Naming
@keyword("redis_del_RedisKey", name="删除Redis键", category="Public",
         legacy_impl="RedisKeyword:deleteRedisKey")
def del_redis_key(ctx: ExecutionContext, alias="", redisKey="", dbIndex="0",
                  delMode="精确匹配", **_kw) -> None:
    # dbIndex 切分片(防误删 db0)；delMode=模糊匹配 时按 redisKey 作前缀模式批量删
    c = _c(ctx, alias, dbIndex)
    if delMode == "模糊匹配":
        keys = c.keys(redisKey)
        if keys:
            c.delete(*keys)
    else:
        c.delete(redisKey)


@keyword("redis_quit_Redis", name="断开Redis", category="Public",
         legacy_impl="RedisKeyword:quitRedis")
def quit_redis(ctx: ExecutionContext, alias="", **_kw) -> None:
    c: Any = _manager(ctx).pop(alias or "", None)
    if c is not None:
        # noinspection PyBroadException
        try:
            c.close()
        except Exception:
            pass


# ===================== Redis 扩展数据结构关键字 =====================
# hash/set/sorted set/list/ttl/keys 等；复用上方 _client 取客户端。


def _select(c, db_index) -> None:
    """若客户端支持 select，则切换 db。"""
    if hasattr(c, "select"):
        # noinspection PyBroadException
        try:
            c.select(int(db_index))
        except Exception:
            pass


def _c(ctx, alias, db_index):
    c = _client(ctx, alias)
    _select(c, db_index)
    return c


# ---------------------------------------------------------------- 读取 (get)

# noinspection PyPep8Naming
@keyword("redis_get_RedisHashVal", name="获取redis中对应key的哈希域值",
         category="Public", out_params=["redisValue"],
         legacy_impl="RedisKeyword:getRedisHashVal")
def get_redis_hash_val(ctx: ExecutionContext, alias="", dbIndex="0", redisKey="",
                       field="", redisValue="", **_kw) -> dict:
    c = _c(ctx, alias, dbIndex)
    return {redisValue: c.hget(redisKey, field)}


# noinspection PyPep8Naming
@keyword("redis_get_RedisSet", name="获取redis中对应key的set集合值",
         category="Public", out_params=["redisValue"],
         legacy_impl="RedisKeyword:getRedisSet")
def get_redis_set(ctx: ExecutionContext, alias="", dbIndex="0", redisKey="",
                  redisValue="", **_kw) -> dict:
    c = _c(ctx, alias, dbIndex)
    members = c.smembers(redisKey)
    return {redisValue: list(members)}


# noinspection PyPep8Naming
@keyword("redis_get_RedisSortedSet", name="获取redis中对应key的有序集合值",
         category="Public", out_params=["redisValue"],
         legacy_impl="RedisKeyword:getRedisSortedSet")
def get_redis_sorted_set(ctx: ExecutionContext, alias="", dbIndex="0", redisKey="",
                         start="0", end="-1", redisValue="", **_kw) -> dict:
    c = _c(ctx, alias, dbIndex)
    return {redisValue: c.zrange(redisKey, int(start), int(end))}


# noinspection PyPep8Naming
@keyword("redis_get_RedisSortedSetScore", name="获取redis中对应key的有序集合值的权重",
         category="Public", out_params=["score"],
         legacy_impl="RedisKeyword:getRedisSortedSetScore")
def get_redis_sorted_set_score(ctx: ExecutionContext, alias="", dbIndex="0",
                               redisKey="", member="0", score="", **_kw) -> dict:
    c = _c(ctx, alias, dbIndex)
    val = c.zscore(redisKey, member)
    return {score: val}


# noinspection PyPep8Naming
@keyword("redis_get_RedisList", name="获取redis中对应key的List集合",
         category="Public", out_params=["redisValue"],
         legacy_impl="RedisKeyword:getRedisList")
def get_redis_list(ctx: ExecutionContext, alias="", dbIndex="0", redisKey="",
                   start="0", end="-1", redisValue="", **_kw) -> dict:
    c = _c(ctx, alias, dbIndex)
    return {redisValue: c.lrange(redisKey, int(start), int(end))}


# noinspection PyPep8Naming
@keyword("redis_get_key_ttl", name="获取redis中对应key的剩余生存时间",
         category="Public", out_params=["seconds"],
         legacy_impl="RedisKeyword:getRedisKeyTtl")
def get_redis_key_ttl(ctx: ExecutionContext, alias="", dbIndex="0", redisKey="",
                      seconds="", **_kw) -> dict:
    c = _c(ctx, alias, dbIndex)
    return {seconds: c.ttl(redisKey)}


# noinspection PyPep8Naming
@keyword("redis_get_keys", name="获取redis中匹配key", category="Public",
         out_params=["redisValue"], legacy_impl="RedisKeyword:getKeys")
def get_keys(ctx: ExecutionContext, alias="", dbIndex="0", redisKey="",
             redisValue="", **_kw) -> dict:
    c = _c(ctx, alias, dbIndex)
    return {redisValue: c.keys(redisKey)}


# ---------------------------------------------------------------- 写入 (set)

# noinspection PyPep8Naming
@keyword("redis_set_RedisHsh", name="设置redis中Hash数据", category="Public",
         legacy_impl="RedisKeyword:setRedisHash")
def set_redis_hash(ctx: ExecutionContext, alias="", dbIndex="0", redisKey="",
                   redisField="", redisValue="", **_kw) -> None:
    c = _c(ctx, alias, dbIndex)
    c.hset(redisKey, redisField, redisValue)


# noinspection PyPep8Naming
@keyword("redis_set_RedisSet", name="设置redis中set数据", category="Public",
         legacy_impl="RedisKeyword:setRedisSet")
def set_redis_set(ctx: ExecutionContext, alias="", dbIndex="0", redisKey="",
                  redisValue="", **_kw) -> None:
    c = _c(ctx, alias, dbIndex)
    # redisValue 可能是逗号分隔的多个成员
    members = [v for v in str(redisValue).split(",") if v != ""] or [redisValue]
    c.sadd(redisKey, *members)


# noinspection PyPep8Naming
@keyword("redis_set_RedisList", name="设置redis中list数据", category="Public",
         legacy_impl="RedisKeyword:setRedisList")
def set_redis_list(ctx: ExecutionContext, alias="", dbIndex="0", redisKey="",
                   redisValue="", **_kw) -> None:
    c = _c(ctx, alias, dbIndex)
    members = [v for v in str(redisValue).split(",") if v != ""] or [redisValue]
    c.lpush(redisKey, *members)


# noinspection PyPep8Naming
@keyword("redis_set_ScoredSet", name="设置redis中有序集合数据", category="Public",
         legacy_impl="RedisKeyword:setRedisScoredSet")
def set_redis_scored_set(ctx: ExecutionContext, alias="", dbIndex="0", redisKey="",
                         redisValue="", **_kw) -> None:
    c = _c(ctx, alias, dbIndex)
    # 解析 "member:score,member:score" 或 "member,score" 形式
    mapping = {}
    for pair in str(redisValue).split(","):
        pair = pair.strip()
        if not pair:
            continue
        sep = ":" if ":" in pair else None
        if sep:
            member, _, sc = pair.partition(":")
            mapping[member] = float(sc)
        else:
            # 单值，无 score，默认 0
            mapping[pair] = 0.0
    if mapping:
        c.zadd(redisKey, mapping)


# ---------------------------------------------------------------- 删除 (del)

# noinspection PyPep8Naming
@keyword("redis_del_RedisKey_withResult", name="删除redis中key数据并返回结果",
         category="Public", out_params=["result"],
         legacy_impl="RedisKeyword:deleteRedisKeyWithResult")
def delete_redis_key_with_result(ctx: ExecutionContext, alias="", dbIndex="0",
                                 redisKey="", delMode="精确匹配", result="",
                                 **_kw) -> dict:
    c = _c(ctx, alias, dbIndex)
    if delMode == "模糊匹配":
        keys = c.keys(redisKey)
        count = c.delete(*keys) if keys else 0
    else:
        count = c.delete(redisKey)
    return {result: count}


# noinspection PyPep8Naming
@keyword("redis_del_RedisScoredSet", name="删除redis中key对应的有序集合member",
         category="Public", legacy_impl="RedisKeyword:deleteRedisScoredSet")
def delete_redis_scored_set(ctx: ExecutionContext, alias="", dbIndex="0",
                            redisKey="", redisValue="", **_kw) -> None:
    c = _c(ctx, alias, dbIndex)
    members = [v for v in str(redisValue).split(",") if v != ""] or [redisValue]
    c.zrem(redisKey, *members)


# noinspection PyPep8Naming
@keyword("redis_del_RedisKeyFromFile", name="批量删除redis中key", category="Public",
         legacy_impl="RedisKeyword:deleteRedisKeyFromFile")
def delete_redis_key_from_file(ctx: ExecutionContext, alias="", dbIndex="0",
                               filePath="", **_kw) -> None:
    c = _c(ctx, alias, dbIndex)
    with open(filePath, "r", encoding="utf-8") as f:
        keys = [line.strip() for line in f if line.strip()]
    if keys:
        c.delete(*keys)


# ---------------------------------------------------------------- 校验 (verify)

# noinspection PyPep8Naming
@keyword("redis_verify_KeysNum", name="校验redis中匹配key个数", category="Public",
         legacy_impl="RedisKeyword:verifyKeysNum")
def verify_keys_num(ctx: ExecutionContext, alias="", dbIndex="0", redisKey="",
                    num="", **_kw) -> None:
    c = _c(ctx, alias, dbIndex)
    actual = len(c.keys(redisKey))
    expected = int(num)
    if actual != expected:
        raise KeywordError(
            f"匹配 key 个数校验失败：模式={redisKey!r} 期望={expected} 实际={actual}")
